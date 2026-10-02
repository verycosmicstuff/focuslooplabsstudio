import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from src.core.db import get_db, db_transaction
from src.core.logger import get_logger

logger = get_logger("tag_manager")

VALID_CATEGORIES = {"speaker", "topic", "mention", "general"}

def normalize_category(cat: Optional[str]) -> str:
    if not cat:
        return "general"
    clean = str(cat).strip().lower()
    return clean if clean in VALID_CATEGORIES else "general"

def normalize_tag(tag: str) -> str:
    if not tag:
        return ""
    # Strip whitespace
    return str(tag).strip()

class TagManager:
    @staticmethod
    def add_tags(file_ids: List[int], tags: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Adds tags to multiple files.
        Each tag can be a dict with {"tag": "...", "category": "speaker|topic|mention|general"}.
        """
        if not file_ids or not tags:
            return {"added_count": 0, "file_count": len(file_ids)}

        cleaned_tags = []
        for t in tags:
            tag_name = normalize_tag(t.get("tag", ""))
            category = normalize_category(t.get("category", "general"))
            if tag_name:
                cleaned_tags.append((tag_name, category))

        if not cleaned_tags:
            return {"added_count": 0, "file_count": len(file_ids)}

        added = 0
        with db_transaction() as tx:
            cur = tx.cursor()
            for fid in file_ids:
                for tag_name, category in cleaned_tags:
                    cur.execute("""
                        INSERT OR IGNORE INTO file_tags (file_id, tag, category)
                        VALUES (?, ?, ?)
                    """, (fid, tag_name, category))
                    if cur.rowcount > 0:
                        added += 1

        logger.info(f"Added {added} tags across {len(file_ids)} files.")
        return {"added_count": added, "file_count": len(file_ids)}

    @staticmethod
    def remove_tags(file_ids: List[int], tags: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Removes specified tags from files.
        """
        if not file_ids or not tags:
            return {"removed_count": 0, "file_count": len(file_ids)}

        removed = 0
        with db_transaction() as tx:
            cur = tx.cursor()
            for fid in file_ids:
                for t in tags:
                    tag_name = normalize_tag(t.get("tag", ""))
                    cat = t.get("category")
                    if not tag_name:
                        continue
                    if cat:
                        cur.execute("""
                            DELETE FROM file_tags
                            WHERE file_id = ? AND LOWER(tag) = LOWER(?) AND category = ?
                        """, (fid, tag_name, normalize_category(cat)))
                    else:
                        cur.execute("""
                            DELETE FROM file_tags
                            WHERE file_id = ? AND LOWER(tag) = LOWER(?)
                        """, (fid, tag_name))
                    removed += cur.rowcount

        logger.info(f"Removed {removed} tags across {len(file_ids)} files.")
        return {"removed_count": removed, "file_count": len(file_ids)}

    @staticmethod
    def set_file_tags(file_id: int, tags: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Replaces all tags on a specific file.
        """
        cleaned_tags = []
        for t in tags:
            tag_name = normalize_tag(t.get("tag", ""))
            category = normalize_category(t.get("category", "general"))
            if tag_name:
                cleaned_tags.append((tag_name, category))

        with db_transaction() as tx:
            cur = tx.cursor()
            cur.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
            for tag_name, category in cleaned_tags:
                cur.execute("""
                    INSERT OR IGNORE INTO file_tags (file_id, tag, category)
                    VALUES (?, ?, ?)
                """, (file_id, tag_name, category))

        return {"file_id": file_id, "tag_count": len(cleaned_tags)}

    @staticmethod
    def update_notes(file_id: int, notes: Optional[str] = None, rating: Optional[int] = None) -> Dict[str, Any]:
        """
        Updates notes or star rating for a file.
        """
        with db_transaction() as tx:
            cur = tx.cursor()
            cur.execute("SELECT file_id, notes, rating FROM media_notes WHERE file_id = ?", (file_id,))
            row = cur.fetchone()

            if row:
                current_notes = row["notes"]
                current_rating = row["rating"]
                new_notes = notes if notes is not None else current_notes
                new_rating = rating if rating is not None else current_rating
                cur.execute("""
                    UPDATE media_notes
                    SET notes = ?, rating = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE file_id = ?
                """, (new_notes, new_rating, file_id))
            else:
                cur.execute("""
                    INSERT INTO media_notes (file_id, notes, rating)
                    VALUES (?, ?, ?)
                """, (file_id, notes or "", rating or 0))

        return {"file_id": file_id, "notes": notes, "rating": rating}

    @staticmethod
    def get_all_tags() -> Dict[str, Any]:
        """
        Returns all unique tags across the catalog grouped by category with usage counts.
        """
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tag, category, COUNT(DISTINCT file_id) as count
            FROM file_tags
            GROUP BY tag, category
            ORDER BY count DESC, tag ASC
        """)
        rows = cursor.fetchall()

        all_tags = []
        speakers = []
        topics = []
        mentions = []
        general = []

        for r in rows:
            item = {"tag": r["tag"], "category": r["category"], "count": r["count"]}
            all_tags.append(item)
            cat = r["category"]
            if cat == "speaker":
                speakers.append(item)
            elif cat == "topic":
                topics.append(item)
            elif cat == "mention":
                mentions.append(item)
            else:
                general.append(item)

        return {
            "all": all_tags,
            "speakers": speakers,
            "topics": topics,
            "mentions": mentions,
            "general": general,
            "total_unique": len(all_tags)
        }

    @staticmethod
    def get_distinct_folders(source_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Returns list of distinct folders containing active media for filter dropdowns.
        """
        conn = get_db()
        cursor = conn.cursor()

        query = """
            SELECT DISTINCT f.abs_path, f.source_id, s.label as source_label
            FROM files f
            JOIN sources s ON f.source_id = s.id
            WHERE f.status = 'active'
              AND f.filename NOT LIKE '$%' AND f.abs_path NOT LIKE '%$recycle.bin%'
        """
        params = []
        if source_id:
            query += " AND f.source_id = ?"
            params.append(source_id)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        folder_map = {}
        for r in rows:
            try:
                raw_path = r["abs_path"]
                # Cross-platform normalization for both Windows (\) and POSIX (/) paths
                norm_path = raw_path.replace("\\", "/")
                parts = norm_path.rsplit("/", 1)
                parent_dir = parts[0] if len(parts) > 1 else str(Path(raw_path).parent)
                dir_name = parent_dir.rsplit("/", 1)[-1] if "/" in parent_dir else parent_dir
                if parent_dir not in folder_map:
                    folder_map[parent_dir] = {
                        "path": parent_dir,
                        "name": dir_name if dir_name else parent_dir,
                        "source_id": r["source_id"],
                        "source_label": r["source_label"],
                        "file_count": 0
                    }
                folder_map[parent_dir]["file_count"] += 1
            except Exception:
                pass

        folders = sorted(folder_map.values(), key=lambda x: (x["source_label"], x["name"].lower()))
        return folders

    @staticmethod
    def query_catalog(
        source_id: Optional[int] = None,
        folder: Optional[str] = None,
        media_type: Optional[str] = "all",
        tag: Optional[str] = None,
        category: Optional[str] = None,
        tag_status: Optional[str] = "all",
        search: Optional[str] = None,
        sort_by: str = "mtime_desc",
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Main query for the Media Tags & Catalog view with comprehensive sorting and filtering.
        """
        conn = get_db()
        cursor = conn.cursor()

        where_clauses = [
            "f.status = 'active'",
            "f.filename NOT LIKE '$%'",
            "f.abs_path NOT LIKE '%$recycle.bin%'"
        ]
        params: List[Any] = []

        if source_id:
            where_clauses.append("f.source_id = ?")
            params.append(source_id)

        if folder:
            f_slash = folder.replace("\\", "/")
            f_bslash = folder.replace("/", "\\")
            where_clauses.append("(f.abs_path LIKE ? OR f.abs_path LIKE ? OR f.rel_path LIKE ? OR f.rel_path LIKE ?)")
            params.extend([f"%{f_slash}%", f"%{f_bslash}%", f"%{f_slash}%", f"%{f_bslash}%"])

        if media_type == "video":
            where_clauses.append("f.media_type = 'video'")
        elif media_type == "photo":
            where_clauses.append("f.media_type IN ('photo', 'raw')")
        elif media_type == "raw":
            where_clauses.append("f.media_type = 'raw'")

        if tag:
            where_clauses.append("""
                EXISTS (
                    SELECT 1 FROM file_tags ft_filter
                    WHERE ft_filter.file_id = f.id AND LOWER(ft_filter.tag) = LOWER(?)
                )
            """)
            params.append(tag)

        if category:
            where_clauses.append("""
                EXISTS (
                    SELECT 1 FROM file_tags ft_cat
                    WHERE ft_cat.file_id = f.id AND ft_cat.category = ?
                )
            """)
            params.append(normalize_category(category))

        if tag_status == "tagged":
            where_clauses.append("""
                EXISTS (SELECT 1 FROM file_tags ft_has WHERE ft_has.file_id = f.id)
            """)
        elif tag_status == "untagged":
            where_clauses.append("""
                NOT EXISTS (SELECT 1 FROM file_tags ft_no WHERE ft_no.file_id = f.id)
            """)

        if search:
            search_clean = f"%{search.strip().lower()}%"
            where_clauses.append("""
                (
                    LOWER(f.filename) LIKE ?
                    OR LOWER(f.rel_path) LIKE ?
                    OR LOWER(COALESCE(n.notes, '')) LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM file_tags ft_s
                        WHERE ft_s.file_id = f.id AND LOWER(ft_s.tag) LIKE ?
                    )
                )
            """)
            params.extend([search_clean, search_clean, search_clean, search_clean])

        where_sql = " AND ".join(where_clauses)

        # 1. Get total count
        count_sql = f"""
            SELECT COUNT(*) as total_count
            FROM files f
            LEFT JOIN media_notes n ON f.id = n.file_id
            WHERE {where_sql}
        """
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()["total_count"]

        # Tagged vs Untagged stats under current filter scope (ignoring tag_status)
        tagged_stat_sql = f"""
            SELECT
                SUM(CASE WHEN EXISTS (SELECT 1 FROM file_tags ft_sub WHERE ft_sub.file_id = f.id) THEN 1 ELSE 0 END) as tagged_count,
                SUM(CASE WHEN NOT EXISTS (SELECT 1 FROM file_tags ft_sub WHERE ft_sub.file_id = f.id) THEN 1 ELSE 0 END) as untagged_count
            FROM files f
            LEFT JOIN media_notes n ON f.id = n.file_id
            WHERE {where_sql}
        """
        cursor.execute(tagged_stat_sql, params)
        stat_row = cursor.fetchone()
        tagged_count = stat_row["tagged_count"] or 0
        untagged_count = stat_row["untagged_count"] or 0

        # 2. Sorting
        sort_map = {
            "mtime_desc": "f.mtime DESC",
            "mtime_asc": "f.mtime ASC",
            "name_asc": "LOWER(f.filename) ASC",
            "name_desc": "LOWER(f.filename) DESC",
            "size_desc": "f.size_bytes DESC",
            "size_asc": "f.size_bytes ASC",
            "duration_desc": "COALESCE(m.duration_sec, 0) DESC, f.size_bytes DESC",
            "duration_asc": "COALESCE(m.duration_sec, 0) ASC, f.size_bytes ASC",
            "tags_desc": "(SELECT COUNT(*) FROM file_tags ft_c WHERE ft_c.file_id = f.id) DESC, f.mtime DESC",
            "rating_desc": "COALESCE(n.rating, 0) DESC, f.mtime DESC",
            "capture_desc": "COALESCE(m.capture_date, '') DESC, f.mtime DESC"
        }
        order_sql = sort_map.get(sort_by, "f.mtime DESC")

        # 3. Fetch items
        items_sql = f"""
            SELECT f.id, f.source_id, f.abs_path, f.rel_path, f.filename, f.ext, f.size_bytes, f.mtime, f.media_type,
                   s.label as source_label, s.path as source_root,
                   m.width, m.height, m.duration_sec, m.video_codec, m.audio_codec, m.bitrate, m.fps, m.camera_model, m.capture_date,
                   n.notes, n.rating,
                   (
                       SELECT json_group_array(json_object('tag', ft.tag, 'category', ft.category))
                       FROM file_tags ft WHERE ft.file_id = f.id
                   ) as tags_json
            FROM files f
            JOIN sources s ON f.source_id = s.id
            LEFT JOIN media_meta m ON f.id = m.file_id
            LEFT JOIN media_notes n ON f.id = n.file_id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """
        fetch_params = params + [limit, offset]
        cursor.execute(items_sql, fetch_params)
        raw_items = [dict(r) for r in cursor.fetchall()]

        items = []
        for r in raw_items:
            # Parse parent folder
            p = Path(r["abs_path"])
            parent = p.parent
            parent_name = parent.name if parent.name else str(parent)
            r["folder_name"] = parent_name
            r["folder_path"] = str(parent)

            # Parse tags JSON
            tags_list = []
            try:
                raw_tags = json.loads(r.get("tags_json") or "[]")
                # Filter out null entries if empty json_group_array returned [null]
                tags_list = [t for t in raw_tags if t and t.get("tag")]
            except Exception:
                tags_list = []
            r["tags"] = tags_list
            r["tags_count"] = len(tags_list)

            # Clean notes & rating
            r["notes"] = r.get("notes") or ""
            r["rating"] = r.get("rating") or 0

            items.append(r)

        return {
            "items": items,
            "total_count": total_count,
            "tagged_count": tagged_count,
            "untagged_count": untagged_count,
            "limit": limit,
            "offset": offset
        }
