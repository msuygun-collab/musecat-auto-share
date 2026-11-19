"""Thread-safe SQLite database layer for clip records and upload statuses."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

VALID_PLATFORMS: tuple[str, ...] = ("youtube", "instagram", "tiktok", "gdrive")


@dataclass
class ClipRecord:
    """Represents a single video clip and its per-platform upload status."""

    id: int
    file_path: str
    file_name: str
    title: str
    description: str
    hashtags: str
    created_at: str
    file_size_mb: float
    status_youtube: str
    status_instagram: str
    status_tiktok: str
    status_gdrive: str
    url_youtube: str
    url_instagram: str
    url_tiktok: str
    url_gdrive: str
    last_error: str


def _row_to_clip(row: sqlite3.Row) -> ClipRecord:
    return ClipRecord(
        id=int(row["id"]),
        file_path=str(row["file_path"]),
        file_name=str(row["file_name"]),
        title=str(row["title"]),
        description=str(row["description"]),
        hashtags=str(row["hashtags"]),
        created_at=str(row["created_at"]),
        file_size_mb=float(row["file_size_mb"]),
        status_youtube=str(row["status_youtube"]),
        status_instagram=str(row["status_instagram"]),
        status_tiktok=str(row["status_tiktok"]),
        status_gdrive=str(row["status_gdrive"]),
        url_youtube=str(row["url_youtube"]),
        url_instagram=str(row["url_instagram"]),
        url_tiktok=str(row["url_tiktok"]),
        url_gdrive=str(row["url_gdrive"]),
        last_error=str(row["last_error"]),
    )


def _normalize_path(file_path: str) -> str:
    return os.path.normpath(str(file_path))


def _safe_file_size_mb(file_path: str) -> float:
    try:
        size_bytes = os.path.getsize(file_path)
        return round(size_bytes / (1024 * 1024), 2)
    except OSError:
        return 0.0


class ClipDatabase:
    """Thread-safe SQLite wrapper for managing clips and multi-platform statuses."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.db_path: Path = Path(db_path) if db_path is not None else DATA_DIR / "clips.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    hashtags TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    file_size_mb REAL NOT NULL DEFAULT 0.0,
                    status_youtube TEXT NOT NULL DEFAULT 'pending',
                    status_instagram TEXT NOT NULL DEFAULT 'pending',
                    status_tiktok TEXT NOT NULL DEFAULT 'pending',
                    status_gdrive TEXT NOT NULL DEFAULT 'pending',
                    url_youtube TEXT NOT NULL DEFAULT '',
                    url_instagram TEXT NOT NULL DEFAULT '',
                    url_tiktok TEXT NOT NULL DEFAULT '',
                    url_gdrive TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_clips_file_path ON clips (file_path);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_clips_status_gdrive ON clips (status_gdrive);"
            )

    def add_clip(
        self,
        file_path: str,
        title: str = "",
        description: str = "",
        hashtags: str = "",
        enabled_platforms: dict[str, bool] | None = None,
    ) -> ClipRecord:
        """Insert a new clip record and return it."""
        norm_path = _normalize_path(file_path)
        path_obj = Path(norm_path)
        file_name = path_obj.name
        resolved_title = title.strip() if title and title.strip() else path_obj.stem
        file_size_mb = _safe_file_size_mb(norm_path)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        statuses: dict[str, str] = {}
        for platform in VALID_PLATFORMS:
            if enabled_platforms is None:
                statuses[platform] = "pending"
            else:
                statuses[platform] = "pending" if enabled_platforms.get(platform, False) else "skipped"

        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO clips (
                    file_path, file_name, title, description, hashtags,
                    created_at, file_size_mb,
                    status_youtube, status_instagram, status_tiktok, status_gdrive,
                    url_youtube, url_instagram, url_tiktok, url_gdrive,
                    last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', '')
                """,
                (
                    norm_path,
                    file_name,
                    resolved_title,
                    description or "",
                    hashtags or "",
                    created_at,
                    file_size_mb,
                    statuses["youtube"],
                    statuses["instagram"],
                    statuses["tiktok"],
                    statuses["gdrive"],
                ),
            )
            clip_id = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
            return _row_to_clip(row)

    def exists_by_path(self, file_path: str) -> bool:
        """Return True if a clip with the given file path already exists."""
        norm_path = _normalize_path(file_path)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM clips WHERE file_path = ? LIMIT 1",
                (norm_path,),
            ).fetchone()
            return row is not None

    def get_clip(self, clip_id: int) -> ClipRecord | None:
        """Fetch a single clip by ID, or None if not found."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
            return _row_to_clip(row) if row is not None else None

    def list_clips(self, limit: int = 200) -> list[ClipRecord]:
        """Return clips ordered newest first."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM clips ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_row_to_clip(row) for row in rows]

    def get_pending_clips(self) -> list[ClipRecord]:
        """Return all clips where at least one platform has status 'pending'."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM clips
                WHERE status_youtube = 'pending'
                   OR status_instagram = 'pending'
                   OR status_tiktok = 'pending'
                   OR status_gdrive = 'pending'
                ORDER BY id ASC
                """
            ).fetchall()
            return [_row_to_clip(row) for row in rows]

    def update_clip_metadata(
        self,
        clip_id: int,
        title: str,
        description: str,
        hashtags: str,
    ) -> None:
        """Update editable metadata fields for a clip."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE clips
                SET title = ?, description = ?, hashtags = ?
                WHERE id = ?
                """,
                (title, description, hashtags, clip_id),
            )

    def set_platform_status(
        self,
        clip_id: int,
        platform: str,
        status: str,
        url: str = "",
        error: str = "",
    ) -> None:
        """Update status (and optionally URL / error) for a specific platform on a clip."""
        if platform not in VALID_PLATFORMS:
            raise ValueError(f"Unsupported platform '{platform}'. Expected one of {VALID_PLATFORMS}.")

        status_col = f"status_{platform}"
        url_col = f"url_{platform}"

        with self._lock, self._connect() as conn:
            if url:
                conn.execute(
                    f"UPDATE clips SET {status_col} = ?, {url_col} = ?, last_error = ? WHERE id = ?",
                    (status, url, error, clip_id),
                )
            elif error:
                conn.execute(
                    f"UPDATE clips SET {status_col} = ?, last_error = ? WHERE id = ?",
                    (status, error, clip_id),
                )
            elif status == "done":
                conn.execute(
                    f"UPDATE clips SET {status_col} = ?, last_error = '' WHERE id = ?",
                    (status, clip_id),
                )
            else:
                conn.execute(
                    f"UPDATE clips SET {status_col} = ? WHERE id = ?",
                    (status, clip_id),
                )

    def reset_failed_to_pending(self, clip_id: int) -> None:
        """Reset any 'error' platform statuses on a clip back to 'pending'."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE clips
                SET status_youtube = CASE WHEN status_youtube = 'error' THEN 'pending' ELSE status_youtube END,
                    status_instagram = CASE WHEN status_instagram = 'error' THEN 'pending' ELSE status_instagram END,
                    status_tiktok = CASE WHEN status_tiktok = 'error' THEN 'pending' ELSE status_tiktok END,
                    status_gdrive = CASE WHEN status_gdrive = 'error' THEN 'pending' ELSE status_gdrive END,
                    last_error = ''
                WHERE id = ?
                """,
                (clip_id,),
            )

    def delete_clip(self, clip_id: int) -> None:
        """Delete a clip record from the database."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))

    def clear_completed_clips(self) -> int:
        """Remove all clips that have no pending or uploading platforms. Returns removed count."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM clips
                WHERE status_youtube NOT IN ('pending', 'uploading')
                  AND status_instagram NOT IN ('pending', 'uploading')
                  AND status_tiktok NOT IN ('pending', 'uploading')
                  AND status_gdrive NOT IN ('pending', 'uploading')
                """
            )
            return int(cur.rowcount or 0)

    def prune_missing_files(self) -> int:
        """Remove clips whose source video file no longer exists on disk. Returns removed count."""
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT id, file_path FROM clips").fetchall()
            missing_ids = [
                int(row["id"])
                for row in rows
                if row["file_path"] and not Path(str(row["file_path"])).is_file()
            ]
            if not missing_ids:
                return 0
            placeholders = ",".join("?" for _ in missing_ids)
            cur = conn.execute(f"DELETE FROM clips WHERE id IN ({placeholders})", missing_ids)
            return int(cur.rowcount or 0)

    def get_drive_backups(self, limit: int = 200) -> list[ClipRecord]:
        """Return clips that have been backed up to Google Drive, newest first."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM clips
                WHERE status_gdrive = 'done'
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_row_to_clip(row) for row in rows]
