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
import base64
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
            try:
                req = urllib.request.Request(YUNET_URL, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp, open(YUNET_PATH, "wb") as f:
                    shutil.copyfileobj(resp, f)
                logger.info(f"YuNet downloaded successfully ({YUNET_PATH.stat().st_size} bytes)")
            except Exception as e:
                logger.warning(f"Could not download YuNet model: {e}")

        if not SFACE_PATH.exists() or SFACE_PATH.stat().st_size < 1000000:
            logger.info(f"Downloading face recognition model (SFace) to {SFACE_PATH}...")
            try:
                req = urllib.request.Request(SFACE_URL, headers=headers)
                with urllib.request.urlopen(req, timeout=45) as resp, open(SFACE_PATH, "wb") as f:
                    shutil.copyfileobj(resp, f)
                logger.info(f"SFace downloaded successfully ({SFACE_PATH.stat().st_size} bytes)")
            except Exception as e:
                logger.warning(f"Could not download SFace model: {e}")

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

# Clamp OpenCV CPU threads to 1 to prevent maxing out CPU cores during background scan
try:
    cv2.setNumThreads(1)
except Exception:
    pass

_gpu_session = None
_gpu_init_attempted = False

def _get_gpu_session():
    global _gpu_session, _gpu_init_attempted
    if _gpu_init_attempted:
        return _gpu_session
    _gpu_init_attempted = True
    try:
        import torch
        torch_lib = os.path.join(os.path.dirname(torch.__file__), 'lib')
        if hasattr(os, 'add_dll_directory') and os.path.isdir(torch_lib):
            os.add_dll_directory(torch_lib)
        if torch_lib not in os.environ.get('PATH', ''):
            os.environ['PATH'] = torch_lib + os.pathsep + os.environ.get('PATH', '')

        import onnxruntime as ort
        if 'CUDAExecutionProvider' in ort.get_available_providers():
            so = ort.SessionOptions()
            so.intra_op_num_threads = 1
            so.inter_op_num_threads = 1
            so.log_severity_level = 3  # Suppress verbose warnings
            ensure_models()
            _gpu_session = ort.InferenceSession(str(SFACE_PATH), so, providers=['CUDAExecutionProvider'])
            logger.info("Face Engine: NVIDIA GeForce RTX 3060 CUDA GPU acceleration ACTIVATED!")
    except Exception as e:
        logger.info(f"Face Engine: Running with CPU fallback ({e})")
    return _gpu_session

def _extract_feature(aligned_crop: np.ndarray, recognizer: cv2.FaceRecognizerSF) -> np.ndarray:
    """Extract 128-d face embedding using RTX 3060 CUDA GPU if available, else CPU."""
    gpu_sess = _get_gpu_session()
    if gpu_sess is not None:
        try:
            blob = cv2.dnn.blobFromImage(aligned_crop, 1.0, (112, 112), (0, 0, 0), swapRB=False, crop=False)
            outputs = gpu_sess.run(None, {'data': blob})
            feature = outputs[0]
            norm = np.linalg.norm(feature)
            if norm > 0:
                feature = feature / norm
            return feature
        except Exception as e:
            logger.debug(f"GPU forward pass failed, fallback to CPU: {e}")

    feature = recognizer.feature(aligned_crop)
    norm = np.linalg.norm(feature)
    if norm > 0:
        feature = feature / norm
    return feature

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
            "is_targeted": False,
            "target_person_id": None,
            "target_person_name": None,
            "matches_found": 0,
            "total_files": 0,
            "scanned_files": 0,
            "faces_found": 0,
            "current_file": "",
            "progress_pct": 0.0,
            "error": None,
            "start_time": None
        }

    @staticmethod
    def _build_folder_sql(folder_filter: str, table_alias: str = "f") -> Tuple[str, List[str]]:
        norm = folder_filter.replace("\\", "/").strip("/")
        cond = f"""(
            REPLACE({table_alias}.abs_path, char(92), '/') LIKE ? 
            OR REPLACE({table_alias}.abs_path, char(92), '/') = ?
            OR REPLACE({table_alias}.rel_path, char(92), '/') LIKE ? 
            OR REPLACE({table_alias}.rel_path, char(92), '/') = ?
            OR REPLACE({table_alias}.abs_path, char(92), '/') LIKE ?
        )"""
        params = [f"{norm}/%", norm, f"{norm}/%", norm, f"%/{norm}/%"]
        return cond, params

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
                feature = _extract_feature(aligned, recognizer)
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
            max_dim = 640  # Native YuNet resolution; prevents high CPU downscaling / inference overhead
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
                        feature = _extract_feature(aligned, recognizer)

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

            time.sleep(0.005)
            t += step_sec

        cap.release()
        return results

    # -------------------------------------------------------------
    # File Processing & Database Storage
    # -------------------------------------------------------------

    def process_file_faces(
        self,
        file_id: int,
        file_path: Path,
        media_type: str,
        step_sec: float = 1.5,
        known_people_cache: Optional[Dict[int, Dict[str, Any]]] = None
    ) -> int:
        """
        Detects faces in a file, stores them in database, saves crops,
        and matches against known people (or creates new person clusters on the fly).
        Returns number of faces found.
        """
        if media_type == "video":
            detections = self.detect_and_embed_video(file_path, step_sec=step_sec)
        else:
            detections = self.detect_and_embed_image(file_path)

        if not detections:
            return 0

        # Load active people and their average embeddings for fast matching
        if known_people_cache is None:
            known_people = self._get_known_people_centroids()
        else:
            known_people = known_people_cache

        faces_stored = 0
        with db_transaction() as conn:
            cursor = conn.cursor()

            for det in detections:
                emb_bytes = det["embedding"]
                feat_vec = np.frombuffer(emb_bytes, dtype=np.float32)

                # Match against known people
                best_person_id = None
                best_sim = -1.0

                for p_id, p_info in known_people.items():
                    sim = float(np.dot(feat_vec, p_info["centroid"]))
                    if sim > best_sim and sim >= SIMILARITY_MATCH_THRESHOLD:
                        best_sim = sim
                        best_person_id = p_id

                # If no existing cluster matched, create a new person IMMEDIATELY on the fly
                if best_person_id is None:
                    cursor.execute("SELECT COUNT(*) FROM people WHERE name LIKE 'Unnamed Person%'")
                    unnamed_num = cursor.fetchone()[0] + 1
                    new_name = f"Unnamed Person {unnamed_num}"
                    cursor.execute("INSERT INTO people (name) VALUES (?)", (new_name,))
                    best_person_id = cursor.lastrowid
                    known_people[best_person_id] = {
                        "name": new_name,
                        "centroid": feat_vec,
                        "count": 1
                    }
                else:
                    # Update running average centroid
                    c = known_people[best_person_id]["centroid"]
                    cnt = known_people[best_person_id]["count"]
                    new_c = (c * cnt + feat_vec) / (cnt + 1)
                    norm = np.linalg.norm(new_c)
                    if norm > 0:
                        new_c = new_c / norm
                    known_people[best_person_id]["centroid"] = new_c
                    known_people[best_person_id]["count"] += 1

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
                        ch, cw = crop_img.shape[:2]
                        if max(cw, ch) > 240:
                            sc = 240.0 / max(cw, ch)
                            crop_img = cv2.resize(crop_img, (max(1, int(cw * sc)), max(1, int(ch * sc))), interpolation=cv2.INTER_AREA)
                        cv2.imwrite(str(crop_full_path), crop_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                        cursor.execute("UPDATE face_detections SET thumbnail_path = ? WHERE id = ?", (crop_filename, face_id))
                    except Exception as e:
                        logger.warning(f"Could not save face crop {crop_full_path}: {e}")

                # If person doesn't have an avatar yet, set this face as avatar
                cursor.execute("""
                    UPDATE people SET avatar_face_id = ?
                    WHERE id = ? AND (avatar_face_id IS NULL OR avatar_face_id = 0)
                """, (face_id, best_person_id))

                # If person is named (not 'Unnamed Person...'), auto-tag the file as speaker
                p_name = known_people[best_person_id]["name"]
                if not p_name.startswith("Unnamed Person"):
                    cursor.execute("""
                        INSERT OR IGNORE INTO file_tags (file_id, tag, category)
                        VALUES (?, ?, 'speaker')
                    """, (file_id, p_name))

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
        sort_by: str = "count",   # "count", "name", "recent", "video_count", "photo_count"
        media_type: str = "all"   # "all", "video", "photo"
    ) -> List[Dict[str, Any]]:
        """
        List all people with counts, avatar thumbnail URL, and media stats.
        Optionally scoped by drive (source_id), folder, and media type.
        """
        conn = get_db()
        cursor = conn.cursor()

        is_scoped = bool((source_id is not None and source_id > 0) or folder_filter)

        # Build scope filter for files
        scope_conditions = ["p.is_hidden = 0"]
        scope_params: List[Any] = []

        if source_id is not None and source_id > 0:
            scope_conditions.append("f.source_id = ?")
            scope_params.append(source_id)

        if folder_filter:
            f_cond, f_params = self._build_folder_sql(folder_filter, "f")
            scope_conditions.append(f_cond)
            scope_params.extend(f_params)

        where_clause = " AND ".join(scope_conditions)
        join_type = "JOIN" if is_scoped else "LEFT JOIN"

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
                MIN(CASE WHEN fd.thumbnail_path IS NOT NULL THEN fd.id END) as scoped_avatar_face_id,
                MIN(CASE WHEN fd.thumbnail_path IS NOT NULL THEN fd.thumbnail_path END) as scoped_thumbnail,
                af.thumbnail_path as global_avatar_thumbnail
            FROM people p
            {join_type} face_detections fd ON fd.person_id = p.id
            {join_type} files f ON f.id = fd.file_id
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

            # Media type filtering
            if media_type == "video" and (r["video_count"] or 0) == 0:
                continue
            if media_type == "photo" and (r["photo_count"] or 0) == 0:
                continue

            # Prefer scoped avatar from current folder/drive if available
            if is_scoped and r["scoped_thumbnail"]:
                avatar_thumb = r["scoped_thumbnail"]
                avatar_face_id = r["scoped_avatar_face_id"] or r["avatar_face_id"]
            else:
                avatar_thumb = r["global_avatar_thumbnail"]
                avatar_face_id = r["avatar_face_id"]

            avatar_url = f"/api/faces/thumbnail/{avatar_face_id}" if avatar_thumb else None

            results.append({
                "id": r["id"],
                "name": name,
                "is_named": is_named,
                "avatar_face_id": avatar_face_id,
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
        elif sort_by == "video_count":
            results.sort(key=lambda x: (x["video_count"], x["face_count"]), reverse=True)
        elif sort_by == "photo_count":
            results.sort(key=lambda x: (x["photo_count"], x["face_count"]), reverse=True)
        else: # "count" (default Google Photos style: most frequent first)
            results.sort(key=lambda x: x["face_count"], reverse=True)

        return results

    def get_person_details(
        self,
        person_id: int,
        source_id: Optional[int] = None,
        folder_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get full details of a person and list of all media files containing them, optionally scoped."""
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

        cursor.execute("SELECT COUNT(id), COUNT(DISTINCT file_id) FROM face_detections WHERE person_id = ?", (person_id,))
        totals = cursor.fetchone()
        total_faces_all = totals[0] if totals else 0
        total_media_all = totals[1] if totals else 0

        is_scoped = bool((source_id is not None and source_id > 0) or folder_filter)
        det_conditions = ["fd.person_id = ?", "f.status = 'active'"]
        det_params: List[Any] = [person_id]

        if source_id is not None and source_id > 0:
            det_conditions.append("f.source_id = ?")
            det_params.append(source_id)

        if folder_filter:
            f_cond, f_params = self._build_folder_sql(folder_filter, "f")
            det_conditions.append(f_cond)
            det_params.extend(f_params)

        det_where = " AND ".join(det_conditions)

        cursor.execute(f"""
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
            WHERE {det_where}
            ORDER BY f.mtime DESC, fd.timestamp_sec ASC
        """, det_params)
        detections = cursor.fetchall()

        # Group detections by file_id
        media_map: Dict[int, Dict[str, Any]] = {}
        scoped_avatar_face_id = None
        for d in detections:
            if scoped_avatar_face_id is None and d["face_thumbnail"]:
                scoped_avatar_face_id = d["face_id"]
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

        display_avatar_id = (scoped_avatar_face_id if is_scoped and scoped_avatar_face_id else p_row["avatar_face_id"])
        avatar_url = f"/api/faces/thumbnail/{display_avatar_id}" if display_avatar_id else None

        return {
            "id": p_row["id"],
            "name": p_row["name"],
            "is_named": not p_row["name"].startswith("Unnamed Person"),
            "avatar_face_id": display_avatar_id,
            "avatar_url": avatar_url,
            "created_at": p_row["created_at"],
            "total_faces": len(detections),
            "total_media": len(media_map),
            "total_faces_all": total_faces_all,
            "total_media_all": total_media_all,
            "is_scoped": is_scoped,
            "media": list(media_map.values())
        }

    def get_faces_by_filename(
        self,
        query: str,
        limit: int = 10,
        source_id: Optional[int] = None,
        folder_filter: Optional[str] = None,
        media_type: str = "all"
    ) -> Dict[str, Any]:
        """
        Search files by filename or path that have face detections,
        returning detected faces from that file and the grouped media
        of all matching people across the collection.
        """
        conn = get_db()
        cursor = conn.cursor()

        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return {"query": "", "matched_files_count": 0, "files": []}

        search_pattern = f"%{cleaned_query}%"

        file_conditions = [
            "(f.filename LIKE ? OR REPLACE(f.rel_path, char(92), '/') LIKE ?)",
            "EXISTS (SELECT 1 FROM face_detections fd WHERE fd.file_id = f.id)",
            "f.status = 'active'"
        ]
        file_params: List[Any] = [search_pattern, search_pattern]

        if source_id is not None and source_id > 0:
            file_conditions.append("f.source_id = ?")
            file_params.append(source_id)

        if folder_filter:
            f_cond, f_params = self._build_folder_sql(folder_filter, "f")
            file_conditions.append(f_cond)
            file_params.extend(f_params)

        if media_type == "video":
            file_conditions.append("f.media_type = 'video'")
        elif media_type == "photo":
            file_conditions.append("f.media_type != 'video'")

        where_files = " AND ".join(file_conditions)

        cursor.execute(f"""
            SELECT f.id, f.filename, f.rel_path, f.abs_path, f.media_type, f.size_bytes, f.mtime,
                   s.label as source_label, s.drive_type
            FROM files f
            LEFT JOIN sources s ON s.id = f.source_id
            WHERE {where_files}
            ORDER BY 
                CASE 
                    WHEN LOWER(f.filename) = LOWER(?) THEN 0
                    WHEN LOWER(f.filename) LIKE LOWER(?) THEN 1
                    ELSE 2
                END,
                f.mtime DESC
            LIMIT ?
        """, file_params + [cleaned_query, f"{cleaned_query}%", limit])
        matched_files = cursor.fetchall()

        if not matched_files:
            return {"query": cleaned_query, "matched_files_count": 0, "files": []}

        results = []
        for mf in matched_files:
            fid = mf["id"]

            cursor.execute("""
                SELECT fd.id as face_id, fd.person_id, fd.timestamp_sec,
                       fd.box_x, fd.box_y, fd.box_w, fd.box_h,
                       fd.confidence, fd.thumbnail_path,
                       p.name as person_name, p.avatar_face_id
                FROM face_detections fd
                LEFT JOIN people p ON p.id = fd.person_id
                WHERE fd.file_id = ?
                ORDER BY fd.timestamp_sec ASC, fd.id ASC
            """, (fid,))
            detections_in_file = cursor.fetchall()

            faces_in_file = []
            distinct_person_ids = []
            unassigned_face_ids = []

            for d in detections_in_file:
                p_id = d["person_id"]
                p_name = d["person_name"] or "Unassigned Face"
                if p_id is not None:
                    if p_id not in distinct_person_ids:
                        distinct_person_ids.append(p_id)
                else:
                    unassigned_face_ids.append(d["face_id"])

                faces_in_file.append({
                    "face_id": d["face_id"],
                    "person_id": p_id,
                    "person_name": p_name,
                    "timestamp_sec": d["timestamp_sec"] or 0.0,
                    "box": [d["box_x"], d["box_y"], d["box_w"], d["box_h"]],
                    "confidence": d["confidence"],
                    "thumbnail_url": f"/api/faces/thumbnail/{d['face_id']}" if d["thumbnail_path"] else None
                })

            people_groups = []
            for p_id in distinct_person_ids:
                try:
                    p_details = self.get_person_details(p_id, source_id=source_id, folder_filter=folder_filter)
                    p_media = p_details.get("media", [])
                    photo_cnt = sum(1 for m in p_media if m.get("media_type") != "video")
                    video_cnt = sum(1 for m in p_media if m.get("media_type") == "video")
                    people_groups.append({
                        "person_id": p_id,
                        "person_name": p_details["name"],
                        "avatar_url": p_details.get("avatar_url"),
                        "is_named": p_details["is_named"],
                        "total_appearances": p_details["total_faces"],
                        "total_appearances_all": p_details.get("total_faces_all", p_details["total_faces"]),
                        "photo_count": photo_cnt,
                        "video_count": video_cnt,
                        "is_scoped": p_details.get("is_scoped", False),
                        "media": p_media
                    })
                except Exception as e:
                    logger.debug(f"Error getting details for person {p_id}: {e}")

            people_groups.sort(key=lambda p: (not p["is_named"], -p["total_appearances"]))

            results.append({
                "file_id": fid,
                "filename": mf["filename"],
                "rel_path": mf["rel_path"],
                "abs_path": mf["abs_path"],
                "media_type": mf["media_type"],
                "size_bytes": mf["size_bytes"],
                "mtime": mf["mtime"],
                "source_label": mf["source_label"] or "Drive",
                "faces_in_file": faces_in_file,
                "faces_count": len(faces_in_file),
                "people_count": len(people_groups),
                "people": people_groups
            })

        return {
            "query": cleaned_query,
            "matched_files_count": len(results),
            "files": results
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
            self.scan_state["is_targeted"] = False
            self.scan_state["target_person_id"] = None
            self.scan_state["target_person_name"] = None
            self.scan_state["matches_found"] = 0
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

    def start_target_scan(
        self,
        person_id: int,
        source_id: Optional[int] = None,
        folder_filter: Optional[str] = None,
        media_type_filter: str = "all",
        step_sec: float = 1.5,
        force_rescan: bool = False
    ) -> Dict[str, Any]:
        """Launch targeted background hunt across specified scope or all folders for a specific person's face."""
        with self._scan_lock:
            if self.scan_state["is_running"]:
                return {"status": "already_running", "message": "A scan is already in progress. Please pause or cancel it first."}

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM people WHERE id = ?", (person_id,))
            p = cursor.fetchone()
            if not p:
                raise ValueError(f"Person with ID {person_id} not found")
            person_name = p["name"]

            cursor.execute("SELECT embedding FROM face_detections WHERE person_id = ? AND embedding IS NOT NULL", (person_id,))
            rows = cursor.fetchall()
            if not rows:
                raise ValueError(f"Person '{person_name}' has no face detections or embeddings to search for")

            self._cancel_scan_event.clear()
            self.scan_state["is_running"] = True
            self.scan_state["is_targeted"] = True
            self.scan_state["target_person_id"] = person_id
            self.scan_state["target_person_name"] = person_name
            self.scan_state["matches_found"] = len(rows)
            self.scan_state["scanned_files"] = 0
            self.scan_state["total_files"] = 0
            self.scan_state["faces_found"] = len(rows)

            loc_label = "all folders"
            if source_id and source_id > 0:
                cursor.execute("SELECT label FROM sources WHERE id = ?", (source_id,))
                s_row = cursor.fetchone()
                if s_row:
                    loc_label = s_row["label"]
            if folder_filter:
                loc_label += f" ({folder_filter})"

            self.scan_state["current_file"] = f"Hunting for {person_name} in {loc_label}..."
            self.scan_state["progress_pct"] = 0.0
            self.scan_state["error"] = None
            self.scan_state["start_time"] = time.time()

            t = threading.Thread(
                target=self._target_scan_worker,
                args=(person_id, person_name, source_id, folder_filter, media_type_filter, step_sec, force_rescan),
                daemon=True
            )
            t.start()

            return {
                "status": "started",
                "message": f"Hunting for '{person_name}' in {loc_label} in background",
                "target_person_id": person_id,
                "target_person_name": person_name,
                "scope": loc_label
            }

    def detect_faces_preview(self, image_bytes: bytes) -> List[Dict[str, Any]]:
        """
        Detect faces in image bytes and return crops as base64 data URLs
        for live UI preview and face selection before searching.
        """
        ensure_models()
        nparr = np.frombuffer(image_bytes, np.uint8)
        bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Could not decode image file")

        h, w = bgr.shape[:2]
        detector = _get_detector(input_size=(w, h))

        _, faces = detector.detect(bgr)
        if faces is None or len(faces) == 0:
            max_dim = 1280
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                sw, sh = int(w * scale), int(h * scale)
                scaled = cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA)
                detector_scaled = _get_detector(input_size=(sw, sh))
                _, faces = detector_scaled.detect(scaled)
                if faces is not None:
                    faces[:, 0:4] /= scale
                    faces[:, 4:14] /= scale

        if faces is None or len(faces) == 0:
            return []

        valid_faces = [f for f in faces if float(f[14]) >= 0.55]
        if not valid_faces and len(faces) > 0:
            valid_faces = [faces[0]]

        valid_faces.sort(key=lambda f: float(f[2]) * float(f[3]), reverse=True)

        results = []
        for idx, face in enumerate(valid_faces):
            margin_x = int(face[2] * 0.35)
            margin_y = int(face[3] * 0.35)
            x1 = max(0, int(face[0]) - margin_x)
            y1 = max(0, int(face[1]) - margin_y)
            x2 = min(w, int(face[0] + face[2]) + margin_x)
            y2 = min(h, int(face[1] + face[3]) + margin_y)
            crop = bgr[y1:y2, x1:x2].copy()

            ch, cw = crop.shape[:2]
            if max(cw, ch) > 200:
                sc = 200.0 / max(cw, ch)
                crop = cv2.resize(crop, (int(cw * sc), int(ch * sc)), interpolation=cv2.INTER_AREA)

            _, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            b64_str = base64.b64encode(buf.tobytes()).decode("utf-8")

            results.append({
                "face_index": idx,
                "box": [int(face[0]), int(face[1]), int(face[2]), int(face[3])],
                "confidence": round(float(face[14]), 3),
                "data_url": f"data:image/jpeg;base64,{b64_str}"
            })

        return results

    def create_person_from_image(
        self,
        image_bytes: bytes,
        filename: str = "upload.jpg",
        person_name: Optional[str] = None,
        face_index: int = 0
    ) -> Dict[str, Any]:
        """
        Extract face from image bytes, register as a new Person, save reference
        file and face crop avatar, and return person record info.
        """
        ensure_models()

        nparr = np.frombuffer(image_bytes, np.uint8)
        bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Could not decode image file")

        h, w = bgr.shape[:2]
        detector = _get_detector(input_size=(w, h))
        recognizer = _get_recognizer()

        _, faces = detector.detect(bgr)
        if faces is None or len(faces) == 0:
            max_dim = 1280
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                sw, sh = int(w * scale), int(h * scale)
                scaled = cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA)
                detector_scaled = _get_detector(input_size=(sw, sh))
                _, faces = detector_scaled.detect(scaled)
                if faces is not None:
                    faces[:, 0:4] /= scale
                    faces[:, 4:14] /= scale

        if faces is None or len(faces) == 0:
            raise ValueError("No faces detected in the image. Please upload a clear photo with a visible face.")

        valid_faces = [f for f in faces if float(f[14]) >= 0.55]
        if not valid_faces:
            valid_faces = [faces[0]]

        valid_faces.sort(key=lambda f: float(f[2]) * float(f[3]), reverse=True)
        target_face = valid_faces[min(face_index, len(valid_faces) - 1)]

        aligned = recognizer.alignCrop(bgr, target_face)
        feature = _extract_feature(aligned, recognizer)
        feat_bytes = feature.astype(np.float32).tobytes()

        margin_x = int(target_face[2] * 0.35)
        margin_y = int(target_face[3] * 0.35)
        x1 = max(0, int(target_face[0]) - margin_x)
        y1 = max(0, int(target_face[1]) - margin_y)
        x2 = min(w, int(target_face[0] + target_face[2]) + margin_x)
        y2 = min(h, int(target_face[1] + target_face[3]) + margin_y)
        crop = bgr[y1:y2, x1:x2].copy()

        uploads_dir = DATA_DIR / "uploads" / "faces"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        clean_fname = Path(filename).name or "reference.jpg"
        timestamp_prefix = int(time.time())
        saved_ref_path = uploads_dir / f"{timestamp_prefix}_{clean_fname}"
        cv2.imwrite(str(saved_ref_path), bgr)

        # Name resolution
        if not person_name or not person_name.strip():
            base = Path(clean_fname).stem.replace("_", " ").title()
            if base.lower() in ("image", "photo", "img", "upload", "pic", "reference", "screenshot", "download"):
                conn_cnt = get_db()
                cur_cnt = conn_cnt.cursor()
                cur_cnt.execute("SELECT COUNT(*) FROM people WHERE name LIKE 'Uploaded Person%'")
                cnt = cur_cnt.fetchone()[0] + 1
                person_name = f"Uploaded Person {cnt}"
            else:
                person_name = base
        else:
            person_name = person_name.strip()

        with db_transaction() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM sources WHERE id = -1")
            if not cursor.fetchone():
                cursor.execute("INSERT OR IGNORE INTO sources (id, path, label, drive_type) VALUES (-1, 'Internal References', 'Reference Uploads', 'LOCAL')")

            cursor.execute("""
                INSERT INTO files (source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, status)
                VALUES (-1, ?, ?, ?, ?, ?, ?, ?, 'photo', 'reference')
            """, (
                str(saved_ref_path.name),
                str(saved_ref_path.resolve()),
                saved_ref_path.name,
                saved_ref_path.suffix.lower(),
                saved_ref_path.stat().st_size,
                int(time.time()),
                int(time.time())
            ))
            ref_file_id = cursor.lastrowid

            cursor.execute("INSERT INTO people (name) VALUES (?)", (person_name,))
            new_person_id = cursor.lastrowid

            bx, by, bw, bh = int(target_face[0]), int(target_face[1]), int(target_face[2]), int(target_face[3])
            conf = float(target_face[14])
            cursor.execute("""
                INSERT INTO face_detections (
                    file_id, person_id, timestamp_sec,
                    box_x, box_y, box_w, box_h,
                    confidence, embedding, thumbnail_path
                ) VALUES (?, ?, 0.0, ?, ?, ?, ?, ?, ?, '')
            """, (ref_file_id, new_person_id, bx, by, bw, bh, conf, feat_bytes))
            new_face_id = cursor.lastrowid

            crop_filename = f"{new_face_id}.jpg"
            crop_path = FACES_DIR / crop_filename
            ch, cw = crop.shape[:2]
            if max(cw, ch) > 240:
                sc = 240.0 / max(cw, ch)
                crop_resized = cv2.resize(crop, (int(cw * sc), int(ch * sc)), interpolation=cv2.INTER_AREA)
            else:
                crop_resized = crop
            cv2.imwrite(str(crop_path), crop_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

            cursor.execute("UPDATE face_detections SET thumbnail_path = ? WHERE id = ?", (crop_filename, new_face_id))
            cursor.execute("UPDATE people SET avatar_face_id = ? WHERE id = ?", (new_face_id, new_person_id))

            if not person_name.startswith("Unnamed Person"):
                cursor.execute("INSERT OR IGNORE INTO file_tags (file_id, tag, category) VALUES (?, ?, 'speaker')", (ref_file_id, person_name))

        return {
            "person_id": new_person_id,
            "person_name": person_name,
            "face_id": new_face_id,
            "avatar_url": f"/api/faces/thumbnail/{new_face_id}",
            "total_faces_detected": len(valid_faces)
        }

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
                f_cond, f_params = self._build_folder_sql(folder_filter, "f")
                conditions.append(f_cond)
                params.extend(f_params)

            # Force rescan vs skipping already-scanned files
            if not force_rescan:
                conditions.append("f.id NOT IN (SELECT DISTINCT file_id FROM face_detections)")

            where_sql = " AND ".join(conditions)
            cursor.execute(f"SELECT f.id, f.abs_path, f.filename, f.media_type FROM files f WHERE {where_sql}", params)
            files_to_scan = cursor.fetchall()

            total = len(files_to_scan)
            self.scan_state["total_files"] = total

            logger.info(f"Starting Face Scan on {total} media files...")

            known_people = self._get_known_people_centroids()

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
                        faces_found = self.process_file_faces(
                            fid, fpath, mtype, step_sec=step_sec, known_people_cache=known_people
                        )
                        self.scan_state["faces_found"] += faces_found
                    except Exception as e:
                        logger.warning(f"Error scanning faces in {fname}: {e}")

                self.scan_state["scanned_files"] = idx + 1

            # Auto-cluster any remaining unassigned faces at the end of the scan
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

    def _target_scan_worker(
        self,
        person_id: int,
        person_name: str,
        source_id: Optional[int] = None,
        folder_filter: Optional[str] = None,
        media_type_filter: str = "all",
        step_sec: float = 1.5,
        force_rescan: bool = False
    ):
        """Worker thread executing targeted face search for a specific person across media scope."""
        try:
            ensure_models()

            conn = get_db()
            cursor = conn.cursor()

            # 1. Compute target person's centroid vector
            cursor.execute("SELECT embedding FROM face_detections WHERE person_id = ? AND embedding IS NOT NULL", (person_id,))
            rows = cursor.fetchall()
            if not rows:
                self.scan_state["error"] = "Target person has no face embeddings"
                return

            embs = [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
            target_vec = np.mean(embs, axis=0)
            norm = np.linalg.norm(target_vec)
            if norm > 0:
                target_vec = target_vec / norm

            # 2. Instant fast sweep of already extracted unassigned faces within the requested scope
            unassigned_conditions = ["fd.person_id IS NULL", "fd.embedding IS NOT NULL", "f.status = 'active'"]
            unassigned_params: List[Any] = []
            if source_id is not None and source_id > 0:
                unassigned_conditions.append("f.source_id = ?")
                unassigned_params.append(source_id)
            if folder_filter:
                f_cond, f_params = self._build_folder_sql(folder_filter, "f")
                unassigned_conditions.append(f_cond)
                unassigned_params.extend(f_params)

            unassigned_where = " AND ".join(unassigned_conditions)
            cursor.execute(f"""
                SELECT fd.id, fd.file_id, fd.embedding 
                FROM face_detections fd
                JOIN files f ON fd.file_id = f.id
                WHERE {unassigned_where}
            """, unassigned_params)
            unassigned_rows = cursor.fetchall()
            for u in unassigned_rows:
                u_vec = np.frombuffer(u["embedding"], dtype=np.float32)
                u_norm = np.linalg.norm(u_vec)
                if u_norm > 0:
                    sim = float(np.dot(target_vec, u_vec / u_norm))
                    if sim >= 0.40:
                        with db_transaction() as wconn:
                            wconn.cursor().execute("UPDATE face_detections SET person_id = ? WHERE id = ?", (person_id, u["id"]))
                            if not person_name.startswith("Unnamed Person"):
                                wconn.cursor().execute(
                                    "INSERT OR IGNORE INTO file_tags (file_id, tag, category) VALUES (?, ?, 'speaker')",
                                    (u["file_id"], person_name)
                                )

            # Count matches in scope
            match_conds = ["fd.person_id = ?", "f.status = 'active'"]
            match_params: List[Any] = [person_id]
            if source_id is not None and source_id > 0:
                match_conds.append("f.source_id = ?")
                match_params.append(source_id)
            if folder_filter:
                f_cond, f_params = self._build_folder_sql(folder_filter, "f")
                match_conds.append(f_cond)
                match_params.extend(f_params)

            cursor.execute(f"""
                SELECT COUNT(fd.id) 
                FROM face_detections fd
                JOIN files f ON fd.file_id = f.id
                WHERE {" AND ".join(match_conds)}
            """, match_params)
            self.scan_state["matches_found"] = cursor.fetchone()[0]

            # 3. Find files to scan according to selected scope (drive, folder, media_type)
            conditions = ["f.status = 'active'"]
            params: List[Any] = []

            if media_type_filter == "photo":
                conditions.append("f.media_type IN ('photo', 'raw')")
            elif media_type_filter == "video":
                conditions.append("f.media_type = 'video'")
            else:
                conditions.append("f.media_type IN ('photo', 'raw', 'video')")

            if source_id is not None and source_id > 0:
                conditions.append("f.source_id = ?")
                params.append(source_id)

            if folder_filter:
                f_cond, f_params = self._build_folder_sql(folder_filter, "f")
                conditions.append(f_cond)
                params.extend(f_params)

            if force_rescan:
                conditions.append("f.id NOT IN (SELECT DISTINCT file_id FROM face_detections WHERE person_id = ?)")
                params.append(person_id)
            else:
                conditions.append("f.id NOT IN (SELECT DISTINCT file_id FROM face_detections)")

            where_sql = " AND ".join(conditions)
            cursor.execute(f"""
                SELECT f.id, f.abs_path, f.filename, f.media_type
                FROM files f
                WHERE {where_sql}
                ORDER BY f.mtime DESC
            """, params)

            files_to_scan = cursor.fetchall()
            total = len(files_to_scan)
            self.scan_state["total_files"] = total

            logger.info(f"Target Scan for '{person_name}' (ID {person_id}) starting on {total} files...")

            known_people = self._get_known_people_centroids()

            for idx, f in enumerate(files_to_scan):
                if self._cancel_scan_event.is_set():
                    logger.info(f"Target scan for {person_name} canceled by user.")
                    break

                fid = f["id"]
                fpath = Path(f["abs_path"])
                mtype = f["media_type"]
                fname = f["filename"]

                self.scan_state["current_file"] = fname
                self.scan_state["progress_pct"] = round((idx / total) * 100, 1) if total > 0 else 100.0

                if fpath.exists():
                    try:
                        faces_found = self.process_file_faces(
                            fid, fpath, mtype, step_sec=step_sec, known_people_cache=known_people
                        )
                        self.scan_state["faces_found"] += faces_found

                        # Refresh live count of matches found for this target person
                        chk_conn = get_db()
                        chk_cur = chk_conn.cursor()
                        chk_cur.execute("SELECT COUNT(*) FROM face_detections WHERE person_id = ?", (person_id,))
                        self.scan_state["matches_found"] = chk_cur.fetchone()[0]
                    except Exception as e:
                        logger.warning(f"Error scanning faces in {fname}: {e}")

                self.scan_state["scanned_files"] = idx + 1
                time.sleep(0.005)  # Yield CPU to keep system cool and responsive

            self.scan_state["progress_pct"] = 100.0
            self.scan_state["current_file"] = f"Finished searching for {person_name}"

        except Exception as e:
            logger.error(f"Target Scan failed: {e}", exc_info=True)
            self.scan_state["error"] = str(e)
        finally:
            self.scan_state["is_running"] = False


# Global singleton engine instance
face_engine = FaceEngine()
