import os
import sys
import json
import shutil
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.db import init_db, get_db, db_transaction
from src.core.models import SourceCreate
from src.scanner.volume import (
    get_or_create_volume_uuid, read_volume_uuid, verify_volume_match,
    update_source_mount_path, find_source_by_volume_uuid
)
from src.scanner.indexer import SourceIndexer
from src.analyzer.deduper import DuplicateDetector
from src.api.server import add_source, list_sources

class TestVolumeAlias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import src.config
        import src.core.db

        cls.test_base = Path(__file__).resolve().parent / "mock_volumes"
        if cls.test_base.exists():
            shutil.rmtree(cls.test_base)
        cls.test_base.mkdir(parents=True, exist_ok=True)

        cls.local_mount = cls.test_base / "usb_easystore"
        cls.nas_mount = cls.test_base / "nas_easystore"
        cls.local_mount.mkdir(parents=True, exist_ok=True)
        cls.nas_mount.mkdir(parents=True, exist_ok=True)

        # ISOLATE TEST DATABASE to avoid touching real data/savespace.db
        cls.orig_db_path = src.config.DB_PATH
        cls.test_db_path = cls.test_base / "test_alias.db"
        src.config.DB_PATH = cls.test_db_path
        src.core.db._thread_local.conn = None
        init_db()

    @classmethod
    def tearDownClass(cls):
        import src.config
        from src.core.db import close_db

        # Restore real DB path
        src.config.DB_PATH = cls.orig_db_path
        close_db()
        if cls.test_base.exists():
            shutil.rmtree(cls.test_base)

    def setUp(self):
        # Clear sources and files for clean isolated tests
        with db_transaction() as tx:
            tx.execute("DELETE FROM files")
            tx.execute("DELETE FROM sources")

        if self.local_mount.exists():
            shutil.rmtree(self.local_mount)
        if self.nas_mount.exists():
            shutil.rmtree(self.nas_mount)
        self.local_mount.mkdir(parents=True, exist_ok=True)
        self.nas_mount.mkdir(parents=True, exist_ok=True)

    def test_1_volume_fingerprint_generation_and_reading(self):
        """Verify .focusloop_id creation, reading, and signature verification."""
        vol_uuid = get_or_create_volume_uuid(self.local_mount, label="MyEasyStore")
        self.assertIsNotNone(vol_uuid)
        self.assertTrue(len(vol_uuid) > 10)

        # File exists on disk
        marker_file = self.local_mount / ".focusloop_id"
        self.assertTrue(marker_file.exists())

        # Read back
        read_uuid = read_volume_uuid(self.local_mount)
        self.assertEqual(vol_uuid, read_uuid)

        # Verification check
        self.assertTrue(verify_volume_match(self.local_mount, vol_uuid))
        self.assertFalse(verify_volume_match(self.local_mount, "wrong-uuid-1234"))

    def test_2_add_source_and_alias_linking(self):
        """Verify adding USB mount, then adding NAS mount links as alias without duplicate source."""
        # 1. Create files on USB mount
        test_file_1 = self.local_mount / "photo1.jpg"
        test_file_2 = self.local_mount / "photo2.jpg"
        test_file_1.write_bytes(b"DATA_IMAGE_1_JPG_SAMPLE_BYTES_1234567890" * 300)
        test_file_2.write_bytes(b"DATA_IMAGE_2_JPG_SAMPLE_BYTES_0987654321" * 300)

        # Register USB source
        res1 = add_source(SourceCreate(path=str(self.local_mount), label="EasyStore USB", drive_type="HDD"))
        self.assertEqual(res1["status"], "created")
        source_id = res1["id"]

        # Index USB files
        indexer = SourceIndexer(source_id, str(self.local_mount))
        indexer.scan()
        self.assertEqual(indexer.scanned_count, 2)

        # Simulate same drive on NAS: copy .focusloop_id and files to nas_mount
        marker = (self.local_mount / ".focusloop_id").read_text(encoding="utf-8")
        (self.nas_mount / ".focusloop_id").write_text(marker, encoding="utf-8")
        (self.nas_mount / "photo1.jpg").write_bytes(test_file_1.read_bytes())
        (self.nas_mount / "photo2.jpg").write_bytes(test_file_2.read_bytes())

        # 2. Register NAS path
        res2 = add_source(SourceCreate(path=str(self.nas_mount), label="EasyStore NAS", drive_type="NAS"))
        self.assertEqual(res2["status"], "alias_linked")
        self.assertEqual(res2["id"], source_id, "Alias should return the existing source ID!")

        # Verify DB has only ONE source
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, path, alternate_paths, volume_uuid FROM sources")
        sources = cur.fetchall()
        self.assertEqual(len(sources), 1, "There should only be 1 source registered!")

        alts = json.loads(sources[0]["alternate_paths"])
        self.assertIn(str(self.local_mount), alts)
        self.assertIn(str(self.nas_mount), alts)

    def test_3_path_migration_updates_files(self):
        """Verify update_source_mount_path updates files.abs_path while preserving IDs and rel_paths."""
        # Setup source
        res = add_source(SourceCreate(path=str(self.local_mount), label="EasyStore", drive_type="HDD"))
        src_id = res["id"]

        # Create nested file
        nested_dir = self.local_mount / "2026" / "Vacation"
        nested_dir.mkdir(parents=True, exist_ok=True)
        img_file = nested_dir / "beach.jpg"
        img_file.write_bytes(b"BEACH_PHOTO_TEST_DATA" * 500)

        indexer = SourceIndexer(src_id, str(self.local_mount))
        indexer.scan()

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, abs_path, rel_path FROM files WHERE source_id = ?", (src_id,))
        files = cur.fetchall()
        self.assertEqual(len(files), 1)
        file_id = files[0]["id"]
        rel_path = files[0]["rel_path"]
        self.assertTrue(str(self.local_mount).lower() in files[0]["abs_path"].lower())

        # Now migrate to NAS mount
        migration_res = update_source_mount_path(src_id, str(self.nas_mount))
        self.assertTrue(migration_res["success"])
        self.assertEqual(migration_res["files_updated"], 1)

        # Query file again
        cur.execute("SELECT id, abs_path, rel_path FROM files WHERE id = ?", (file_id,))
        updated_file = cur.fetchone()
        self.assertEqual(updated_file["id"], file_id)
        self.assertEqual(updated_file["rel_path"], rel_path)
        self.assertTrue(str(self.nas_mount).lower() in updated_file["abs_path"].lower())

    def test_4_zero_false_duplicates(self):
        """Verify that duplicate detector detects ZERO false duplicates across USB and NAS aliasing."""
        res = add_source(SourceCreate(path=str(self.local_mount), label="EasyStore", drive_type="HDD"))
        src_id = res["id"]

        # Create two distinct photos on the drive
        f1 = self.local_mount / "photoA.jpg"
        f2 = self.local_mount / "photoB.jpg"
        f1.write_bytes(b"DISTINCT_PHOTO_A" * 700)
        f2.write_bytes(b"DISTINCT_PHOTO_B" * 700)

        indexer = SourceIndexer(src_id, str(self.local_mount))
        indexer.scan()

        # Check duplicates
        dupes = DuplicateDetector.find_duplicates()
        self.assertEqual(len(dupes), 0, "Unique photos should yield 0 duplicates")

        # Now link NAS alias
        marker = (self.local_mount / ".focusloop_id").read_text(encoding="utf-8")
        (self.nas_mount / ".focusloop_id").write_text(marker, encoding="utf-8")
        res_alias = add_source(SourceCreate(path=str(self.nas_mount), label="EasyStore NAS", drive_type="NAS"))
        self.assertEqual(res_alias["status"], "alias_linked")

        # Duplicates must still be 0!
        dupes_after = DuplicateDetector.find_duplicates()
        self.assertEqual(len(dupes_after), 0, "Aliased mount must never produce false duplicates!")

    def test_5_list_sources_auto_switches_when_offline(self):
        """Verify list_sources automatically activates an online alternate mount if current path is offline."""
        # Register source at a path that doesn't exist
        ghost_path = self.test_base / "unplugged_drive"
        vol_uuid = get_or_create_volume_uuid(self.nas_mount, label="EasyStore")

        with db_transaction() as tx:
            tx.execute("""
                INSERT INTO sources (path, label, drive_type, total_bytes, free_bytes, is_online, volume_uuid, alternate_paths)
                VALUES (?, 'AutoSwitchTest', 'HDD', 1000, 500, 1, ?, ?)
            """, (str(ghost_path), vol_uuid, json.dumps([str(ghost_path), str(self.nas_mount)])))

        sources = list_sources()
        self.assertEqual(len(sources), 1)
        src = sources[0]

        # Should auto-switch to nas_mount since ghost_path does not exist!
        self.assertEqual(src["path"], str(self.nas_mount))
        self.assertTrue(src["is_online"])

if __name__ == "__main__":
    unittest.main()
