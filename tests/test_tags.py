import sys
import shutil
import unittest
import time
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.config
import src.core.db
from src.core.db import init_db, get_db, close_db
from src.core.tag_manager import TagManager
from src.api.server import app

class TestTaggingAndCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).resolve().parent / "mock_tag_storage"
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        cls.orig_db_path = src.config.DB_PATH
        cls.test_db_path = cls.test_dir / "test_tags.db"
        src.config.DB_PATH = cls.test_db_path
        src.core.db._thread_local.conn = None
        init_db()

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        src.config.DB_PATH = cls.orig_db_path
        close_db()
        import gc
        gc.collect()
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        # Create mock source and files
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM files")
        cursor.execute("DELETE FROM sources")
        cursor.execute("DELETE FROM file_tags")
        cursor.execute("DELETE FROM media_notes")
        conn.commit()

        cursor.execute("""
            INSERT INTO sources (id, path, label, drive_type)
            VALUES (1, 'F:\\Videos\\Interviews', 'SSD Primary', 'SSD')
        """)
        cursor.execute("""
            INSERT INTO sources (id, path, label, drive_type)
            VALUES (2, 'E:\\Archive\\2026', 'Backup HDD', 'HDD')
        """)

        # Insert 3 sample video files in different folders
        cursor.execute("""
            INSERT INTO files (id, source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, status)
            VALUES (101, 1, 'ShootA\\CEO_Keynote.mp4', 'F:\\Videos\\Interviews\\ShootA\\CEO_Keynote.mp4', 'CEO_Keynote.mp4', '.mp4', 500000000, 1000.0, 1000.0, 'video', 'active')
        """)
        cursor.execute("""
            INSERT INTO files (id, source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, status)
            VALUES (102, 1, 'ShootA\\Q3_Finance_Review.mp4', 'F:\\Videos\\Interviews\\ShootA\\Q3_Finance_Review.mp4', 'Q3_Finance_Review.mp4', '.mp4', 250000000, 2000.0, 2000.0, 'video', 'active')
        """)
        cursor.execute("""
            INSERT INTO files (id, source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, status)
            VALUES (103, 2, 'Broll\\Product_Broll.mov', 'E:\\Archive\\2026\\Broll\\Product_Broll.mov', 'Product_Broll.mov', '.mov', 800000000, 3000.0, 3000.0, 'video', 'active')
        """)
        # Insert 1 photo
        cursor.execute("""
            INSERT INTO files (id, source_id, rel_path, abs_path, filename, ext, size_bytes, mtime, ctime, media_type, status)
            VALUES (104, 1, 'Stills\\Speaker_Portrait.jpg', 'F:\\Videos\\Interviews\\Stills\\Speaker_Portrait.jpg', 'Speaker_Portrait.jpg', '.jpg', 15000000, 4000.0, 4000.0, 'photo', 'active')
        """)

        # Add media_meta for duration
        cursor.execute("""
            INSERT INTO media_meta (file_id, duration_sec, width, height, video_codec)
            VALUES (101, 1800.0, 3840, 2160, 'h264')
        """)
        cursor.execute("""
            INSERT INTO media_meta (file_id, duration_sec, width, height, video_codec)
            VALUES (102, 600.0, 1920, 1080, 'h264')
        """)
        conn.commit()

    def test_add_and_retrieve_categorized_tags(self):
        """Test adding speaker, topic, mention, and general tags to a file."""
        tags = [
            {"tag": "CEO Tim", "category": "speaker"},
            {"tag": "Annual Keynote", "category": "topic"},
            {"tag": "Project Apollo", "category": "mention"},
            {"tag": "4K Master", "category": "general"}
        ]
        res = TagManager.add_tags([101], tags)
        self.assertEqual(res["added_count"], 4)

        all_tags = TagManager.get_all_tags()
        self.assertEqual(all_tags["total_unique"], 4)
        self.assertTrue(any(s["tag"] == "CEO Tim" for s in all_tags["speakers"]))
        self.assertTrue(any(s["tag"] == "Annual Keynote" for s in all_tags["topics"]))
        self.assertTrue(any(s["tag"] == "Project Apollo" for s in all_tags["mentions"]))
        self.assertTrue(any(s["tag"] == "4K Master" for s in all_tags["general"]))

    def test_notes_and_rating(self):
        """Test adding notes and star rating to a media item."""
        TagManager.update_notes(101, notes="Tim discussed AI roadmap in first 10 mins.", rating=5)
        cat = TagManager.query_catalog(search="Tim discussed AI")
        self.assertEqual(cat["total_count"], 1)
        item = cat["items"][0]
        self.assertEqual(item["id"], 101)
        self.assertEqual(item["notes"], "Tim discussed AI roadmap in first 10 mins.")
        self.assertEqual(item["rating"], 5)

    def test_batch_tagging_across_multiple_files(self):
        """Test tagging multiple files at once (e.g. folder batch tagging)."""
        res = TagManager.add_tags([101, 102], [{"tag": "Sarah Chen", "category": "speaker"}])
        self.assertEqual(res["added_count"], 2)

        # Query catalog by speaker tag
        cat = TagManager.query_catalog(tag="Sarah Chen")
        self.assertEqual(cat["total_count"], 2)
        item_ids = {i["id"] for i in cat["items"]}
        self.assertEqual(item_ids, {101, 102})

    def test_filtering_by_scope_folder_and_drive(self):
        """Test filtering by whole collection, specific drive, and specific folder."""
        # 1. Whole collection
        cat_all = TagManager.query_catalog()
        self.assertEqual(cat_all["total_count"], 4)

        # 2. Specific drive (source_id = 1)
        cat_src1 = TagManager.query_catalog(source_id=1)
        self.assertEqual(cat_src1["total_count"], 3)

        # 3. Specific subfolder (ShootA)
        cat_shoota = TagManager.query_catalog(folder="ShootA")
        self.assertEqual(cat_shoota["total_count"], 2)

        # 4. Media type filter: videos only
        cat_videos = TagManager.query_catalog(media_type="video")
        self.assertEqual(cat_videos["total_count"], 3)

        # 5. Media type filter: photos only
        cat_photos = TagManager.query_catalog(media_type="photo")
        self.assertEqual(cat_photos["total_count"], 1)
        self.assertEqual(cat_photos["items"][0]["filename"], "Speaker_Portrait.jpg")

    def test_untagged_vs_tagged_filter(self):
        """Test filtering untagged vs tagged items."""
        TagManager.add_tags([101], [{"tag": "Interview", "category": "general"}])

        tagged_res = TagManager.query_catalog(tag_status="tagged")
        self.assertEqual(tagged_res["total_count"], 1)
        self.assertEqual(tagged_res["items"][0]["id"], 101)

        untagged_res = TagManager.query_catalog(tag_status="untagged")
        self.assertEqual(untagged_res["total_count"], 3)
        self.assertNotIn(101, [i["id"] for i in untagged_res["items"]])

    def test_sorting_options(self):
        """Test sorting by duration, size, name, and tags count."""
        # Duration desc: 101 (1800s), 102 (600s), others (0s)
        dur_cat = TagManager.query_catalog(sort_by="duration_desc")
        self.assertEqual(dur_cat["items"][0]["id"], 101)
        self.assertEqual(dur_cat["items"][1]["id"], 102)

        # Name asc: CEO_Keynote.mp4 -> Product_Broll.mov -> Q3_Finance_Review.mp4 -> Speaker_Portrait.jpg
        name_cat = TagManager.query_catalog(sort_by="name_asc")
        self.assertEqual(name_cat["items"][0]["filename"], "CEO_Keynote.mp4")

    def test_rest_api_endpoints(self):
        """Test API endpoints /api/tags/catalog, /api/tags/update, /api/tags/notes, etc."""
        # 1. Update tags via API
        resp = self.client.post("/api/tags/update", json={
            "file_ids": [101],
            "add_tags": [{"tag": "Dr. Smith", "category": "speaker"}, {"tag": "AI Tech", "category": "topic"}]
        })
        self.assertEqual(resp.status_code, 200)

        # 2. Fetch catalog via API
        cat_resp = self.client.get("/api/tags/catalog?tag=Dr. Smith")
        self.assertEqual(cat_resp.status_code, 200)
        data = cat_resp.json()
        self.assertEqual(data["total_count"], 1)
        self.assertEqual(data["items"][0]["id"], 101)
        self.assertEqual(len(data["items"][0]["tags"]), 2)

        # 3. Add notes via API
        note_resp = self.client.post("/api/tags/notes", json={
            "file_id": 101,
            "notes": "Timestamp 04:30 discussion about neural nets.",
            "rating": 4
        })
        self.assertEqual(note_resp.status_code, 200)

        # 4. Search via API
        search_resp = self.client.get("/api/tags/catalog?search=neural nets")
        self.assertEqual(search_resp.status_code, 200)
        self.assertEqual(search_resp.json()["total_count"], 1)

        # 5. Get distinct folders
        folder_resp = self.client.get("/api/tags/folders")
        self.assertEqual(folder_resp.status_code, 200)
        folders = folder_resp.json()["folders"]
        self.assertTrue(len(folders) >= 2)

        # 6. Get all tags
        all_tags_resp = self.client.get("/api/tags/all")
        self.assertEqual(all_tags_resp.status_code, 200)
        tags_data = all_tags_resp.json()
        self.assertTrue(any(s["tag"] == "Dr. Smith" for s in tags_data["speakers"]))

if __name__ == "__main__":
    unittest.main()
