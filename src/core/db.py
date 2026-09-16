import sqlite3
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
import src.config

from contextlib import contextmanager

_thread_local = threading.local()
db_write_lock = threading.RLock()

def get_db():
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        conn = sqlite3.connect(str(src.config.DB_PATH), check_same_thread=False, timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 60000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        _thread_local.conn = conn
    return _thread_local.conn

def close_db():
    if hasattr(_thread_local, "conn") and _thread_local.conn is not None:
        try:
            _thread_local.conn.close()
        except Exception:
            pass
        _thread_local.conn = None

@contextmanager
def db_transaction():
    """Thread-safe write transaction manager for SQLite."""
    with db_write_lock:
        conn = get_db()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

def init_db():
    with db_write_lock:
        conn = get_db()
        cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        label TEXT NOT NULL,
        drive_type TEXT DEFAULT 'LOCAL', -- SSD, HDD, NAS, CLOUD
        total_bytes INTEGER DEFAULT 0,
        free_bytes INTEGER DEFAULT 0,
        is_online BOOLEAN DEFAULT 1,
        excluded_paths TEXT DEFAULT '[]', -- JSON list of excluded/deselected subfolders
        volume_uuid TEXT,
        alternate_paths TEXT DEFAULT '[]', -- JSON list of alternate/alias paths (e.g. NAS UNC or local drive letter)
        last_scanned TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
        rel_path TEXT NOT NULL,
        abs_path TEXT UNIQUE NOT NULL,
        filename TEXT NOT NULL,
        ext TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        mtime REAL NOT NULL,
        ctime REAL NOT NULL,
        media_type TEXT NOT NULL, -- raw, photo, video, sidecar, other
        fast_hash TEXT,
        full_hash TEXT,
        pair_id TEXT, -- Groups RAW + XMP + JPG together
        status TEXT DEFAULT 'active' -- active, quarantined, deleted, transcoded
    );

    CREATE INDEX IF NOT EXISTS idx_files_fast_hash ON files(fast_hash);
    CREATE INDEX IF NOT EXISTS idx_files_full_hash ON files(full_hash);
    CREATE INDEX IF NOT EXISTS idx_files_pair_id ON files(pair_id);
    CREATE INDEX IF NOT EXISTS idx_files_media_type ON files(media_type);
    CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_id);

    CREATE TABLE IF NOT EXISTS media_meta (
        file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
        width INTEGER,
        height INTEGER,
        duration_sec REAL,
        video_codec TEXT,
        audio_codec TEXT,
        bitrate INTEGER,
        fps REAL,
        camera_make TEXT,
        camera_model TEXT,
        lens TEXT,
        iso INTEGER,
        shutter TEXT,
        aperture REAL,
        capture_date TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_meta_camera ON media_meta(camera_model);
    CREATE INDEX IF NOT EXISTS idx_meta_capture ON media_meta(capture_date);

    CREATE TABLE IF NOT EXISTS culling (
        file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
        blur_score REAL, -- 0 to 100
        is_blurry BOOLEAN DEFAULT 0,
        burst_group TEXT,
        is_burst_best BOOLEAN DEFAULT 0,
        disposition TEXT DEFAULT 'review' -- keep, trash, review, ignore
    );

    CREATE INDEX IF NOT EXISTS idx_culling_burst ON culling(burst_group);
    CREATE INDEX IF NOT EXISTS idx_culling_blur ON culling(blur_score);
    CREATE INDEX IF NOT EXISTS idx_culling_disp ON culling(disposition);

    CREATE TABLE IF NOT EXISTS transcodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
        output_path TEXT NOT NULL,
        status TEXT DEFAULT 'pending', -- pending, transcoding, verifying, completed, failed, paused
        profile TEXT NOT NULL,
        original_size INTEGER NOT NULL,
        converted_size INTEGER DEFAULT 0,
        saved_bytes INTEGER DEFAULT 0,
        progress REAL DEFAULT 0.0,
        speed TEXT DEFAULT '',
        fps REAL DEFAULT 0.0,
        error_msg TEXT,
        started_at TIMESTAMP,
        finished_at TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_transcode_status ON transcodes(status);

    CREATE TABLE IF NOT EXISTS sync_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fast_hash TEXT NOT NULL,
        file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
        source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
        is_backup BOOLEAN DEFAULT 0,
        verified_at TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_sync_hash ON sync_records(fast_hash);
    """)

    # Column migration: ensure excluded_paths, volume_uuid, and alternate_paths exist in sources
    cursor.execute("PRAGMA table_info(sources)")
    cols = [r["name"] for r in cursor.fetchall()]
    if "excluded_paths" not in cols:
        cursor.execute("ALTER TABLE sources ADD COLUMN excluded_paths TEXT DEFAULT '[]'")
    if "volume_uuid" not in cols:
        cursor.execute("ALTER TABLE sources ADD COLUMN volume_uuid TEXT")
    if "alternate_paths" not in cols:
        cursor.execute("ALTER TABLE sources ADD COLUMN alternate_paths TEXT DEFAULT '[]'")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_volume_uuid ON sources(volume_uuid)")

    conn.commit()

init_db()
