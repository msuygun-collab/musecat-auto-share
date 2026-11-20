"""Entry point for AutoClipShareAuto — stream-safe clip automation for Turkish streamers."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from src.config import DATA_DIR, ConfigManager
from src.database import ClipDatabase
from src.license_manager import LicenseManager
from src.scheduler import ClipScheduler
from src.ui.app import AutoClipApp
from src.ui.tray import TrayManager
from src.watcher import ClipWatcher
from src.worker import UploadWorker

LOG_DIR = DATA_DIR


def setup_logging() -> None:
    """Configure console + file logging under data/app.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "app.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="AutoClipShareAuto",
        description="OBS Aitum Vertical klip izleyici ve çoklu platform paylaşım otomasyonu.",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Uygulamayı pencere açmadan doğrudan sistem tepsisinde başlatır.",
    )
    return parser.parse_args(argv)


def _set_windows_app_id() -> None:
    """Assign an explicit Windows AppUserModelID so the taskbar uses the MuseCat icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "MuseCat.AutoShare.Desktop.1"
        )
    except Exception:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    _set_windows_app_id()
    setup_logging()
    logger = logging.getLogger("main")
    args = parse_args(argv)

    config_manager = ConfigManager()
    db = ClipDatabase()

    app_ref: dict[str, Optional[AutoClipApp]] = {"app": None}

    def forward_worker_event(*event_args: Any, **event_kwargs: Any) -> None:
        app = app_ref["app"]
        if app is not None:
            app.on_worker_event(*event_args, **event_kwargs)

    worker = UploadWorker(config_manager, db, on_event=forward_worker_event)
    license_manager = LicenseManager(config_manager)
    scheduler = ClipScheduler(
        config_manager,
        db,
        worker,
        license_manager,
        on_event=forward_worker_event,
    )

    cfg = config_manager.config
    extensions = getattr(cfg, "video_extensions", [".mp4", ".mov", ".mkv"])
    stability_seconds = getattr(cfg, "file_stability_seconds", 2.0)

    watcher = ClipWatcher(
        watch_folder=cfg.watch_folder,
        on_new_clip=worker.handle_new_clip,
        extensions=extensions,
        stability_seconds=stability_seconds,
    )

    shutdown_lock = threading.Lock()
    shutdown_done = {"value": False}
    tray_ref: dict[str, Optional[TrayManager]] = {"tray": None}

    def shutdown() -> None:
        with shutdown_lock:
            if shutdown_done["value"]:
                return
            shutdown_done["value"] = True

        logger.info("AutoClipShareAuto kapatılıyor...")
        try:
            scheduler.stop()
        except Exception as exc:
            logger.debug("Scheduler stop error: %s", exc)

        try:
            watcher.stop()
        except Exception as exc:
            logger.debug("Watcher stop error: %s", exc)

        try:
            worker.stop()
        except Exception as exc:
            logger.debug("Worker stop error: %s", exc)

        tray = tray_ref["tray"]
        if tray is not None:
            try:
                tray.stop()
            except Exception as exc:
                logger.debug("Tray stop error: %s", exc)

        app = app_ref["app"]
        if app is not None:
            try:
                app.after(0, app.destroy)
            except Exception:
                try:
                    app.destroy()
                except Exception:
                    pass

    # Start background services
    worker.start()
    scheduler.start()
    if cfg.watch_folder and Path(cfg.watch_folder).is_dir():
        try:
            watcher.start()
        except Exception as exc:
            logger.warning("Klasör izleyici başlatılamadı (%s): %s", cfg.watch_folder, exc)

    # Create UI window
    app = AutoClipApp(
        config_manager=config_manager,
        db=db,
        worker=worker,
        watcher=watcher,
        on_quit=shutdown,
        license_manager=license_manager,
        scheduler=scheduler,
    )
    app_ref["app"] = app

    # Create and start silent system tray
    tray = TrayManager(
        on_open_panel=app.show_window,
        on_toggle_stream_mode=app.toggle_stream_mode_from_tray,
        on_share_queue_now=app.share_queue_from_tray,
        on_quit=shutdown,
        get_stream_mode=lambda: bool(config_manager.config.stream_safe_mode),
        get_language=lambda: str(getattr(config_manager.config, "language", "tr") or "tr"),
    )
    tray_ref["tray"] = tray
    app.set_tray_manager(tray)
    tray_started = tray.start()

    if args.minimized:
        if tray_started:
            app.withdraw()
            logger.info("Uygulama sistem tepsisinde sessiz modda başlatıldı.")
        else:
            logger.warning("--minimized istendi ancak sistem tepsisi başlatılamadı; pencere açılıyor.")

    try:
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("Klavye kesmesi alındı, kapatılıyor...")
    finally:
        shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
