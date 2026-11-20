"""Sequential background upload worker with stream-safe queueing."""

from __future__ import annotations

import inspect
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

from src.config import ConfigManager
from src.database import VALID_PLATFORMS, ClipDatabase, ClipRecord
from src.uploaders import create_uploaders

logger = logging.getLogger(__name__)

# Canonical execution order: Google Drive always runs first so its public
# download URL can be passed to Instagram Reels if needed.
PLATFORM_EXECUTION_ORDER: tuple[str, ...] = ("gdrive", "youtube", "instagram", "tiktok")


@dataclass(frozen=True)
class _UploadJob:
    clip_id: int
    platforms: tuple[str, ...] | None = None


class UploadWorker:
    """Processes clip uploads sequentially on a background daemon thread."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db: ClipDatabase,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.config_manager: ConfigManager = config_manager
        self.db: ClipDatabase = db
        self.on_event: Callable[[str, dict[str, Any]], None] | None = on_event

        self._queue: queue.Queue[_UploadJob | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._active_job: bool = False

    @property
    def is_busy(self) -> bool:
        """Return True if a job is currently running or queued."""
        with self._state_lock:
            return self._active_job or not self._queue.empty()

    def start(self) -> None:
        """Start the background worker thread if not already running."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="UploadWorker",
                daemon=True,
            )
            self._thread.start()
            logger.info("UploadWorker started.")

    def stop(self) -> None:
        """Signal the worker thread to stop and wait briefly for exit."""
        self._stop_event.set()
        self._queue.put(None)
        with self._state_lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        logger.info("UploadWorker stopped.")

    def handle_new_clip(self, file_path: str) -> ClipRecord | None:
        """Register a newly discovered clip and auto-enqueue only when not in stream-safe mode."""
        if self.db.exists_by_path(file_path):
            logger.debug("Clip already exists in database; skipping: %s", file_path)
            return None

        cfg = self.config_manager.config
        clip = self.db.add_clip(
            file_path=file_path,
            hashtags=cfg.default_hashtags,
            enabled_platforms=cfg.enabled_platforms,
        )
        self._emit(
            "clip_added",
            {
                "clip_id": clip.id,
                "file_path": clip.file_path,
                "file_name": clip.file_name,
                "title": clip.title,
                "stream_safe_mode": cfg.stream_safe_mode,
            },
        )

        if not cfg.stream_safe_mode:
            if bool(getattr(cfg, "require_approval_before_social", True)):
                # Başlıksız/onaysız sosyal medyaya atma: yalnızca Google Drive'a otomatik yedekle,
                # YouTube/Instagram/TikTok için kullanıcının başlık yazıp onaylamasını bekle.
                if bool((cfg.enabled_platforms or {}).get("gdrive", True)):
                    self.process_clip_now(clip.id, platforms=["gdrive"])
            else:
                self.process_clip_now(clip.id)

        return clip

    def process_clip_now(self, clip_id: int, platforms: list[str] | None = None) -> None:
        """Enqueue a specific clip for immediate sequential upload."""
        normalized: tuple[str, ...] | None = None
        if platforms is not None:
            normalized = tuple(p for p in PLATFORM_EXECUTION_ORDER if p in platforms)
            if not normalized:
                return
        self._queue.put(_UploadJob(clip_id=clip_id, platforms=normalized))

    def process_all_pending(self, platforms: list[str] | None = None) -> int:
        """Enqueue all clips that have at least one pending platform. Returns enqueued count."""
        pending_clips = self.db.get_pending_clips()
        count = 0
        for clip in pending_clips:
            if platforms is not None:
                has_matching_pending = any(
                    getattr(clip, f"status_{p}", "") == "pending"
                    for p in platforms
                    if p in VALID_PLATFORMS
                )
                if not has_matching_pending:
                    continue
            self.process_clip_now(clip.id, platforms=platforms)
            count += 1
        return count

    def backup_all_to_drive(self) -> int:
        """Enqueue all clips whose Google Drive status is pending, error, or skipped."""
        all_clips = self.db.list_clips(limit=10000)
        count = 0
        for clip in reversed(all_clips):
            if clip.status_gdrive in ("pending", "error", "skipped"):
                self.process_clip_now(clip.id, platforms=["gdrive"])
                count += 1
        return count

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if job is None:
                self._queue.task_done()
                break

            with self._state_lock:
                self._active_job = True

            try:
                self._execute_job(job)
            except Exception as exc:
                logger.exception("Unexpected error processing upload job for clip %s: %s", job.clip_id, exc)
            finally:
                self._queue.task_done()
                with self._state_lock:
                    self._active_job = False
                if self._queue.empty() and not self._stop_event.is_set():
                    self._emit("queue_idle", {})
                elif not self._queue.empty() and not self._stop_event.is_set():
                    # Anti-Spam Koruması: Toplu yüklemelerde arka arkaya saniyesinde gönderip
                    # Instagram/TikTok/YouTube spam filtresine takılmamak için güvenli bekleme uygula.
                    cfg = self.config_manager.config
                    cooldown = int(getattr(cfg, "anti_spam_delay_seconds", 180) or 0)
                    if not cfg.dry_run and cooldown > 0:
                        logger.info(
                            "Anti-Spam Koruması: Sonraki klip öncesi %d saniye bekleniyor...",
                            cooldown,
                        )
                        self._emit("anti_spam_wait", {"seconds": cooldown})
                        self._stop_event.wait(timeout=cooldown)

    def _execute_job(self, job: _UploadJob) -> None:
        clip = self.db.get_clip(job.clip_id)
        if clip is None:
            logger.warning("Clip ID %s no longer exists; skipping job.", job.clip_id)
            return

        target_platforms = self._resolve_target_platforms(clip, job.platforms)
        if not target_platforms:
            return

        uploaders = create_uploaders(self.config_manager.config)
        drive_public_url: str = ""

        # MuseCat Pro: Otomatik altyazılı sürüm varsa (veya otomatik altyazı açıksa) sosyal medyaya onu yükle
        social_video_path = clip.file_path
        cfg = self.config_manager.config
        has_social_target = any(p in target_platforms for p in ("youtube", "instagram", "tiktok"))
        if has_social_target and not cfg.dry_run:
            from pathlib import Path as _Path
            from src.captions import CAPTION_OUTPUT_DIR, CaptionEngine

            existing_captioned = CAPTION_OUTPUT_DIR / f"{_Path(clip.file_path).stem}_subtitled.mp4"
            if existing_captioned.is_file():
                social_video_path = str(existing_captioned)
            elif (
                bool(getattr(cfg, "auto_caption_enabled", False))
                and (getattr(cfg, "license_status", "free") or "").lower() == "pro"
            ):
                self._emit("caption_started", {"clip_id": clip.id, "file_name": clip.file_name})
                ok_cap, cap_path, cap_msg = CaptionEngine(cfg).generate_captioned_video(clip.file_path)
                if ok_cap and cap_path:
                    social_video_path = cap_path
                    logger.info("Otomatik altyazı eklendi: %s", cap_msg)
                else:
                    logger.warning("Otomatik altyazı atlandı (%s), orijinal video yüklenecek.", cap_msg)

        # Klip daha önce Google Drive'a başarıyla yedeklendiyse tekrar yükleme (çift kopyayı önle).
        # Instagram Reels için mevcut Drive dosyasının linkini yeniden kullan.
        gdrive_uploader = uploaders.get("gdrive")
        existing_drive_id = ""
        if (
            clip.status_gdrive == "done"
            and clip.url_gdrive
            and gdrive_uploader is not None
            and hasattr(gdrive_uploader, "extract_file_id_from_url")
        ):
            existing_drive_id = gdrive_uploader.extract_file_id_from_url(clip.url_gdrive)

        if existing_drive_id:
            if "gdrive" in target_platforms:
                logger.info(
                    "Klip %s zaten Google Drive'da yedekli (%s); çift yükleme atlandı.",
                    clip.id,
                    existing_drive_id,
                )
                target_platforms = [p for p in target_platforms if p != "gdrive"]
            if (
                "instagram" in target_platforms
                and self.config_manager.config.instagram_public_url_mode == "gdrive"
                and hasattr(gdrive_uploader, "ensure_public_download_url")
            ):
                drive_public_url = gdrive_uploader.ensure_public_download_url(existing_drive_id)

        for platform in target_platforms:
            if self._stop_event.is_set():
                break

            uploader = uploaders.get(platform)
            if uploader is None:
                err_msg = f"No uploader registered for platform '{platform}'."
                self.db.set_platform_status(clip.id, platform, "error", error=err_msg)
                self._emit(
                    "upload_finished",
                    {
                        "clip_id": clip.id,
                        "platform": platform,
                        "status": "error",
                        "url": "",
                        "error": err_msg,
                        "file_name": clip.file_name,
                    },
                )
                continue

            self.db.set_platform_status(clip.id, platform, "uploading")
            self._emit(
                "upload_started",
                {
                    "clip_id": clip.id,
                    "platform": platform,
                    "file_name": clip.file_name,
                    "title": clip.title,
                },
            )

            extra_kwargs: dict[str, Any] = {}
            if (
                platform == "gdrive"
                and "instagram" in target_platforms
                and self.config_manager.config.instagram_public_url_mode == "gdrive"
            ):
                extra_kwargs["make_public_for_instagram"] = True
            elif platform == "instagram":
                extra_kwargs["public_video_url"] = drive_public_url

            try:
                effective_clip = clip
                if platform in ("youtube", "instagram", "tiktok") and social_video_path != clip.file_path:
                    from dataclasses import replace

                    effective_clip = replace(clip, file_path=social_video_path)
                result = self._invoke_uploader(uploader, effective_clip, extra_kwargs)
                success = bool(getattr(result, "success", False))
                url = str(getattr(result, "url", "") or getattr(result, "share_url", "") or "")
                error = str(getattr(result, "error", "") or getattr(result, "message", "") or "")

                if success:
                    if platform == "gdrive":
                        drive_public_url = str(getattr(result, "public_download_url", "") or "")
                    self.db.set_platform_status(clip.id, platform, "done", url=url, error="")
                    self._emit(
                        "upload_finished",
                        {
                            "clip_id": clip.id,
                            "platform": platform,
                            "status": "done",
                            "url": url,
                            "error": "",
                            "file_name": clip.file_name,
                        },
                    )
                else:
                    err_msg = error or f"{platform} upload failed."
                    self.db.set_platform_status(clip.id, platform, "error", error=err_msg)
                    self._emit(
                        "upload_finished",
                        {
                            "clip_id": clip.id,
                            "platform": platform,
                            "status": "error",
                            "url": "",
                            "error": err_msg,
                            "file_name": clip.file_name,
                        },
                    )
            except Exception as exc:
                err_msg = str(exc) or f"{platform} upload raised an exception."
                logger.exception("Upload failed for clip %s on %s: %s", clip.id, platform, exc)
                self.db.set_platform_status(clip.id, platform, "error", error=err_msg)
                self._emit(
                    "upload_finished",
                    {
                        "clip_id": clip.id,
                        "platform": platform,
                        "status": "error",
                        "url": "",
                        "error": err_msg,
                        "file_name": clip.file_name,
                    },
                )

    @staticmethod
    def _resolve_target_platforms(
        clip: ClipRecord,
        requested: tuple[str, ...] | None,
    ) -> list[str]:
        """Return target platforms in canonical order with 'gdrive' always first."""
        if requested is not None:
            requested_set = set(requested)
            return [p for p in PLATFORM_EXECUTION_ORDER if p in requested_set]

        return [
            p
            for p in PLATFORM_EXECUTION_ORDER
            if getattr(clip, f"status_{p}", "") == "pending"
        ]

    @staticmethod
    def _invoke_uploader(
        uploader: Any,
        clip: ClipRecord,
        extra_kwargs: dict[str, Any],
    ) -> Any:
        """Call uploader.upload matching either (clip, **kwargs) or (file_path, title, ...)."""
        sig = inspect.signature(uploader.upload)
        params = list(sig.parameters.keys())
        if params and params[0] in ("clip", "record", "clip_record"):
            return uploader.upload(clip, **extra_kwargs)

        return uploader.upload(
            file_path=clip.file_path,
            title=clip.title,
            description=clip.description,
            hashtags=clip.hashtags,
            **extra_kwargs,
        )

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event_name, payload)
        except Exception as exc:
            logger.exception("Error in UploadWorker on_event handler for '%s': %s", event_name, exc)
