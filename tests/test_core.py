"""Core unit tests for AutoClipShareAuto (config, database, watcher, worker)."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import ConfigManager
from src.database import ClipDatabase
from src.watcher import ClipWatcher
from src.worker import UploadWorker


class _DummyResult:
    def __init__(self, platform: str, success: bool = True, public_download_url: str = "") -> None:
        self.success = success
        self.platform = platform
        self.url = f"https://example.com/{platform}/test"
        self.remote_id = f"id_{platform}"
        self.message = "ok"
        self.dry_run = True
        self.public_download_url = public_download_url


class _DummyUploader:
    def __init__(self, platform: str) -> None:
        self.platform_name = platform
        self.calls: list[dict] = []

    def is_configured(self) -> bool:
        return True

    def test_connection(self) -> tuple[bool, str]:
        return True, "ok"

    def upload(self, file_path: str, title: str, description: str, hashtags: str, **kwargs):
        self.calls.append(
            {
                "file_path": file_path,
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "kwargs": kwargs,
            }
        )
        pub = "https://drive.google.com/uc?export=download&id=dummy" if self.platform_name == "gdrive" else ""
        return _DummyResult(self.platform_name, success=True, public_download_url=pub)


class TestAutoClipCore(unittest.TestCase):
    def test_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            cm = ConfigManager(cfg_path)
            self.assertTrue(cm.config.stream_safe_mode)
            self.assertTrue(cm.config.dry_run)

            cm.update(watch_folder=tmp, drive_folder_name="MyKickClips")
            cm2 = ConfigManager(cfg_path)
            self.assertEqual(cm2.config.watch_folder, tmp)
            self.assertEqual(cm2.config.drive_folder_name, "MyKickClips")

    def test_database_and_stream_safe_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            db_path = Path(tmp) / "clips.db"
            clip_file = Path(tmp) / "kick_clutch.mp4"
            clip_file.write_bytes(b"0" * 1024)

            cm = ConfigManager(cfg_path)
            db = ClipDatabase(db_path)

            dummies = {
                "gdrive": _DummyUploader("gdrive"),
                "youtube": _DummyUploader("youtube"),
                "instagram": _DummyUploader("instagram"),
                "tiktok": _DummyUploader("tiktok"),
            }

            with patch("src.worker.create_uploaders", return_value=dummies):
                worker = UploadWorker(cm, db)
                worker.start()
                try:
                    # Stream-safe mode ON -> should queue only, not upload automatically
                    rec = worker.handle_new_clip(str(clip_file))
                    self.assertIsNotNone(rec)
                    time.sleep(0.2)
                    self.assertEqual(len(dummies["youtube"].calls), 0)

                    # Now trigger post-stream batch upload
                    enqueued = worker.process_all_pending()
                    self.assertEqual(enqueued, 1)

                    deadline = time.time() + 5.0
                    while worker.is_busy and time.time() < deadline:
                        time.sleep(0.05)

                    updated = db.get_clip(rec.id)
                    self.assertEqual(updated.status_gdrive, "done")
                    self.assertEqual(updated.status_youtube, "done")
                    self.assertEqual(updated.status_instagram, "done")
                    self.assertEqual(updated.status_tiktok, "done")

                    # Verify Instagram received Drive public_video_url
                    ig_call = dummies["instagram"].calls[0]
                    self.assertIn("drive.google.com", ig_call["kwargs"].get("public_video_url", ""))
                finally:
                    worker.stop()

    def test_watcher_handles_missing_folder_gracefully(self) -> None:
        watcher = ClipWatcher("", lambda p: None)
        self.assertFalse(watcher.start())
        self.assertFalse(watcher.is_running)


if __name__ == "__main__":
    unittest.main()
