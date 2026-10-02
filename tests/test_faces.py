import sys
import shutil
import unittest
import numpy as np
import cv2
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.config
import src.core.db
from src.core.db import init_db, get_db, close_db
from src.analyzer.face_engine import face_engine, ensure_models
from src.api.server import app

class TestFaceEngineAndCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).resolve().parent / "mock_face_storage"
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        cls.orig_db_path = src.config.DB_PATH
        cls.orig_faces_dir = src.config.FACES_DIR

        cls.test_db_path = cls.test_dir / "test_faces.db"
        cls.test_faces_dir = cls.test_dir / "faces"
        cls.test_faces_dir.mkdir(parents=True, exist_ok=True)

        src.config.DB_PATH = cls.test_db_path
        src.config.FACES_DIR = cls.test_faces_dir
        src.core.db._thread_local.conn = None
        init_db()

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        src.config.DB_PATH = cls.orig_db_path
        src.config.FACES_DIR = cls.orig_faces_dir
        close_db()
        import gc
        gc.collect()
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM face_detections")
        cursor.execute("DELETE FROM people")
        cursor.execute("DELETE FROM file_tags")
        cursor.execute("DELETE FROM files")
        cursor.execute("DELETE FROM sources")
        conn.commit()

        # Insert mock source and files
        src_path = str(self.test_dir / "Drive_SSD")
        cursor.execute("INSERT INTO sources (id, path, label, drive_type) VALUES (1, ?, 'Main Drive', 'SSD')", (src_path,))

        cursor.execute("""
            INSERT INTO files (id, source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type)
            VALUES (1, 1, 'Photos/portrait1.jpg', ?, 'portrait1.jpg', '.jpg', 1048576, 1700000000, 1700000000, 'photo')
        """, (str(self.test_dir / "portrait1.jpg"),))

        cursor.execute("""
            INSERT INTO files (id, source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type)
            VALUES (2, 1, 'Photos/portrait2.jpg', ?, 'portrait2.jpg', '.jpg', 1048576, 1700000100, 1700000100, 'photo')
        """, (str(self.test_dir / "portrait2.jpg"),))

        cursor.execute("""
            INSERT INTO files (id, source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type)
            VALUES (3, 1, 'Videos/interview.mp4', ?, 'interview.mp4', '.mp4', 50485760, 1700000200, 1700000200, 'video')
        """, (str(self.test_dir / "interview.mp4"),))
        conn.commit()

    def _generate_synthetic_embedding(self, seed: int = 42) -> bytes:
        rng = np.random.RandomState(seed)
        vec = rng.randn(128).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec.tobytes()

    def test_01_ensure_models(self):
        """Ensure OpenCV YuNet & SFace models can be verified or loaded."""
        loaded = ensure_models()
        self.assertTrue(loaded)

    def test_02_face_insertion_and_listing(self):
        """Insert face detections and test listing people."""
        conn = get_db()
        cursor = conn.cursor()

        # Person A embeddings (seed 100 and slight variation)
        emb_a1 = self._generate_synthetic_embedding(100)
        emb_a2 = self._generate_synthetic_embedding(101)
        # Person B embedding (seed 500)
        emb_b1 = self._generate_synthetic_embedding(500)

        # Create thumbnail files
        (src.config.FACES_DIR / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0mockjpg")
        (src.config.FACES_DIR / "2.jpg").write_bytes(b"\xff\xd8\xff\xe0mockjpg")
        (src.config.FACES_DIR / "3.jpg").write_bytes(b"\xff\xd8\xff\xe0mockjpg")

        cursor.execute("INSERT INTO people (id, name, avatar_face_id) VALUES (1, 'Alice Smith', 1)")
        cursor.execute("INSERT INTO people (id, name, avatar_face_id) VALUES (2, 'Bob Jones', 3)")

        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding, thumbnail_path)
            VALUES (1, 1, 1, 0.0, 50, 50, 100, 100, 0.95, ?, '1.jpg')
        """, (emb_a1,))
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding, thumbnail_path)
            VALUES (2, 3, 1, 14.5, 60, 60, 95, 95, 0.92, ?, '2.jpg')
        """, (emb_a2,))
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding, thumbnail_path)
            VALUES (3, 2, 2, 0.0, 40, 40, 80, 80, 0.98, ?, '3.jpg')
        """, (emb_b1,))
        conn.commit()

        # Call API
        resp = self.client.get("/api/faces/people")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)

        alice = next(p for p in data if p["id"] == 1)
        self.assertEqual(alice["name"], "Alice Smith")
        self.assertEqual(alice["face_count"], 2)
        self.assertEqual(alice["photo_count"], 1)
        self.assertEqual(alice["video_count"], 1)

    def test_03_rename_person_and_tags_sync(self):
        """Naming/renaming a person should update their record and auto-tag files with 'speaker'."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO people (id, name) VALUES (10, 'Unnamed Person 1')")
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (10, 1, 10, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(1),))
        conn.commit()

        # Rename via API
        resp = self.client.post("/api/faces/people/10/rename", json={
            "name": "Sarah Connor",
            "sync_to_tags": True
        })
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()
        self.assertEqual(res_data["new_name"], "Sarah Connor")
        self.assertEqual(res_data["files_tagged"], 1)

        # Verify in file_tags
        cursor.execute("SELECT tag, category FROM file_tags WHERE file_id = 1")
        tags = cursor.fetchall()
        self.assertTrue(any(t["tag"] == "Sarah Connor" and t["category"] == "speaker" for t in tags))

    def test_04_merge_people(self):
        """Combining/merging two people into one (Google Photos style)."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO people (id, name, avatar_face_id) VALUES (20, 'Person A', 21)")
        cursor.execute("INSERT INTO people (id, name, avatar_face_id) VALUES (21, 'Person B (Duplicate)', 22)")

        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (21, 1, 20, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(20),))
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (22, 2, 21, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(21),))
        conn.commit()

        # Merge Person B into Person A
        resp = self.client.post("/api/faces/people/merge", json={
            "target_person_id": 20,
            "source_person_ids": [21]
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["faces_merged"], 1)

        # Verify Person B is gone and face 22 now belongs to Person A
        cursor.execute("SELECT COUNT(*) FROM people WHERE id = 21")
        self.assertEqual(cursor.fetchone()[0], 0)

        cursor.execute("SELECT person_id FROM face_detections WHERE id = 22")
        self.assertEqual(cursor.fetchone()[0], 20)

    def test_05_unlink_and_assign_face(self):
        """Unlinking a face from a person and reassigning it to another."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO people (id, name) VALUES (30, 'Person Alpha')")
        cursor.execute("INSERT INTO people (id, name) VALUES (31, 'Person Beta')")

        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (35, 1, 30, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(30),))
        conn.commit()

        # Unlink face 35
        resp = self.client.post("/api/faces/faces/35/unlink")
        self.assertEqual(resp.status_code, 200)
        cursor.execute("SELECT person_id FROM face_detections WHERE id = 35")
        self.assertIsNone(cursor.fetchone()[0])

        # Assign face 35 to Person Beta
        resp = self.client.post("/api/faces/faces/35/assign", json={
            "target_person_id": 31
        })
        self.assertEqual(resp.status_code, 200)
        cursor.execute("SELECT person_id FROM face_detections WHERE id = 35")
        self.assertEqual(cursor.fetchone()[0], 31)

    def test_06_person_detail_with_video_timestamps(self):
        """Person detail endpoint returns photos and video appearances with timestamps."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO people (id, name) VALUES (40, 'Host John')")
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (41, 3, 40, 23.5, 10, 10, 50, 50, 0.92, ?)
        """, (self._generate_synthetic_embedding(40),))
        conn.commit()

        resp = self.client.get("/api/faces/people/40")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "Host John")
        self.assertEqual(len(data["media"]), 1)
        media_item = data["media"][0]
        self.assertEqual(media_item["media_type"], "video")
        self.assertEqual(len(media_item["faces"]), 1)
        self.assertEqual(media_item["faces"][0]["timestamp_sec"], 23.5)

    def test_07_clustering_unassigned_faces(self):
        """Auto-clustering groups similar unassigned faces into new clusters."""
        conn = get_db()
        cursor = conn.cursor()

        # 3 faces with nearly identical vectors (Cluster 1)
        base_v1 = (np.ones(128, dtype=np.float32) / np.sqrt(128)).astype(np.float32)
        emb_c1_a = base_v1.tobytes()
        emb_c1_b = (base_v1 + 0.001).astype(np.float32)
        emb_c1_b /= np.linalg.norm(emb_c1_b)
        emb_c1_b = emb_c1_b.tobytes()

        # 1 face with completely different orthogonal vector (Cluster 2)
        v2 = np.zeros(128, dtype=np.float32)
        v2[0] = 1.0
        emb_c2 = v2.tobytes()

        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (51, 1, NULL, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (emb_c1_a,))
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (52, 2, NULL, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (emb_c1_b,))
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (53, 3, NULL, 5.0, 10, 10, 50, 50, 0.9, ?)
        """, (emb_c2,))
        conn.commit()

        resp = self.client.post("/api/faces/recluster")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["clusters_formed"], 1)

        # Faces 51 and 52 should be in the same cluster!
        cursor.execute("SELECT person_id FROM face_detections WHERE id = 51")
        p51 = cursor.fetchone()[0]
        cursor.execute("SELECT person_id FROM face_detections WHERE id = 52")
        p52 = cursor.fetchone()[0]
        self.assertIsNotNone(p51)
        self.assertEqual(p51, p52)

    def test_08_scan_status_and_cancel(self):
        """Scan status and cancellation endpoints work as expected."""
        resp = self.client.get("/api/faces/scan/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("is_running", data)
        self.assertIn("faces_found", data)

        cancel_resp = self.client.post("/api/faces/scan/cancel")
        self.assertEqual(cancel_resp.status_code, 200)

    def test_09_media_type_filter_and_sorting(self):
        """Test filtering by media_type (video vs photo) and sorting by video_count / photo_count."""
        conn = get_db()
        cursor = conn.cursor()

        # Person 1: Appears in 2 videos (file 3)
        cursor.execute("INSERT INTO people (id, name) VALUES (101, 'Video Star')")
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (101, 3, 101, 1.0, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(101),))
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (102, 3, 101, 3.5, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(102),))

        # Person 2: Appears in 2 photos (file 1, file 2)
        cursor.execute("INSERT INTO people (id, name) VALUES (102, 'Photo Model')")
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (103, 1, 102, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(103),))
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (104, 2, 102, 0.0, 10, 10, 50, 50, 0.9, ?)
        """, (self._generate_synthetic_embedding(104),))
        conn.commit()

        # 1. Filter media_type = video
        resp_video = self.client.get("/api/faces/people?media_type=video")
        self.assertEqual(resp_video.status_code, 200)
        video_people = resp_video.json()
        self.assertTrue(any(p["id"] == 101 for p in video_people))
        self.assertFalse(any(p["id"] == 102 for p in video_people))

        # 2. Filter media_type = photo
        resp_photo = self.client.get("/api/faces/people?media_type=photo")
        self.assertEqual(resp_photo.status_code, 200)
        photo_people = resp_photo.json()
        self.assertTrue(any(p["id"] == 102 for p in photo_people))
        self.assertFalse(any(p["id"] == 101 for p in photo_people))

        # 3. Sort by video_count
        resp_sort_video = self.client.get("/api/faces/people?sort=video_count")
        self.assertEqual(resp_sort_video.status_code, 200)
        sorted_v = resp_sort_video.json()
        self.assertEqual(sorted_v[0]["id"], 101) # Video Star at top

        # 4. Sort by photo_count
        resp_sort_photo = self.client.get("/api/faces/people?sort=photo_count")
        self.assertEqual(resp_sort_photo.status_code, 200)
        sorted_p = resp_sort_photo.json()
        self.assertEqual(sorted_p[0]["id"], 102) # Photo Model at top

    def test_10_targeted_face_scan_find_everywhere(self):
        """Test targeted face scan across unassigned faces and media."""
        conn = get_db()
        cursor = conn.cursor()

        # Create target person with known vector
        target_vec = (np.ones(128, dtype=np.float32) / np.sqrt(128)).astype(np.float32)
        emb_target = target_vec.tobytes()

        cursor.execute("INSERT INTO people (id, name) VALUES (201, 'Target Agent')")
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (201, 1, 201, 0.0, 10, 10, 50, 50, 0.95, ?)
        """, (emb_target,))

        # Create an unassigned face with matching vector (cosine sim = 1.0)
        cursor.execute("""
            INSERT INTO face_detections (id, file_id, person_id, timestamp_sec, box_x, box_y, box_w, box_h, confidence, embedding)
            VALUES (202, 2, NULL, 0.0, 15, 15, 45, 45, 0.92, ?)
        """, (emb_target,))
        conn.commit()

        # Launch targeted hunt
        resp = self.client.post("/api/faces/people/201/find-everywhere", json={"step_sec": 1.5})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "started")
        self.assertEqual(data["target_person_id"], 201)

        # Wait briefly for worker sweep
        import time
        for _ in range(20):
            status = face_engine.scan_state
            if not status["is_running"]:
                break
            time.sleep(0.05)

        # The unassigned face (202) should now be linked to Person 201!
        cursor.execute("SELECT person_id FROM face_detections WHERE id = 202")
        self.assertEqual(cursor.fetchone()[0], 201)

        # File 2 should be tagged with 'Target Agent' as speaker
        cursor.execute("SELECT tag FROM file_tags WHERE file_id = 2 AND category = 'speaker'")
        tag_row = cursor.fetchone()
        self.assertIsNotNone(tag_row)
        self.assertEqual(tag_row[0], "Target Agent")


if __name__ == "__main__":
    unittest.main()

