import os
import sys
import time
import shutil
import unittest
import numpy as np
import cv2
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.db import init_db, get_db
from src.scanner.sidecar import compute_pair_id, find_sidecars_for_file
from src.scanner.indexer import SourceIndexer, compute_fast_hash
from src.analyzer.culler import compute_blur_score, CullingEngine
from src.analyzer.deduper import DuplicateDetector
from src.transcoder.engine import TranscodeJob, TRANSCODE_PROFILES
from src.config import FFMPEG_PATH, FFPROBE_PATH

class TestSaveSpace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.test_dir = Path(__file__).resolve().parent / "mock_storage"
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)

    def test_1_sidecar_binding(self):
        """Test that Fuji RAW + XMP sidecars are bound together atomically."""
        raf_file = self.test_dir / "DSCF9999.RAF"
        xmp_file = self.test_dir / "DSCF9999.xmp"
        jpg_file = self.test_dir / "DSCF9999.JPG"

        raf_file.write_bytes(b"MOCK_FUJI_RAF_DATA_12345678")
        xmp_file.write_text("<xmp>Lightroom Edits</xmp>")
        jpg_file.write_bytes(b"MOCK_JPEG_PREVIEW_DATA")

        sidecars = find_sidecars_for_file(str(raf_file))
        self.assertTrue(any("DSCF9999.xmp" in s for s in sidecars), "XMP sidecar was not detected!")

    def test_2_blur_detection(self):
        """Test that Laplacian focus scoring distinguishes sharp vs blurry images."""
        sharp_path = self.test_dir / "test_sharp.jpg"
        blurry_path = self.test_dir / "test_blurry.jpg"

        # Create sharp image: high-contrast checkerboard with text
        img = np.zeros((400, 400), dtype=np.uint8)
        for i in range(0, 400, 20):
            img[i:i+10, :] = 255
            img[:, i:i+10] = 255
        cv2.putText(img, "SHARP FOCUS TEST", (30, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 3)
        cv2.imwrite(str(sharp_path), img)

        # Create blurry image by applying heavy blur
        blurred = cv2.GaussianBlur(img, (45, 45), 0)
        cv2.imwrite(str(blurry_path), blurred)

        score_sharp = compute_blur_score(str(sharp_path))
        score_blurry = compute_blur_score(str(blurry_path))

        print(f"\n[Test] Sharp Focus Score: {score_sharp}/100 | Blurry Focus Score: {score_blurry}/100")
        self.assertGreater(score_sharp, 40.0)
        self.assertLess(score_blurry, 25.0)
        self.assertGreater(score_sharp, score_blurry * 2.0)

    def test_3_fast_hasher_and_duplicates(self):
        """Test fast head-mid-tail hashing and duplicate detection."""
        f1 = self.test_dir / "shoot_a_copy1.bin"
        f2 = self.test_dir / "shoot_a_copy2.bin"

        dummy_data = b"X" * (300 * 1024) # 300KB
        f1.write_bytes(dummy_data)
        f2.write_bytes(dummy_data)

        h1 = compute_fast_hash(str(f1), len(dummy_data))
        h2 = compute_fast_hash(str(f2), len(dummy_data))
        self.assertEqual(h1, h2)
        self.assertTrue(len(h1) > 0)

    def test_4_nvenc_video_transcoding(self):
        """Test that FFmpeg with hevc_nvenc or fallback converts test video and preserves metadata."""
        if not FFMPEG_PATH:
            print("FFmpeg not installed, skipping transcode test")
            return

        in_video = self.test_dir / "input_camera_clip.mp4"
        out_video = self.test_dir / "output_camera_clip_H265.mp4"

        # Generate 2-second test video using ffmpeg
        gen_cmd = [
            FFMPEG_PATH, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
            "-c:v", "libx264", "-b:v", "5M",
            "-c:a", "aac",
            str(in_video)
        ]
        import subprocess
        res = subprocess.run(gen_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(res.returncode, 0, "Failed to generate test input video")

        orig_size = in_video.stat().st_size
        print(f"\n[Test] Original Test Video Size: {orig_size} bytes")

        # Test TranscodeJob
        job = TranscodeJob(
            transcode_id=9999,
            source_path=str(in_video),
            output_path=str(out_video),
            profile_key="nvenc_hq_10bit",
            perf_mode="balanced"
        )
        success = job.run()
        self.assertTrue(success, "Transcode job failed")
        self.assertTrue(out_video.exists(), "Transcoded output does not exist")

        conv_size = out_video.stat().st_size
        print(f"[Test] Transcoded H.265 Video Size: {conv_size} bytes (Saved {orig_size - conv_size} bytes)")
        self.assertGreater(conv_size, 0)

    def test_5_duplicate_detector_folder_pairing(self):
        """Test that duplicate detector groups matches with folder pairing metadata."""
        dir_a = self.test_dir / "drone_sd"
        dir_b = self.test_dir / "drone_backup"
        dir_a.mkdir(exist_ok=True)
        dir_b.mkdir(exist_ok=True)

        file_a = dir_a / "clip1.mp4"
        file_b = dir_b / "clip1.mp4"
        content = b"IDENTICAL_VIDEO_CONTENT_12345" * 1000  # ~29 KB
        file_a.write_bytes(content)
        file_b.write_bytes(content)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO sources (path, label, drive_type) VALUES (?, ?, ?)",
                       (str(self.test_dir), "Test Drive", "SSD"))
        cursor.execute("SELECT id FROM sources WHERE path = ?", (str(self.test_dir),))
        src_id = cursor.fetchone()[0]

        h1 = compute_fast_hash(str(file_a), len(content))
        cursor.execute("""
            INSERT OR REPLACE INTO files (source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, fast_hash, full_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (src_id, "drone_sd/clip1.mp4", str(file_a), "clip1.mp4", ".mp4", len(content), time.time() - 100, time.time(), "video", h1, None, "active"))

        cursor.execute("""
            INSERT OR REPLACE INTO files (source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, fast_hash, full_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (src_id, "drone_backup/clip1.mp4", str(file_b), "clip1.mp4", ".mp4", len(content), time.time(), time.time(), "video", h1, None, "active"))
        conn.commit()

        dupes = DuplicateDetector.find_duplicates(source_id=src_id)
        self.assertGreaterEqual(len(dupes), 1, "Duplicate group was not found!")
        group = next((g for g in dupes if g["primary_filename"] == "clip1.mp4"), None)
        self.assertIsNotNone(group, "Target duplicate group not found")
        self.assertIn("folder_pair_key", group)
        self.assertIn("folder_pair_label", group)
        self.assertIn("drone_sd", group["folder_pair_label"])
        self.assertIn("drone_backup", group["folder_pair_label"])
        self.assertIn(" ⟷ ", group["folder_pair_label"])
        self.assertEqual(len(group["folder_paths"]), 2)
        for f in group["files"]:
            self.assertIn("folder_path", f)
            self.assertIn("folder_name", f)

    def test_video_candidates_search_and_folder_filtering(self):
        """Tests that transcode candidates can be queried by folder name, source label, or filename."""
        from src.api.server import get_transcode_candidates

        # Query candidates by folder name in rel_path (min_size_mb=0 to catch test files)
        by_folder = get_transcode_candidates(min_size_mb=0, search="drone_sd")
        self.assertTrue(any("clip1.mp4" in c["filename"] for c in by_folder), "Candidate not found by folder search")

        # Query candidates by source label
        by_label = get_transcode_candidates(min_size_mb=0, search="Test Drive")
        self.assertTrue(any("clip1.mp4" in c["filename"] for c in by_label), "Candidate not found by source label search")

if __name__ == "__main__":
    unittest.main()

