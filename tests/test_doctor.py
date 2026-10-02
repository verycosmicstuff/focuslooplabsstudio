import os
import time
import shutil
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from src.sync.doctor import BackupDoctor, backup_doctor
from src.api.server import app

client = TestClient(app)

class TestBackupDoctor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_doctor_")
        self.src_dir = Path(self.temp_dir) / "source"
        self.tgt_dir = Path(self.temp_dir) / "target"
        self.src_dir.mkdir()
        self.tgt_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_audit_detection(self):
        doctor = BackupDoctor()

        # 1. Healthy file
        (self.src_dir / "healthy.txt").write_bytes(b"A" * 1024)
        (self.tgt_dir / "healthy.txt").write_bytes(b"A" * 1024)

        # 2. Corrupted 0-byte stub on target
        (self.src_dir / "corrupted.mp4").write_bytes(b"VIDEO_DATA" * 500)
        (self.tgt_dir / "corrupted.mp4").write_bytes(b"") # 0 bytes

        # 3. Missing file
        (self.src_dir / "missing.wav").write_bytes(b"AUDIO_DATA" * 300)

        # 4. Size mismatch
        (self.src_dir / "mismatch.jpg").write_bytes(b"IMG" * 100)
        (self.tgt_dir / "mismatch.jpg").write_bytes(b"IMG" * 50)

        # 5. Orphan file on target
        (self.tgt_dir / "orphan.tmp").write_bytes(b"EXTRA")

        # 6. Nested subfolder corrupted file
        (self.src_dir / "subfolder").mkdir()
        (self.tgt_dir / "subfolder").mkdir()
        (self.src_dir / "subfolder" / "clip.mov").write_bytes(b"SUBCLIP" * 200)
        (self.tgt_dir / "subfolder" / "clip.mov").write_bytes(b"") # 0 bytes

        res = doctor.audit_folders(str(self.src_dir), str(self.tgt_dir))
        summary = res["summary"]

        self.assertEqual(summary["healthy_count"], 1)
        self.assertEqual(summary["corrupted_count"], 2)
        self.assertEqual(summary["missing_count"], 1)
        self.assertEqual(summary["mismatch_count"], 1)
        self.assertEqual(summary["orphan_count"], 1)
        self.assertFalse(summary["is_healthy"])

        corrupted_names = {f["filename"] for f in res["corrupted_files"]}
        self.assertIn("corrupted.mp4", corrupted_names)
        self.assertIn("clip.mov", corrupted_names)

        missing_names = {f["filename"] for f in res["missing_files"]}
        self.assertIn("missing.wav", missing_names)

    def test_repair_corrupted_only(self):
        doctor = BackupDoctor()

        # Setup 0-byte corrupted file and missing file
        (self.src_dir / "broken.bin").write_bytes(b"REPAIRED_CONTENT_12345")
        (self.tgt_dir / "broken.bin").write_bytes(b"") # 0 byte stub
        (self.src_dir / "missing.bin").write_bytes(b"MISSING_DATA")

        res = doctor.start_repair(
            str(self.src_dir),
            str(self.tgt_dir),
            mode="corrupted_only"
        )
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["total_files"], 1)

        # Wait for worker thread to finish
        for _ in range(50):
            status = doctor.get_status()
            if not status["is_running"]:
                break
            time.sleep(0.05)

        status = doctor.get_status()
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["completed_files"], 1)
        self.assertEqual((self.tgt_dir / "broken.bin").stat().st_size, len(b"REPAIRED_CONTENT_12345"))
        self.assertEqual((self.tgt_dir / "broken.bin").read_bytes(), b"REPAIRED_CONTENT_12345")
        # Missing file should NOT be touched in corrupted_only mode
        self.assertFalse((self.tgt_dir / "missing.bin").exists())

    def test_repair_all_defects_and_mtime_preservation(self):
        doctor = BackupDoctor()

        (self.src_dir / "broken.bin").write_bytes(b"DATA_BROKEN" * 100)
        (self.tgt_dir / "broken.bin").write_bytes(b"")
        (self.src_dir / "missing.bin").write_bytes(b"DATA_MISSING" * 50)

        # Set specific mtime on source
        custom_mtime = time.time() - 3600
        os.utime(self.src_dir / "broken.bin", (custom_mtime, custom_mtime))

        res = doctor.start_repair(
            str(self.src_dir),
            str(self.tgt_dir),
            mode="all_defects"
        )
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["total_files"], 2)

        for _ in range(50):
            status = doctor.get_status()
            if not status["is_running"]:
                break
            time.sleep(0.05)

        self.assertEqual((self.tgt_dir / "broken.bin").read_bytes(), (self.src_dir / "broken.bin").read_bytes())
        self.assertEqual((self.tgt_dir / "missing.bin").read_bytes(), (self.src_dir / "missing.bin").read_bytes())
        self.assertAlmostEqual((self.tgt_dir / "broken.bin").stat().st_mtime, custom_mtime, delta=2.0)

    def test_api_endpoints(self):
        (self.src_dir / "item1.dat").write_bytes(b"CONTENT" * 50)
        (self.tgt_dir / "item1.dat").write_bytes(b"") # 0 bytes

        # 1. Audit endpoint
        resp = client.post("/api/sync/doctor/audit", json={
            "source_path": str(self.src_dir),
            "target_path": str(self.tgt_dir)
        })
        self.assertEqual(resp.status_code, 200)
        audit_data = resp.json()
        self.assertEqual(audit_data["summary"]["corrupted_count"], 1)

        # 2. Status endpoint
        resp = client.get("/api/sync/doctor/status")
        self.assertEqual(resp.status_code, 200)

        # 3. Repair endpoint
        resp = client.post("/api/sync/doctor/repair", json={
            "source_path": str(self.src_dir),
            "target_path": str(self.tgt_dir),
            "mode": "corrupted_only"
        })
        self.assertEqual(resp.status_code, 200)

        for _ in range(50):
            resp = client.get("/api/sync/doctor/status")
            if not resp.json()["is_running"]:
                break
            time.sleep(0.05)

        self.assertEqual((self.tgt_dir / "item1.dat").read_bytes(), b"CONTENT" * 50)
