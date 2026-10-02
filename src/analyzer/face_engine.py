import os
import sys
import math
import time
import shutil
import urllib.request
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import sqlite3
import cv2
import numpy as np
from PIL import Image, ImageOps

from src.config import (
    BASE_DIR, DATA_DIR, FACES_DIR, MODELS_DIR, PHOTO_EXTS, VIDEO_EXTS, RAW_EXTS
)
from src.core.db import get_db, db_transaction
from src.core.logger import get_logger

logger = get_logger("faces")

YUNET_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"

YUNET_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_PATH = MODELS_DIR / "face_recognition_sface_2021dec.onnx"

# Cosine similarity matching threshold for SFace (values >= threshold considered same person)
SIMILARITY_MATCH_THRESHOLD = 0.40
VIDEO_DUPLICATE_THRESHOLD = 0.80

_models_lock = threading.Lock()
_thread_local = threading.local()

def ensure_models() -> bool:
    """Download YuNet and SFace ONNX models to MODELS_DIR if missing."""
    with _models_lock:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        FACES_DIR.mkdir(parents=True, exist_ok=True)
        
        headers = {"User-Agent": "Mozilla/5.0 FocusloopLabs/2.1"}

        if not YUNET_PATH.exists() or YUNET_PATH.stat().st_size < 10000:
            logger.info(f"Downloading face detection model (YuNet) to {YUNET_PATH}...")
            req = urllib.request.Request(YUNET_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp, open(YUNET_PATH, "wb") as f:
                shutil.copyfileobj(resp, f)
            logger.info(f"YuNet downloaded successfully ({YUNET_PATH.stat().st_size} bytes)")

        if not SFACE_PATH.exists() or SFACE_PATH.stat().st_size < 1000000:
            logger.info(f"Downloading face recognition model (SFace) to {SFACE_PATH}...")
            req = urllib.request.Request(SFACE_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp, open(SFACE_PATH, "wb") as f:
                shutil.copyfileobj(resp, f)
            logger.info(f"SFace downloaded successfully ({SFACE_PATH.stat().st_size} bytes)")

        return YUNET_PATH.exists() and SFACE_PATH.exists()

def _get_detector(input_size: Tuple[int, int] = (640, 640)) -> cv2.FaceDetectorYN:
    """Thread-local instance of YuNet face detector."""
    ensure_models()
    if not hasattr(_thread_local, "detector") or _thread_local.detector is None:
        detector = cv2.FaceDetectorYN.create(
            str(YUNET_PATH),
            "",
            input_size,
            score_threshold=0.6,
            nms_threshold=0.3,
            top_k=5000
        )
        _thread_local.detector = detector
        _thread_local.detector_size = input_size
    else:
        if getattr(_thread_local, "detector_size", None) != input_size:
            _thread_local.detector.setInputSize(input_size)
            _thread_local.detector_size = input_size
    return _thread_local.detector

def _get_recognizer() -> cv2.FaceRecognizerSF:
    """Thread-local instance of SFace recognizer."""
    ensure_models()
    if not hasattr(_thread_local, "recognizer") or _thread_local.recognizer is None:
        _thread_local.recognizer = cv2.FaceRecognizerSF.create(str(SFACE_PATH), "")
    return _thread_local.recognizer

def _read_image_bgr(file_path: Path, max_dim: int = 1280) -> Tuple[Optional[np.ndarray], float]:
    """
    Read image from file into OpenCV BGR format with proper orientation.
    Returns (bgr_image, scale_factor).
    """
    try:
        # Use PIL first for EXIF orientation and format handling
        with Image.open(file_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            orig_w, orig_h = img.size
            scale = 1.0
            if max(orig_w, orig_h) > max_dim:
                scale = max_dim / max(orig_w, orig_h)
                new_w = max(1, int(orig_w * scale))
                new_h = max(1, int(orig_h * scale))
                img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
            
            rgb_arr = np.array(img)
            bgr_arr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
            return bgr_arr, scale
    except Exception as e:
        logger.warning(f"Could not read image {file_path}: {e}")
        return None, 1.0

class FaceEngine:
    """
    Core engine for face detection, embedding extraction, clustering,
    naming, and collection organization for Focusloop Labs Studio.
    """

    def __init__(self):
        self._scan_lock = threading.Lock()
        self._cancel_scan_event = threading.Event()
        self.scan_state: Dict[str, Any] = {
            "is_running": False,
            "total_files": 0,
            "scanned_files": 0,
            "faces_found": 0,
            "current_file": "",
            "progress_pct": 0.0,
            "error": None,
            "start_time": None
        }

    # -------------------------------------------------------------
    # Low-level Detection & Embedding Extraction
    # -------------------------------------------------------------

    def detect_and_embed_image(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Detect faces in a photo and extract their 128-d embeddings.
        Returns list of face dicts:
        [{ "box": (x, y, w, h), "conf": float, "raw_face": array, "embedding": bytes, "crop": np.ndarray }]
        """
        bgr, scale = _read_image_bgr(file_path)
        if bgr is None:
            return []

        h, w = bgr.shape[:2]
        detector = _get_detector(input_size=(w, h))
        recognizer = _get_recognizer()

        _, faces = detector.detect(bgr)
        if faces is None:
            return []

        results = []
        for face in faces:
            conf = float(face[14])
            if conf < 0.60:
                continue

            # Original coordinates
            bx, by, bw, bh = int(face[0] / scale), int(face[1] / scale), int(face[2] / scale), int(face[3] / scale)
            if bw < 24 or bh < 24:
                continue

            try:
                aligned = recognizer.alignCrop(bgr, face)
                feature = recognizer.feature(aligned) # shape (1, 128), float32
                # L2 normalize just to be absolutely sure
                norm = np.linalg.norm(feature)
                if norm > 0:
                    feature = feature / norm
                feat_bytes = feature.astype(np.float32).tobytes()

                # Extract a cropped avatar with 30% margin for nice visual display
                margin_x = int(face[2] * 0.35)
                margin_y = int(face[3] * 0.35)
                x1 = max(0, int(face[0]) - margin_x)
                y1 = max(0, int(face[1]) - margin_y)
                x2 = min(w, int(face[0] + face[2]) + margin_x)
                y2 = min(h, int(face[1] + face[3]) + margin_y)
                crop = bgr[y1:y2, x1:x2].copy()

                results.append({
                    "box": (bx, by, bw, bh),
                    "confidence": conf,
                    "raw_face": face,
                    "embedding": feat_bytes,
                    "crop": crop,
                    "timestamp_sec": 0.0
                })
            except Exception as e:
                logger.debug(f"Failed to extract face feature in {file_path}: {e}")

        return results

    def detect_and_embed_video(
        self,
        file_path: Path,
        step_sec: float = 1.5,
        max_duration_sec: float = 7200.0
    ) -> List[Dict[str, Any]]:
        """
        Sample video frames at step_sec intervals, detect faces, and de-duplicate
        redundant sightings of the same person within a temporal window.
        """
        cap = cv2.VideoCapture(str(file_path))
        if not cap.isOpened():
            logger.warning(f"Failed to open video {file_path}")
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0.0
        duration = min(duration, max_duration_sec)

        recognizer = _get_recognizer()
        results: List[Dict[str, Any]] = []
        recent_embeddings: List[Tuple[float, np.ndarray]] = [] # [(timestamp, feat)]

        t = 0.0
        while t < duration:
            if self._cancel_scan_event.is_set():
                break

            frame_idx = int(t * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                t += step_sec
                continue

            fh, fw = frame.shape[:2]
            scale = 1.0
            max_dim = 1080
            if max(fw, fh) > max_dim:
                scale = max_dim / max(fw, fh)
                sw = max(1, int(fw * scale))
                sh = max(1, int(fh * scale))
                scaled_frame = cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA)
            else:
                scaled_frame = frame

            sh, sw = scaled_frame.shape[:2]
            detector = _get_detector(input_size=(sw, sh))
            _, faces = detector.detect(scaled_frame)

            if faces is not None:
                for face in faces:
                    conf = float(face[14])
                    if conf < 0.65:
                        continue

                    bx = int(face[0] / scale)
                    by = int(face[1] / scale)
                    bw = int(face[2] / scale)
                    bh = int(face[3] / scale)
                    if bw < 28 or bh < 28:
                        continue

                    try:
                        aligned = recognizer.alignCrop(scaled_frame, face)
                        feature = recognizer.feature(aligned)
                        norm = np.linalg.norm(feature)
                        if norm > 0:
                            feature = feature / norm

                        # De-duplicate: check if identical face was seen within last 4 seconds
                        is_duplicate = False
                        current_t = round(t, 2)
                        for prev_t, prev_feat in recent_embeddings:
                            if (current_t - prev_t) <= 4.0:
                                sim = float(np.dot(feature.flatten(), prev_feat.flatten()))
                                if sim >= VIDEO_DUPLICATE_THRESHOLD:
                                    is_duplicate = True
                                    break

                        if is_duplicate:
                            continue

                        recent_embeddings.append((current_t, feature))
                        if len(recent_embeddings) > 30:
                            recent_embeddings.pop(0)

                        feat_bytes = feature.astype(np.float32).tobytes()

                        margin_x = int(face[2] * 0.35)
                        margin_y = int(face[3] * 0.35)
                        x1 = max(0, int(face[0]) - margin_x)
                        y1 = max(0, int(face[1]) - margin_y)
                        x2 = min(sw, int(face[0] + face[2]) + margin_x)
                        y2 = min(sh, int(face[1] + face[3]) + margin_y)
                        crop = scaled_frame[y1:y2, x1:x2].copy()

                        results.append({
                            "box": (bx, by, bw, bh),
                            "confidence": conf,
                            "raw_face": face,
                            "embedding": feat_bytes,
                            "crop": crop,
                            "timestamp_sec": current_t
                        })
                    except Exception as e:
                        logger.debug(f"Video frame face extraction failed at {t}s: {e}")

            t += step_sec

        cap.release()
        return results

    # -------------------------------------------------------------
    # File Processing & Database Storage
    # -------------------------------------------------------------

    def process_file_faces(self, file_id: int, file_path: Path, media_type: str, step_sec: float = 1.5) -> int:
        """
        Detects faces in a file, stores them in database, saves crops,
        and matches against known people. Returns number of faces found.
        """
        if media_type == "video":
            detections = self.detect_and_embed_video(file_path, step_sec=step_sec)
        else:
            detections = self.detect_and_embed_image(file_path)

        if not detections:
            return 0

        # Load active people and their average embeddings for fast matching
        known_people = self._get_known_people_centroids()

        faces_stored = 0
        with db_transaction() as conn:
            cursor = conn.cursor()

            for det in detections:
                emb_bytes = det["embedding"]
                feat_vec = np.frombuffer(emb_bytes, dtype=np.float32)

                # Match against known named people first
                best_person_id = None
                best_sim = -1.0

                for p_id, p_info in known_people.items():
                    sim = float(np.dot(feat_vec, p_info["centroid"]))
                    if sim > best_sim and sim >= SIMILARITY_MATCH_THRESHOLD:
                        best_sim = sim
                        best_person_id = p_id

                bx, by, bw, bh = det["box"]
                cursor.execute("""
                    INSERT INTO face_detections (
                        file_id, person_id, timestamp_sec,
                        box_x, box_y, box_w, box_h,
                        confidence, embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    file_id,
                    best_person_id,
                    det["timestamp_sec"],
                    bx, by, bw, bh,
                    det["confidence"],
                    emb_bytes
                ))
                face_id = cursor.lastrowid

                # Save face crop image to FACES_DIR / {face_id}.jpg
                crop_img = det.get("crop")
                if crop_img is not None and crop_img.size > 0:
                    crop_filename = f"{face_id}.jpg"
                    crop_full_path = FACES_DIR / crop_filename
                    try:
                        # Resize crop to standard avatar dimension (e.g. 200x200 max)
                        ch, cw = crop_img.shape[:2]
                        if max(cw, ch) > 240:
                            sc = 240.0 / max(cw, ch)
                            crop_img = cv2.resize(crop_img, (max(1, int(cw * sc)), max(1, int(ch * sc))), interpolation=cv2.INTER_AREA)
                        cv2.imwrite(str(crop_full_path), crop_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                        cursor.execute("UPDATE face_detections SET thumbnail_path = ? WHERE id = ?", (crop_filename, face_id))
                    except Exception as e:
                        logger.warning(f"Could not save face crop {crop_full_path}: {e}")

                # If matched to a person and person doesn't have an avatar yet, assign this face
                if best_person_id:
                    cursor.execute("""
                        UPDATE people SET avatar_face_id = ?
                        WHERE id = ? AND (avatar_face_id IS NULL OR avatar_face_id = 0)
                    """, (face_id, best_person_id))

                faces_stored += 1

        return faces_stored

    def _get_known_people_centroids(self) -> Dict[int, Dict[str, Any]]:
        """Calculate the average normalized embedding for all people."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM people WHERE is_hidden = 0")
        people_rows = cursor.fetchall()
        result = {}

        for p in people_rows:
            p_id = p["id"]
            cursor.execute("SELECT embedding FROM face_detections WHERE person_id = ?", (p_id,))
            emb_rows = cursor.fetchall()
            if not emb_rows:
                continue

            vectors = [np.frombuffer(r["embedding"], dtype=np.float32) for r in emb_rows]
            avg_vec = np.mean(vectors, axis=0)
            norm = np.linalg.norm(avg_vec)
            if norm > 0:
                avg_vec = avg_vec / norm

            result[p_id] = {
                "name": p["name"],
                "centroid": avg_vec,
                "count": len(vectors)
            }

        return result

    # -------------------------------------------------------------
    # Auto-Clustering & Grouping of Unnamed Faces
    # -------------------------------------------------------------

    def cluster_unassigned_faces(self, threshold: float = 0.40) -> Dict[str, Any]:
        """
        Group unassigned faces (person_id IS NULL) into clusters.
        Creates unnamed Person records ('Unnamed Person #X') with avatar.
        """
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, embedding FROM face_detections
            WHERE person_id IS NULL
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        if not rows:
            return {"clusters_formed": 0, "faces_grouped": 0}

        face_ids = []
        emb_list = []
        for r in rows:
            raw = r["embedding"]
            if not raw:
                continue
            v = np.frombuffer(raw, dtype=np.float32)
            if len(v) >= 128:
                face_ids.append(r["id"])
                emb_list.append(v[:128])

        if not face_ids:
            return {"clusters_formed": 0, "faces_grouped": 0}

        embeddings = np.array(emb_list, dtype=np.float32)

        # Normalize
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = embeddings / norms

        N = len(face_ids)
        if N == 1:
            # Single face: create a new person
            with db_transaction() as wconn:
                wcursor = wconn.cursor()
                wcursor.execute("INSERT INTO people (name, avatar_face_id) VALUES (?, ?)", ("Unnamed Person", face_ids[0]))
                p_id = wcursor.lastrowid
                wcursor.execute("UPDATE face_detections SET person_id = ? WHERE id = ?", (p_id, face_ids[0]))
            return {"clusters_formed": 1, "faces_grouped": 1}

        # Pairwise Cosine Distance = 1.0 - Cosine Similarity
        # SFace cosine similarity is in [-1, 1], identical is 1.0.
        sim_matrix = np.dot(embeddings, embeddings.T)
        dist_matrix = np.maximum(0.0, 1.0 - sim_matrix)
        # Ensure diagonal is exactly 0
        np.fill_diagonal(dist_matrix, 0.0)

        # Hierarchical agglomerative clustering
        try:
            from scipy.spatial.distance import squareform
            from scipy.cluster.hierarchy import linkage, fcluster
            condensed = squareform(dist_matrix, checks=False)
            Z = linkage(condensed, method="average")
            # Distance threshold = 1.0 - similarity threshold (e.g. 1.0 - 0.40 = 0.60)
            dist_threshold = max(0.1, 1.0 - threshold)
            labels = fcluster(Z, t=dist_threshold, criterion="distance")
        except Exception as e:
            logger.warning(f"Clustering fallback to greedy graph: {e}")
            labels = self._greedy_cluster(sim_matrix, threshold)

        # Group face_ids by cluster label
        clusters: Dict[int, List[int]] = {}
        for idx, lbl in enumerate(labels):
            clusters.setdefault(lbl, []).append(face_ids[idx])

        clusters_formed = 0
        faces_grouped = 0

        # Check existing unnamed people count for naming ("Unnamed Person 1", etc.)
        cursor.execute("SELECT COUNT(*) FROM people WHERE name LIKE 'Unnamed Person%'")
        unnamed_base = cursor.fetchone()[0]

        with db_transaction() as wconn:
            wcursor = wconn.cursor()
            for lbl, f_ids in clusters.items():
                if not f_ids:
                    continue
                unnamed_base += 1
                person_name = f"Unnamed Person {unnamed_base}"
                avatar_face_id = f_ids[0]

                wcursor.execute("INSERT INTO people (name, avatar_face_id) VALUES (?, ?)", (person_name, avatar_face_id))
                new_person_id = wcursor.lastrowid

                placeholders = ",".join("?" for _ in f_ids)
                wcursor.execute(f"UPDATE face_detections SET person_id = ? WHERE id IN ({placeholders})", [new_person_id] + f_ids)
                clusters_formed += 1
                faces_grouped += len(f_ids)

        return {"clusters_formed": clusters_formed, "faces_grouped": faces_grouped}

    def _greedy_cluster(self, sim_matrix: np.ndarray, threshold: float) -> List[int]:
        """Greedy connected-component fallback clustering."""
        n = sim_matrix.shape[0]
        visited = [False] * n
        labels = [0] * n
        current_cluster = 1

        for i in range(n):
            if not visited[i]:
                queue = [i]
                visited[i] = True
                labels[i] = current_cluster
                while queue:
                    curr = queue.pop(0)
                    for j in range(n):
                        if not visited[j] and sim_matrix[curr, j] >= threshold:
                            visited[j] = True
                            labels[j] = current_cluster
                            queue.append(j)
                current_cluster += 1
        return labels

    # -------------------------------------------------------------
    # Person & Face Management Actions (Name, Merge, Unlink)
    # -------------------------------------------------------------

    def rename_person(self, person_id: int, new_name: str, sync_to_tags: bool = True) -> Dict[str, Any]:
        """
        Name or rename a person.
        If sync_to_tags is True, automatically updates file_tags ('speaker' category)
        for all associated photos and videos.
        """
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Person name cannot be blank")

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM people WHERE id = ?", (person_id,))
            person = cursor.fetchone()
            if not person:
                raise ValueError(f"Person with ID {person_id} not found")

            old_name = person["name"]
            cursor.execute("UPDATE people SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_name, person_id))

            # Find all files where this person appears
            cursor.execute("SELECT DISTINCT file_id FROM face_detections WHERE person_id = ?", (person_id,))
            file_ids = [r[0] for r in cursor.fetchall()]

            if sync_to_tags and file_ids:
                # Remove old speaker tag if old_name was not 'Unnamed Person...'
                if not old_name.startswith("Unnamed Person"):
                    placeholders = ",".join("?" for _ in file_ids)
                    cursor.execute(f"""
                        DELETE FROM file_tags
                        WHERE category = 'speaker' AND tag = ? AND file_id IN ({placeholders})
                    """, [old_name] + file_ids)

                # Insert new speaker tag
                for fid in file_ids:
                    cursor.execute("""
                        INSERT OR IGNORE INTO file_tags (file_id, tag, category)
                        VALUES (?, ?, 'speaker')
                    """, (fid, new_name))

        return {
            "person_id": person_id,
            "old_name": old_name,
            "new_name": new_name,
            "files_tagged": len(file_ids) if sync_to_tags else 0
        }

    def merge_people(self, target_person_id: int, source_person_ids: List[int]) -> Dict[str, Any]:
        """
        Combine multiple person clusters into one person (Google Photos merge style).
        Reassigns all face detections from source people into target person,
        and deletes the source people.
        """
        source_ids = [pid for pid in source_person_ids if pid != target_person_id]
        if not source_ids:
            return {"target_person_id": target_person_id, "faces_merged": 0}

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, avatar_face_id FROM people WHERE id = ?", (target_person_id,))
            target = cursor.fetchone()
            if not target:
                raise ValueError(f"Target person with ID {target_person_id} not found")

            target_name = target["name"]
            avatar_id = target["avatar_face_id"]

            placeholders = ",".join("?" for _ in source_ids)

            # Move all faces
            cursor.execute(f"""
                UPDATE face_detections
                SET person_id = ?
                WHERE person_id IN ({placeholders})
            """, [target_person_id] + source_ids)
            faces_merged = cursor.rowcount

            # If target has no avatar, pick the first available face
            if not avatar_id:
                cursor.execute("SELECT id FROM face_detections WHERE person_id = ? LIMIT 1", (target_person_id,))
                first_face = cursor.fetchone()
                if first_face:
                    cursor.execute("UPDATE people SET avatar_face_id = ? WHERE id = ?", (first_face[0], target_person_id))

            # Delete source people
            cursor.execute(f"DELETE FROM people WHERE id IN ({placeholders})", source_ids)

            # Sync speaker tags for newly associated files if target person is named
            if not target_name.startswith("Unnamed Person"):
                cursor.execute("SELECT DISTINCT file_id FROM face_detections WHERE person_id = ?", (target_person_id,))
                all_fids = [r[0] for r in cursor.fetchall()]
                for fid in all_fids:
                    cursor.execute("""
                        INSERT OR IGNORE INTO file_tags (file_id, tag, category)
                        VALUES (?, ?, 'speaker')
                    """, (fid, target_name))

        return {
            "target_person_id": target_person_id,
            "faces_merged": faces_merged,
            "merged_people_count": len(source_ids)
        }

    def unlink_face(self, face_id: int) -> bool:
        """Unlink a false match from a person (sets person_id = NULL)."""
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT person_id FROM face_detections WHERE id = ?", (face_id,))
            face = cursor.fetchone()
            if not face:
                return False

            old_person_id = face["person_id"]
            cursor.execute("UPDATE face_detections SET person_id = NULL WHERE id = ?", (face_id,))

            # If this face was the person's avatar, pick another face as avatar
            if old_person_id:
                cursor.execute("""
                    SELECT avatar_face_id FROM people WHERE id = ?
                """, (old_person_id,))
                p_row = cursor.fetchone()
                if p_row and p_row["avatar_face_id"] == face_id:
                    cursor.execute("SELECT id FROM face_detections WHERE person_id = ? LIMIT 1", (old_person_id,))
                    next_face = cursor.fetchone()
                    new_avatar = next_face[0] if next_face else None
                    cursor.execute("UPDATE people SET avatar_face_id = ? WHERE id = ?", (new_avatar, old_person_id))

        return True

    def assign_face(self, face_id: int, target_person_id: int) -> bool:
        """Assign or reassign an individual face to a specific person."""
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM people WHERE id = ?", (target_person_id,))
            person = cursor.fetchone()
            if not person:
                raise ValueError("Target person does not exist")

            cursor.execute("UPDATE face_detections SET person_id = ? WHERE id = ?", (target_person_id, face_id))

            # Auto-tag file if person is named
            p_name = person["name"]
            if not p_name.startswith("Unnamed Person"):
                cursor.execute("SELECT file_id FROM face_detections WHERE id = ?", (face_id,))
                f_row = cursor.fetchone()
                if f_row:
                    cursor.execute("""
                        INSERT OR IGNORE INTO file_tags (file_id, tag, category)
                        VALUES (?, ?, 'speaker')
                    """, (f_row[0], p_name))

        return True

    def set_person_avatar(self, person_id: int, face_id: int) -> bool:
        """Set a specific face as the cover avatar for this person."""
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE people SET avatar_face_id = ? WHERE id = ?", (face_id, person_id))
        return True

    def delete_person(self, person_id: int) -> bool:
        """Delete a person record; its face detections become unassigned."""
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE face_detections SET person_id = NULL WHERE person_id = ?", (person_id,))
            cursor.execute("DELETE FROM people WHERE id = ?", (person_id,))
        return True

    # -------------------------------------------------------------
    # People & Media Queries
    # -------------------------------------------------------------

    def list_people(
        self,
        source_id: Optional[int] = None,
        folder_filter: Optional[str] = None,
        filter_type: str = "all", # "all", "named", "unnamed"
        sort_by: str = "count"    # "count", "name", "recent"
    ) -> List[Dict[str, Any]]:
        """
        List all people with counts, avatar thumbnail URL, and media stats.
        Optionally scoped by drive (source_id) or folder.
        """
        conn = get_db()
        cursor = conn.cursor()

        # Build scope filter for files
        scope_conditions = ["p.is_hidden = 0"]
        scope_params: List[Any] = []

        if source_id is not None and source_id > 0:
            scope_conditions.append("f.source_id = ?")
            scope_params.append(source_id)

        if folder_filter:
            norm_folder = folder_filter.replace("\\", "/").strip("/")
            scope_conditions.append("(f.rel_path LIKE ? OR f.rel_path LIKE ?)")
            scope_params.append(f"{norm_folder}/%")
            scope_params.append(f"{norm_folder}")

        where_clause = " AND ".join(scope_conditions)

        query = f"""
            SELECT
                p.id,
                p.name,
                p.avatar_face_id,
                p.created_at,
                p.updated_at,
                COUNT(fd.id) as face_count,
                COUNT(DISTINCT fd.file_id) as file_count,
                COUNT(DISTINCT CASE WHEN f.media_type = 'video' THEN fd.file_id END) as video_count,
                COUNT(DISTINCT CASE WHEN f.media_type != 'video' THEN fd.file_id END) as photo_count,
                af.thumbnail_path as avatar_thumbnail
            FROM people p
            LEFT JOIN face_detections fd ON fd.person_id = p.id
            LEFT JOIN files f ON f.id = fd.file_id
            LEFT JOIN face_detections af ON af.id = p.avatar_face_id
            WHERE {where_clause}
            GROUP BY p.id
        """

        cursor.execute(query, scope_params)
        rows = cursor.fetchall()

        results = []
        for r in rows:
            name = r["name"]
            is_named = not name.startswith("Unnamed Person")

            if filter_type == "named" and not is_named:
                continue
            if filter_type == "unnamed" and is_named:
                continue

            avatar_thumb = r["avatar_thumbnail"]
            avatar_url = f"/api/faces/thumbnail/{r['avatar_face_id']}" if avatar_thumb else None

            results.append({
                "id": r["id"],
                "name": name,
                "is_named": is_named,
                "avatar_face_id": r["avatar_face_id"],
                "avatar_url": avatar_url,
                "face_count": r["face_count"],
                "file_count": r["file_count"],
                "video_count": r["video_count"],
                "photo_count": r["photo_count"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"]
            })

        # Sorting
        if sort_by == "name":
            results.sort(key=lambda x: (not x["is_named"], x["name"].lower()))
        elif sort_by == "recent":
            results.sort(key=lambda x: x["updated_at"] or "", reverse=True)
        else: # "count" (default Google Photos style: most frequent first)
            results.sort(key=lambda x: x["face_count"], reverse=True)

        return results

    def get_person_details(self, person_id: int) -> Dict[str, Any]:
        """Get full details of a person and list of all media files containing them."""
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT p.*, af.thumbnail_path as avatar_thumbnail
            FROM people p
            LEFT JOIN face_detections af ON af.id = p.avatar_face_id
            WHERE p.id = ?
        """, (person_id,))
        p_row = cursor.fetchone()
        if not p_row:
            raise ValueError(f"Person {person_id} not found")

        cursor.execute("""
            SELECT
                fd.id as face_id,
                fd.file_id,
                fd.timestamp_sec,
                fd.box_x, fd.box_y, fd.box_w, fd.box_h,
                fd.confidence,
                fd.thumbnail_path as face_thumbnail,
                f.filename,
                f.rel_path,
                f.abs_path,
                f.media_type,
                f.size_bytes,
                f.mtime,
                s.label as source_label,
                s.drive_type
            FROM face_detections fd
            JOIN files f ON f.id = fd.file_id
            LEFT JOIN sources s ON s.id = f.source_id
            WHERE fd.person_id = ?
            ORDER BY f.mtime DESC, fd.timestamp_sec ASC
        """, (person_id,))
        detections = cursor.fetchall()

        # Group detections by file_id
        media_map: Dict[int, Dict[str, Any]] = {}
        for d in detections:
            fid = d["file_id"]
            if fid not in media_map:
                media_map[fid] = {
                    "file_id": fid,
                    "filename": d["filename"],
                    "rel_path": d["rel_path"],
                    "abs_path": d["abs_path"],
                    "media_type": d["media_type"],
                    "size_bytes": d["size_bytes"],
                    "mtime": d["mtime"],
                    "source_label": d["source_label"],
                    "faces": []
                }
            media_map[fid]["faces"].append({
                "face_id": d["face_id"],
                "timestamp_sec": d["timestamp_sec"],
                "box": [d["box_x"], d["box_y"], d["box_w"], d["box_h"]],
                "confidence": d["confidence"],
                "thumbnail_url": f"/api/faces/thumbnail/{d['face_id']}" if d["face_thumbnail"] else None
            })

        avatar_url = f"/api/faces/thumbnail/{p_row['avatar_face_id']}" if p_row["avatar_thumbnail"] else None

        return {
            "id": p_row["id"],
            "name": p_row["name"],
            "is_named": not p_row["name"].startswith("Unnamed Person"),
            "avatar_face_id": p_row["avatar_face_id"],
            "avatar_url": avatar_url,
            "created_at": p_row["created_at"],
            "total_faces": len(detections),
            "total_media": len(media_map),
            "media": list(media_map.values())
        }

    # -------------------------------------------------------------
    # Background Scanner Job
    # -------------------------------------------------------------

    def start_scan_job(
        self,
        source_id: Optional[int] = None,
        folder_filter: Optional[str] = None,
        media_type_filter: str = "all", # "all", "photo", "video"
        step_sec: float = 1.5,
        force_rescan: bool = False
    ) -> Dict[str, Any]:
        """Launch background scan thread for faces across specified scope."""
        with self._scan_lock:
            if self.scan_state["is_running"]:
                return {"status": "already_running", "message": "Face scan is already in progress"}

            self._cancel_scan_event.clear()
            self.scan_state["is_running"] = True
            self.scan_state["scanned_files"] = 0
            self.scan_state["faces_found"] = 0
            self.scan_state["current_file"] = "Initializing..."
            self.scan_state["progress_pct"] = 0.0
            self.scan_state["error"] = None
            self.scan_state["start_time"] = time.time()

            t = threading.Thread(
                target=self._scan_worker,
                args=(source_id, folder_filter, media_type_filter, step_sec, force_rescan),
                daemon=True
            )
            t.start()

            return {"status": "started", "message": "Face scan started in background"}

    def cancel_scan(self) -> Dict[str, Any]:
        """Cancel the ongoing face scan."""
        with self._scan_lock:
            if not self.scan_state["is_running"]:
                return {"status": "not_running", "message": "No scan is currently running"}
            self._cancel_scan_event.set()
            return {"status": "canceling", "message": "Face scan cancellation requested"}

    def _scan_worker(
        self,
        source_id: Optional[int],
        folder_filter: Optional[str],
        media_type_filter: str,
        step_sec: float,
        force_rescan: bool
    ):
        """Worker thread executing face detection on files."""
        try:
            ensure_models()

            conn = get_db()
            cursor = conn.cursor()

            conditions = ["f.status = 'active'"]
            params: List[Any] = []

            # Media type condition
            if media_type_filter == "photo":
                conditions.append("f.media_type IN ('photo', 'raw')")
            elif media_type_filter == "video":
                conditions.append("f.media_type = 'video'")
            else:
                conditions.append("f.media_type IN ('photo', 'raw', 'video')")

            # Scope by source
            if source_id is not None and source_id > 0:
                conditions.append("f.source_id = ?")
                params.append(source_id)

            # Scope by folder
            if folder_filter:
                norm_folder = folder_filter.replace("\\", "/").strip("/")
                conditions.append("(f.rel_path LIKE ? OR f.rel_path LIKE ?)")
                params.append(f"{norm_folder}/%")
                params.append(f"{norm_folder}")

            # Force rescan vs skipping already-scanned files
            if not force_rescan:
                conditions.append("f.id NOT IN (SELECT DISTINCT file_id FROM face_detections)")

            where_sql = " AND ".join(conditions)
            cursor.execute(f"SELECT f.id, f.abs_path, f.filename, f.media_type FROM files f WHERE {where_sql}", params)
            files_to_scan = cursor.fetchall()

            total = len(files_to_scan)
            self.scan_state["total_files"] = total

            logger.info(f"Starting Face Scan on {total} media files...")

            for idx, f in enumerate(files_to_scan):
                if self._cancel_scan_event.is_set():
                    logger.info("Face Scan canceled by user.")
                    break

                fid = f["id"]
                fpath = Path(f["abs_path"])
                mtype = f["media_type"]
                fname = f["filename"]

                self.scan_state["current_file"] = fname
                self.scan_state["progress_pct"] = round((idx / total) * 100, 1) if total > 0 else 100.0

                if fpath.exists():
                    try:
                        faces_found = self.process_file_faces(fid, fpath, mtype, step_sec=step_sec)
                        self.scan_state["faces_found"] += faces_found
                    except Exception as e:
                        logger.warning(f"Error scanning faces in {fname}: {e}")

                self.scan_state["scanned_files"] = idx + 1

            # Auto-cluster newly found faces at the end of the scan
            if self.scan_state["faces_found"] > 0 and not self._cancel_scan_event.is_set():
                self.scan_state["current_file"] = "Auto-clustering people..."
                try:
                    cluster_res = self.cluster_unassigned_faces()
                    logger.info(f"Clustering complete: {cluster_res}")
                except Exception as e:
                    logger.warning(f"Error during auto-clustering: {e}")

            self.scan_state["progress_pct"] = 100.0
            self.scan_state["current_file"] = "Scan completed"

        except Exception as e:
            logger.error(f"Face Scan job failed: {e}", exc_info=True)
            self.scan_state["error"] = str(e)
        finally:
            self.scan_state["is_running"] = False


# Global singleton engine instance
face_engine = FaceEngine()
