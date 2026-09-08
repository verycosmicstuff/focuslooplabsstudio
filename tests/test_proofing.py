import os
import sys
import shutil
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.proofing.watermarker import (
    apply_text_watermark, apply_logo_watermark, resize_for_web_proof,
    process_single_image, generate_watermark_preview, watermark_manager
)
from src.proofing.contact_sheet import (
    parse_client_selects, resolve_selects_against_directory_or_db,
    execute_selects_export, generate_contact_sheet_package
)

class TestProofingAndWatermark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).resolve().parent / "mock_proofing"
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        # Create sample base test image (3000 x 2000)
        cls.sample_photo = cls.test_dir / "DSCF1001.JPG"
        img = Image.new("RGB", (3000, 2000), color=(80, 120, 180))
        draw = ImageDraw.Draw(img)
        draw.rectangle([200, 200, 2800, 1800], outline=(255, 255, 255), width=10)
        img.save(str(cls.sample_photo), "JPEG", quality=90)

        # Create companion XMP sidecar for DSCF1001
        cls.sample_xmp = cls.test_dir / "DSCF1001.xmp"
        cls.sample_xmp.write_text("<xmp:rating>5</xmp:rating>")

        # Create second test image (DSCF1002.JPG)
        cls.sample_photo2 = cls.test_dir / "DSCF1002.JPG"
        img2 = Image.new("RGB", (1200, 800), color=(180, 100, 80))
        img2.save(str(cls.sample_photo2), "JPEG", quality=85)

        # Create sample PNG logo with transparency (200 x 100)
        cls.sample_logo = cls.test_dir / "logo.png"
        logo = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        logo_draw = ImageDraw.Draw(logo)
        logo_draw.ellipse([10, 10, 190, 90], fill=(255, 215, 0, 220))
        logo.save(str(cls.sample_logo), "PNG")

    @classmethod
    def tearDownClass(cls):
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)

    def test_1_text_watermarking_diagonal_grid(self):
        """Test diagonal repeating grid text watermark."""
        img = Image.open(str(self.sample_photo)).convert("RGBA")
        watermarked = apply_text_watermark(
            img,
            text="PROOF ONLY - DO NOT COPY",
            position="diagonal_grid",
            opacity=0.40,
            font_scale=0.04
        )
        self.assertEqual(watermarked.size, (3000, 2000))
        # Ensure image has alpha composited
        self.assertEqual(watermarked.mode, "RGBA")

    def test_2_logo_watermarking(self):
        """Test PNG transparent logo watermark placement and scaling."""
        img = Image.open(str(self.sample_photo2)).convert("RGBA")
        watermarked = apply_logo_watermark(
            img,
            logo_path=str(self.sample_logo),
            position="bottom-right",
            opacity=0.85,
            scale_pct=0.20
        )
        self.assertEqual(watermarked.size, (1200, 800))

    def test_3_web_proof_resizing(self):
        """Test downscaling to web proof dimension while maintaining aspect ratio."""
        img = Image.open(str(self.sample_photo)) # 3000 x 2000
        resized = resize_for_web_proof(img, max_dimension=2048)
        self.assertEqual(resized.size[0], 2048)
        self.assertEqual(resized.size[1], 1365) # 2000 * (2048/3000)

    def test_4_process_single_image_export(self):
        """Test end-to-end single image processing with export to disk."""
        out_path = self.test_dir / "exports" / "DSCF1001_proof.jpg"
        config = {
            "watermark_type": "text",
            "text": "STUDIO PROOF",
            "position": "diagonal_grid",
            "opacity": 0.35,
            "max_dimension": 2048,
            "quality": 80
        }
        success = process_single_image(str(self.sample_photo), str(out_path), config)
        self.assertTrue(success)
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 1000)

        # Check resolution
        with Image.open(str(out_path)) as res_img:
            self.assertEqual(max(res_img.size), 2048)

    def test_5_live_preview_generation(self):
        """Test base64 live preview generation for instant UI display."""
        config = {
            "watermark_type": "text",
            "text": "LIVE TEST",
            "position": "center",
            "opacity": 0.5
        }
        data_url = generate_watermark_preview(str(self.sample_photo), config, preview_size=600)
        self.assertIsNotNone(data_url)
        self.assertTrue(data_url.startswith("data:image/jpeg;base64,"))

    def test_6_parse_client_selects(self):
        """Test intelligent parsing of various client selection formats."""
        # Comma separated
        res1 = parse_client_selects("DSCF1001, DSCF1002, DSCF1005")
        self.assertEqual(res1, ["DSCF1001", "DSCF1002", "DSCF1005"])

        # Newlines with bullets
        res2 = parse_client_selects("• DSCF1001\n- DSCF1002\n#1005")
        self.assertEqual(res2, ["DSCF1001", "DSCF1002", "1005"])

        # JSON manifest
        json_input = '{"selections": ["DSCF1001.JPG", "DSCF1002.JPG"]}'
        res3 = parse_client_selects(json_input)
        self.assertEqual(res3, ["DSCF1001.JPG", "DSCF1002.JPG"])

    def test_7_resolve_selects_and_sidecar(self):
        """Test matching client selects against folder and auto-binding .xmp sidecars."""
        queries = ["1001", "DSCF1002.JPG", "NON_EXISTENT_9999"]
        res = resolve_selects_against_directory_or_db(queries, source_dir=str(self.test_dir))

        self.assertEqual(res["matched_count"], 2)
        self.assertEqual(res["unmatched_count"], 1)
        self.assertIn("NON_EXISTENT_9999", res["unmatched"])

        # Check sidecar binding for DSCF1001
        matched_1001 = next(m for m in res["matched"] if "DSCF1001" in m["filename"])
        self.assertIsNotNone(matched_1001["sidecar_path"])
        self.assertTrue(matched_1001["sidecar_path"].endswith("DSCF1001.xmp"))

    def test_8_execute_selects_export(self):
        """Test copying matched files and sidecars to destination edit folder."""
        dest_dir = self.test_dir / "Lightroom_Selects"
        queries = ["DSCF1001"]
        resolved = resolve_selects_against_directory_or_db(queries, source_dir=str(self.test_dir))

        export_res = execute_selects_export(resolved["matched"], str(dest_dir), action="copy")
        self.assertEqual(export_res["processed_count"], 1)

        # Main image and sidecar should both exist in destination
        self.assertTrue((dest_dir / "DSCF1001.JPG").exists())
        self.assertTrue((dest_dir / "DSCF1001.xmp").exists())

    def test_9_contact_sheet_package(self):
        """Test generating interactive standalone client HTML contact sheet."""
        contact_out = self.test_dir / "Client_Package"
        files = [
            {"abs_path": str(self.sample_photo), "filename": "DSCF1001.JPG"},
            {"abs_path": str(self.sample_photo2), "filename": "DSCF1002.JPG"}
        ]
        pkg_res = generate_contact_sheet_package(
            files=files,
            output_dir=str(contact_out),
            project_title="Sarah & David Wedding",
            client_name="Sarah",
            watermark_text="PROOF ONLY"
        )
        self.assertEqual(pkg_res["status"], "ready")
        self.assertEqual(pkg_res["total_images"], 2)

        html_file = Path(pkg_res["html_path"])
        self.assertTrue(html_file.exists())
        content = html_file.read_text(encoding="utf-8")
        self.assertIn("Sarah & David Wedding", content)
        self.assertIn("DSCF1001.JPG", content)
        self.assertIn("btnCopyPicks", content)
        self.assertIn("lightbox", content)

        # Thumbnails should exist
        self.assertTrue((contact_out / "thumbnails" / "DSCF1001_thumb.jpg").exists())

    def test_10_top_center_and_bottom_center_positions(self):
        """Test top-center and bottom-center positions for both text and logo watermarks."""
        img = Image.open(str(self.sample_photo)).convert("RGBA")

        # Text: top-center
        tc_text = apply_text_watermark(img, text="TOP CENTER PROOF", position="top-center")
        self.assertEqual(tc_text.size, (3000, 2000))

        # Text: bottom-center
        bc_text = apply_text_watermark(img, text="BOTTOM CENTER PROOF", position="bottom-center")
        self.assertEqual(bc_text.size, (3000, 2000))

        # Logo: top-center
        tc_logo = apply_logo_watermark(img, logo_path=str(self.sample_logo), position="top-center")
        self.assertEqual(tc_logo.size, (3000, 2000))

        # Logo: bottom-center
        bc_logo = apply_logo_watermark(img, logo_path=str(self.sample_logo), position="bottom-center")
        self.assertEqual(bc_logo.size, (3000, 2000))

    def test_11_batch_watermark_original_folder_mode(self):
        """Test batch watermarking saving directly into respective original folders."""
        sub_folder = self.test_dir / "shoot_a"
        sub_folder.mkdir(parents=True, exist_ok=True)
        photo_a = sub_folder / "DSCF2001.JPG"
        shutil.copy(str(self.sample_photo), str(photo_a))

        files = [{"abs_path": str(photo_a), "filename": "DSCF2001.JPG"}]
        config = {
            "watermark_type": "text",
            "text": "ORIGINAL FOLDER PROOF",
            "position": "bottom-center",
            "max_dimension": 1600,
            "quality": 80
        }

        # Run synchronously via _run_batch
        watermark_manager._run_batch(
            files=files,
            output_dir=None,
            config=config,
            suffix="_proof",
            output_mode="original_folder",
            subfolder_name="_proofs"
        )

        expected_proof = sub_folder / "DSCF2001_proof.jpg"
        self.assertTrue(expected_proof.exists(), f"Expected proof {expected_proof} to exist")
        self.assertGreater(expected_proof.stat().st_size, 500)

    def test_12_batch_watermark_original_subfolder_mode(self):
        """Test batch watermarking saving into custom subfolder inside each respective photo folder."""
        sub_folder_b = self.test_dir / "shoot_b"
        sub_folder_b.mkdir(parents=True, exist_ok=True)
        photo_b = sub_folder_b / "DSCF3001.JPG"
        shutil.copy(str(self.sample_photo2), str(photo_b))

        files = [{"abs_path": str(photo_b), "filename": "DSCF3001.JPG"}]
        config = {
            "watermark_type": "logo",
            "logo_path": str(self.sample_logo),
            "logo_position": "top-center",
            "max_dimension": 1200,
            "quality": 80
        }

        watermark_manager._run_batch(
            files=files,
            output_dir=None,
            config=config,
            suffix="_clientproof",
            output_mode="original_subfolder",
            subfolder_name="_web_proofs",
            subfolder_type="custom"
        )

        expected_proof_b = sub_folder_b / "_web_proofs" / "DSCF3001_clientproof.jpg"
        self.assertTrue(expected_proof_b.exists(), f"Expected proof {expected_proof_b} to exist in subfolder")
        self.assertGreater(expected_proof_b.stat().st_size, 500)

    def test_13_multi_folder_listing(self):
        """Test scanning and aggregating photos across multiple folders."""
        dir1 = self.test_dir / "folder_alpha"
        dir2 = self.test_dir / "folder_beta"
        dir1.mkdir(parents=True, exist_ok=True)
        dir2.mkdir(parents=True, exist_ok=True)

        shutil.copy(str(self.sample_photo), str(dir1 / "alpha_01.jpg"))
        shutil.copy(str(self.sample_photo2), str(dir2 / "beta_01.jpg"))

        from src.api.server import list_photos_in_dir
        res = list_photos_in_dir({"paths": [str(dir1), str(dir2)]})

        self.assertGreaterEqual(res["total"], 2)
        filenames = [p["filename"] for p in res["photos"]]
        self.assertIn("alpha_01.jpg", filenames)
        self.assertIn("beta_01.jpg", filenames)

        folder_names = [p["folder_name"] for p in res["photos"]]
        self.assertIn("folder_alpha", folder_names)
        self.assertIn("folder_beta", folder_names)

    def test_14_subfolder_detection_and_counts(self):
        """Test subfolder discovery with photo counts and direct file counts."""
        parent = self.test_dir / "shoot_parent"
        sub1 = parent / "card_1"
        sub2 = parent / "card_2"
        sub1.mkdir(parents=True, exist_ok=True)
        sub2.mkdir(parents=True, exist_ok=True)

        shutil.copy(str(self.sample_photo), str(sub1 / "img1.jpg"))
        shutil.copy(str(self.sample_photo2), str(sub2 / "img2.jpg"))
        shutil.copy(str(self.sample_photo2), str(parent / "direct_root.jpg"))

        from src.api.server import list_directory_subfolders
        res = list_directory_subfolders({"path": str(parent), "include_counts": True})

        self.assertEqual(len(res["subfolders"]), 2)
        self.assertEqual(res["direct_photo_count"], 1)

        sub_names = {s["name"]: s["photo_count"] for s in res["subfolders"]}
        self.assertEqual(sub_names["card_1"], 1)
        self.assertEqual(sub_names["card_2"], 1)

    def test_15_folder_items_recursive_and_proofs_skip(self):
        """Test folder_items with recursive=False, and verify _proofs subfolders are skipped."""
        parent = self.test_dir / "shoot_parent"
        proofs_sub = parent / "_proofs"
        proofs_sub.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(self.sample_photo), str(proofs_sub / "img1_proof.jpg"))

        from src.api.server import list_photos_in_dir
        # Non-recursive scan on parent should only get direct_root.jpg, skipping subfolders & _proofs
        res_non_rec = list_photos_in_dir({"folder_items": [{"path": str(parent), "recursive": False}]})
        self.assertEqual(res_non_rec["total"], 1)
        self.assertEqual(res_non_rec["photos"][0]["filename"], "direct_root.jpg")

        # Recursive scan on parent should include sub1 and sub2 photos, but skip _proofs
        res_rec = list_photos_in_dir({"folder_items": [{"path": str(parent), "recursive": True}]})
        res_filenames = [p["filename"] for p in res_rec["photos"]]
        self.assertIn("img1.jpg", res_filenames)
        self.assertIn("img2.jpg", res_filenames)
        self.assertIn("direct_root.jpg", res_filenames)
        self.assertNotIn("img1_proof.jpg", res_filenames)

    def test_16_batch_watermark_endpoint_null_output_dir(self):
        """Test start_watermark_batch API with output_dir=None (original_subfolder mode)."""
        from src.api.server import start_watermark_batch
        payload = {
            "file_ids": [],
            "file_paths": [str(self.sample_photo)],
            "output_dir": None,
            "output_mode": "original_subfolder",
            "subfolder_name": "_proofs",
            "suffix": "_proof",
            "config": {
                "watermark_type": "text",
                "text": "TEST NULL OUTPUT DIR",
                "position": "diagonal_grid"
            }
        }
        res = start_watermark_batch(payload)
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["output_mode"], "original_subfolder")
        self.assertEqual(res["total_files"], 1)

    def test_17_session_state_and_last_task(self):
        """Test GET and POST session state and recording last tasks."""
        from src.api.server import api_get_session_state, api_save_session_state
        from src.core.session import record_last_task

        # 1. Fetch initial state
        state = api_get_session_state()
        self.assertIn("version", state)
        self.assertIn("watermark_settings", state)

        # 2. Update state
        updated = api_save_session_state({
            "last_active_tab": "proofing",
            "last_proofing_subview": "watermark",
            "watermark_settings": {
                "text": "SESSION PERSISTENCE TEST"
            }
        })
        self.assertEqual(updated["last_active_tab"], "proofing")
        self.assertEqual(updated["watermark_settings"]["text"], "SESSION PERSISTENCE TEST")

        # 3. Record a completed task
        record_last_task("test_task", "Completed test task for verification")
        latest = api_get_session_state()
        self.assertEqual(latest["last_task"]["task_type"], "test_task")
        self.assertEqual(latest["last_task"]["summary"], "Completed test task for verification")
        self.assertGreater(latest["last_task"]["timestamp"], 0)

    def test_18_logs_endpoints(self):
        """Test recent logs retrieval endpoint."""
        from src.api.server import api_get_recent_logs
        res = api_get_recent_logs(lines=50)
        self.assertIn("path", res)
        self.assertIn("lines", res)
        self.assertIsInstance(res["lines"], list)
        self.assertGreater(len(res["lines"]), 0)

    def test_19_batch_watermark_subfolder_prefix_and_suffix(self):
        """Test batch watermarking with prefix and suffix subfolder modes."""
        pref_folder = self.test_dir / "shoot_pref"
        suff_folder = self.test_dir / "shoot_suff"
        pref_folder.mkdir(parents=True, exist_ok=True)
        suff_folder.mkdir(parents=True, exist_ok=True)

        photo_p = pref_folder / "DSCF4001.JPG"
        photo_s = suff_folder / "DSCF4002.JPG"
        shutil.copy(str(self.sample_photo), str(photo_p))
        shutil.copy(str(self.sample_photo2), str(photo_s))

        config = {
            "watermark_type": "text",
            "text": "PREFIX SUFFIX TEST",
            "position": "bottom-center",
            "max_dimension": 800,
            "quality": 80
        }

        # Test Prefix mode (e.g. _proofs -> _proofs_shoot_pref)
        watermark_manager._run_batch(
            files=[{"abs_path": str(photo_p), "filename": "DSCF4001.JPG"}],
            output_dir=None,
            config=config,
            suffix="_p",
            output_mode="original_subfolder",
            subfolder_name="_proofs",
            subfolder_type="prefix"
        )
        expected_pref = pref_folder / "_proofs_shoot_pref" / "DSCF4001_p.jpg"
        self.assertTrue(expected_pref.exists(), f"Expected {expected_pref} to exist")

        # Test Suffix mode (e.g. _web -> shoot_suff_web)
        watermark_manager._run_batch(
            files=[{"abs_path": str(photo_s), "filename": "DSCF4002.JPG"}],
            output_dir=None,
            config=config,
            suffix="_s",
            output_mode="original_subfolder",
            subfolder_name="_web",
            subfolder_type="suffix"
        )
        expected_suff = suff_folder / "shoot_suff_web" / "DSCF4002_s.jpg"
        self.assertTrue(expected_suff.exists(), f"Expected {expected_suff} to exist")

    def test_20_watermark_presets_crud_and_api(self):
        """Test preset engine and API CRUD operations for presets."""
        from src.proofing.presets import get_all_presets, save_preset, delete_preset, get_preset_by_id
        from src.api.server import api_get_presets, api_save_preset, api_delete_preset

        # 1. Fetch default presets
        presets = get_all_presets()
        self.assertGreaterEqual(len(presets), 5)
        builtin_ids = [p["id"] for p in presets if p.get("is_builtin")]
        self.assertIn("builtin_diagonal_text", builtin_ids)
        self.assertIn("builtin_logo_bottom_right", builtin_ids)

        # 2. Cannot delete built-in
        can_del_builtin = delete_preset("builtin_diagonal_text")
        self.assertFalse(can_del_builtin)

        # 3. Create a new custom preset
        new_preset = save_preset(
            name="Unit Test Custom Preset",
            config={
                "watermark_type": "text",
                "text": "UNIT TEST PRESET",
                "position": "center",
                "opacity": 0.5,
                "font_scale": 0.05,
                "quality": 88,
                "max_dimension": 2500,
                "output_mode": "original_subfolder",
                "subfolder_name": "_custom_proofs",
                "subfolder_type": "suffix"
            }
        )
        self.assertEqual(new_preset["name"], "Unit Test Custom Preset")
        self.assertFalse(new_preset["is_builtin"])
        custom_id = new_preset["id"]

        # Verify lookup
        fetched = get_preset_by_id(custom_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["config"]["text"], "UNIT TEST PRESET")

        # 4. Update the custom preset
        updated = save_preset(
            name="Unit Test Custom Preset (Updated)",
            config={
                "watermark_type": "logo",
                "text": "UPDATED TEXT",
                "quality": 90
            },
            preset_id=custom_id
        )
        self.assertEqual(updated["name"], "Unit Test Custom Preset (Updated)")
        self.assertEqual(updated["config"]["quality"], 90)

        # 5. Test API Endpoints
        api_res = api_get_presets()
        self.assertIn("presets", api_res)
        self.assertTrue(any(p["id"] == custom_id for p in api_res["presets"]))

        # 6. Delete the custom preset
        del_success = delete_preset(custom_id)
        self.assertTrue(del_success)
        self.assertIsNone(get_preset_by_id(custom_id))

if __name__ == "__main__":
    unittest.main()

