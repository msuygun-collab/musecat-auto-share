"""Background Smart Scheduler for MuseCat Pro — spreads clip uploads over time."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from src.config import DATA_DIR, ConfigManager
from src.database import ClipDatabase
from src.license_manager import LicenseManager
from src.uploaders.google_drive import GoogleDriveUploader
from src.worker import UploadWorker

logger = logging.getLogger(__name__)


class ClipScheduler:
    """Checks for due scheduled clips and dispatches them to UploadWorker."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db: ClipDatabase,
        worker: UploadWorker,
        license_manager: LicenseManager,
        on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
        poll_interval_seconds: float = 20.0,
    ) -> None:
        self.config_manager = config_manager
        self.db = db
        self.worker = worker
        self.license_manager = license_manager
        self.on_event = on_event
        self.poll_interval_seconds = poll_interval_seconds

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ClipScheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("ClipScheduler started.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        logger.info("ClipScheduler stopped.")

    def schedule_all_pending(
        self,
        interval_minutes: int,
        start_delay_minutes: int = 0,
    ) -> int:
        """Assign staggered scheduled_at timestamps to all pending clips."""
        if not self.license_manager.is_pro:
            return 0

        pending = self.db.get_pending_clips()
        if not pending:
            return 0

        interval = max(5, int(interval_minutes))
        base_time = datetime.now() + timedelta(minutes=max(0, int(start_delay_minutes)))

        # Schedule oldest pending clip first
        ordered = list(reversed(pending))
        for idx, clip in enumerate(ordered):
            due_dt = base_time + timedelta(minutes=idx * interval)
            self.db.set_scheduled_at(clip.id, due_dt.strftime("%Y-%m-%d %H:%M:%S"))

        self.config_manager.update(
            scheduler_enabled=True,
            scheduler_interval_minutes=interval,
        )
        self.config_manager.save()
        return len(ordered)

    def clear_all_schedules(self) -> None:
        self.db.clear_all_schedules()
        self.config_manager.update(scheduler_enabled=False)
        self.config_manager.save()

    def pull_next_stock_video_from_drive(self, lang: str = "tr") -> tuple[bool, str]:
        """Pull the oldest video from Google Drive stock folder, queue & publish it, and move to Yayinlandi."""
        if not self.license_manager.is_pro:
            msg = (
                "Google Drive Stok Klasörü yalnızca MuseCat Pro özelliğidir."
                if lang == "tr"
                else "Google Drive Stock Queue is a MuseCat Pro feature."
            )
            return False, msg

        cfg = self.config_manager.config
        folder_name = (getattr(cfg, "drive_stock_folder_name", "") or "MuseCat_Stok_Kuyruk").strip()
        uploader = GoogleDriveUploader(cfg)
        if not uploader.is_configured():
            msg = (
                "Google Drive bağlantısı yapılmamış. Önce Hesaplar & API sekmesinden Google'ı bağlayın."
                if lang == "tr"
                else "Google Drive is not connected. Connect Google in Accounts & API first."
            )
            return False, msg

        try:
            folder_id, videos = uploader.list_stock_videos(folder_name)
        except Exception as exc:  # noqa: BLE001
            msg = (
                f"Drive stok klasörü okunamadı: {exc}"
                if lang == "tr"
                else f"Could not read Drive stock folder: {exc}"
            )
            return False, msg

        if not videos:
            msg = (
                f"'{folder_name}' klasöründe bekleyen stok video bulunamadı."
                if lang == "tr"
                else f"No pending stock videos found in '{folder_name}'."
            )
            return False, msg

        item = videos[0]
        file_id = str(item["id"])
        file_name = str(item["name"])
        web_link = str(item.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view")

        cache_dir = DATA_DIR / "drive_stock_cache"
        local_path = cache_dir / f"{file_id}_{file_name}"
        try:
            if not local_path.is_file():
                uploader.download_stock_video(file_id, local_path)
        except Exception as exc:  # noqa: BLE001
            msg = (
                f"Stok video indirilemedi ({file_name}): {exc}"
                if lang == "tr"
                else f"Failed to download stock video ({file_name}): {exc}"
            )
            return False, msg

        clip = self.db.add_clip(
            file_path=str(local_path),
            title=Path(file_name).stem,
            hashtags=cfg.default_hashtags,
            enabled_platforms=cfg.enabled_platforms,
        )
        # Already on Drive -> mark Drive done with existing link so worker reuses it without duplicating!
        self.db.set_platform_status(clip.id, "gdrive", "done", url=web_link, error="")
        uploader.move_file_to_published(file_id, folder_id, "Yayinlandi")

        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.config_manager.update(drive_stock_last_run=now_iso)
        self.config_manager.save()

        target_platforms = [
            p
            for p in ("youtube", "instagram", "tiktok")
            if bool((cfg.enabled_platforms or {}).get(p, True))
        ]
        if target_platforms:
            self.worker.process_clip_now(clip.id, platforms=target_platforms)

        msg = (
            f"Stok video çekildi ve paylaşım kuyruğuna alındı: {file_name}"
            if lang == "tr"
            else f"Stock video pulled and queued for publishing: {file_name}"
        )
        return True, msg

    def _check_drive_stock_due(self) -> None:
        cfg = self.config_manager.config
        if not bool(getattr(cfg, "drive_stock_sync_enabled", False)):
            return
        interval_min = max(180, int(getattr(cfg, "scheduler_interval_minutes", 180) or 180))
        last_run_str = (getattr(cfg, "drive_stock_last_run", "") or "").strip()
        if last_run_str:
            try:
                last_dt = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - last_dt < timedelta(minutes=interval_min):
                    return
            except ValueError:
                pass
        ok, msg = self.pull_next_stock_video_from_drive(lang=getattr(cfg, "language", "tr"))
        if ok:
            logger.info("Drive stok otomasyonu: %s", msg)
            if self.on_event is not None:
                try:
                    self.on_event("schedule_triggered", {"message": msg})
                except Exception:
                    pass

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if (
                    self.license_manager.is_pro
                    and not self.worker.is_busy
                ):
                    if bool(getattr(self.config_manager.config, "scheduler_enabled", False)):
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        due_clips = self.db.get_due_scheduled_clips(now_str)
                        for clip in due_clips:
                            if self._stop_event.is_set():
                                break
                            logger.info(
                                "Zamanlanan klip paylaşım zamanı geldi: #%s (%s)",
                                clip.id,
                                clip.file_name,
                            )
                            self.db.set_scheduled_at(clip.id, "")
                            self.worker.process_clip_now(clip.id)
                            if self.on_event is not None:
                                try:
                                    self.on_event(
                                        "schedule_triggered",
                                        {"clip_id": clip.id, "file_name": clip.file_name},
                                    )
                                except Exception:
                                    pass
                    self._check_drive_stock_due()
            except Exception as exc:
                logger.exception("ClipScheduler döngü hatası: %s", exc)

            self._stop_event.wait(timeout=self.poll_interval_seconds)
