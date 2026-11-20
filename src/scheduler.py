"""Background Smart Scheduler for MuseCat Pro — spreads clip uploads over time."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from src.config import ConfigManager
from src.database import ClipDatabase
from src.license_manager import LicenseManager
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

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if (
                    self.license_manager.is_pro
                    and bool(getattr(self.config_manager.config, "scheduler_enabled", False))
                    and not self.worker.is_busy
                ):
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
                        # Clear scheduled_at first so it isn't dispatched twice
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
            except Exception as exc:
                logger.exception("ClipScheduler döngü hatası: %s", exc)

            self._stop_event.wait(timeout=self.poll_interval_seconds)
