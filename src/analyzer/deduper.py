from typing import List, Dict, Any, Optional
from src.core.db import get_db
from src.scanner.indexer import compute_full_hash

class DuplicateDetector:
    @staticmethod
    def find_duplicates(
        source_id: Optional[int] = None,
        cross_source_only: bool = False,
        same_name_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Finds duplicate media clusters using fast_hash and verifies with full_hash if matched.
        Excludes sidecar files (.xmp, .thm, etc.) and enforces minimum media size (>= 10 KB).
        """
        conn = get_db()
        cursor = conn.cursor()

        # Group by fast_hash and size_bytes
        # Only true media files (photo, raw, video) >= 10 KB; never sidecars (.xmp)
        query = """
            SELECT fast_hash, size_bytes, COUNT(*) as cnt
            FROM files
            WHERE status = 'active'
              AND media_type IN ('photo', 'raw', 'video')
              AND ext NOT IN ('.xmp', '.thm', '.lrf', '.xml', '.json', '.txt')
              AND size_bytes >= 10240
              AND fast_hash != ''
        """
        params = []
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)

        query += " GROUP BY fast_hash, size_bytes HAVING cnt > 1"
        cursor.execute(query, params)
        candidates = cursor.fetchall()

        duplicate_groups = []

        for cand in candidates:
            fhash = cand["fast_hash"]
            size = cand["size_bytes"]

            cursor.execute("""
                SELECT f.id, f.source_id, f.rel_path, f.abs_path, f.filename, f.size_bytes, f.mtime, f.media_type, f.full_hash,
                       s.label as source_label, s.drive_type
                FROM files f
                JOIN sources s ON f.source_id = s.id
                WHERE f.fast_hash = ? AND f.size_bytes = ? AND f.status = 'active'
                  AND f.media_type IN ('photo', 'raw', 'video')
                  AND f.ext NOT IN ('.xmp', '.thm', '.lrf', '.xml', '.json', '.txt')
                ORDER BY f.mtime ASC
            """, (fhash, size))
            file_rows = [dict(r) for r in cursor.fetchall()]

            if len(file_rows) < 2:
                continue

            # Verify with full sha256 if not already computed
            verified_by_full_hash = {}
            for item in file_rows:
                full_h = item.get("full_hash")
                if not full_h:
                    full_h = compute_full_hash(item["abs_path"])
                    if full_h:
                        cursor.execute("UPDATE files SET full_hash = ? WHERE id = ?", (full_h, item["id"]))
                        item["full_hash"] = full_h

                if full_h:
                    verified_by_full_hash.setdefault(full_h, []).append(item)

            conn.commit()

            # Process groups that match full sha256
            for full_h, matched_files in verified_by_full_hash.items():
                if len(matched_files) < 2:
                    continue

                # Check cross source requirement if requested
                unique_sources = {m["source_id"] for m in matched_files}
                if cross_source_only and len(unique_sources) < 2:
                    continue

                if same_name_only:
                    # Partition by filename (case-insensitive)
                    by_name = {}
                    for m in matched_files:
                        by_name.setdefault(m["filename"].lower(), []).append(m)
                    subgroups = [grp for grp in by_name.values() if len(grp) >= 2]
                else:
                    subgroups = [matched_files]

                for grp in subgroups:
                    # Authoritative primary: NAS or backup copy, otherwise oldest
                    primary_item = grp[0]
                    for m in grp:
                        if m["drive_type"] in ("NAS", "HDD") or "backup" in m["source_label"].lower():
                            primary_item = m
                            break

                    primary_name = primary_item["filename"].lower()
                    for m in grp:
                        m["is_same_filename"] = (m["filename"].lower() == primary_name)

                    all_same_name = all(m["is_same_filename"] for m in grp)

                    duplicate_groups.append({
                        "hash": full_h,
                        "file_size": size,
                        "count": len(grp),
                        "potential_savings_bytes": size * (len(grp) - 1),
                        "primary_id": primary_item["id"],
                        "primary_filename": primary_item["filename"],
                        "all_same_name": all_same_name,
                        "files": grp
                    })

        return duplicate_groups
