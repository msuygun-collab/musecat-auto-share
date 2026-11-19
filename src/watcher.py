"""Folder watcher with file-write stability detection for new video clips."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

DEFAULT_VIDEO_EXTENSIONS: tuple[str, ...] = (".mp4", ".mov", ".mkv")
POLL_INTERVAL_SECONDS: float = 0.5
MAX_WAIT_SECONDS: float = 120.0


class _ClipEventHandler(FileSystemEventHandler):
    """Watchdog event handler that forwards matching video files to ClipWatcher."""

    def __init__(self, watcher: ClipWatcher) -> None:
        super().__init__()
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher._handle_candidate(str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            dest_path = getattr(event, "dest_path", "")
            if dest_path:
                self._watcher._handle_candidate(str(dest_path))


class ClipWatcher:
    """Watches a directory for newly created or moved video clips and waits until stable."""

    def __init__(
        self,
        watch_folder: str,
        on_new_clip: Callable[[str], None],
        extensions: list[str] | None = None,
        stability_seconds: float = 2.0,
    ) -> None:
        self.watch_folder: str = watch_folder or ""
        self.on_new_clip: Callable[[str], None] = on_new_clip
        raw_exts = extensions if extensions is not None else list(DEFAULT_VIDEO_EXTENSIONS)
        self.extensions: frozenset[str] = frozenset(
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in raw_exts
            if ext.strip()
        )
        self.stability_seconds: float = max(0.0, float(stability_seconds))

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._in_flight: set[str] = set()
        self._observer: Observer | None = None

    @property
    def is_running(self) -> bool:
        """Return True if the underlying watchdog observer is active."""
        with self._lock:
            return self._observer is not None and self._observer.is_alive()

    def start(self) -> bool:
        """Start watching the configured folder. Returns False if folder is invalid."""
        with self._lock:
            if self._observer is not None and self._observer.is_alive():
                return True

            folder = self.watch_folder.strip()
            if not folder:
                logger.info("Watch folder is not configured; ClipWatcher not started.")
                return False

            folder_path = Path(folder)
            if not folder_path.exists() or not folder_path.is_dir():
                logger.warning("Watch folder does not exist or is not a directory: %s", folder)
                return False

            self._stop_event.clear()
            observer = Observer()
            handler = _ClipEventHandler(self)
            try:
                observer.schedule(handler, str(folder_path), recursive=True)
                observer.start()
            except Exception as exc:
                logger.error("Failed to start ClipWatcher on '%s': %s", folder, exc)
                return False

            self._observer = observer
            logger.info("ClipWatcher started on: %s", folder_path)
            return True

    def stop(self) -> None:
        """Stop watching and cancel pending stability checks."""
        self._stop_event.set()
        with self._lock:
            observer = self._observer
            self._observer = None

        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=5.0)
            except Exception as exc:
                logger.warning("Error while stopping ClipWatcher observer: %s", exc)
            logger.info("ClipWatcher stopped.")

    def update_folder(self, new_folder: str) -> bool:
        """Switch the watched directory and restart the observer."""
        self.stop()
        self.watch_folder = new_folder or ""
        return self.start()

    def _is_matching_video(self, file_path: str) -> bool:
        ext = Path(file_path).suffix.lower()
        return bool(ext) and ext in self.extensions

    def _handle_candidate(self, file_path: str) -> None:
        if not self._is_matching_video(file_path):
            return

        norm_key = os.path.normcase(os.path.normpath(file_path))
        with self._lock:
            if norm_key in self._in_flight:
                return
            self._in_flight.add(norm_key)

        thread = threading.Thread(
            target=self._wait_for_stability,
            args=(os.path.normpath(file_path), norm_key),
            name=f"ClipStability-{Path(file_path).name}",
            daemon=True,
        )
        thread.start()

    def _wait_for_stability(self, file_path: str, norm_key: str) -> None:
        start_time = time.monotonic()
        last_size: int = -1
        stable_since: float | None = None

        try:
            while not self._stop_event.is_set():
                elapsed = time.monotonic() - start_time
                if elapsed > MAX_WAIT_SECONDS:
                    logger.warning(
                        "Timed out waiting for clip to stabilize after %.0fs: %s",
                        MAX_WAIT_SECONDS,
                        file_path,
                    )
                    return

                if not os.path.exists(file_path):
                    return

                try:
                    current_size = os.path.getsize(file_path)
                except OSError:
                    stable_since = None
                    self._stop_event.wait(POLL_INTERVAL_SECONDS)
                    continue

                now = time.monotonic()
                if current_size > 0 and current_size == last_size:
                    if stable_since is None:
                        stable_since = now
                    if (now - stable_since) >= self.stability_seconds:
                        if self._can_read_file(file_path):
                            logger.info("Clip stabilized (%d bytes): %s", current_size, file_path)
                            try:
                                self.on_new_clip(file_path)
                            except Exception as exc:
                                logger.exception("Error in on_new_clip callback for '%s': %s", file_path, exc)
                            return
                else:
                    last_size = current_size
                    stable_since = now if current_size > 0 else None

                self._stop_event.wait(POLL_INTERVAL_SECONDS)
        finally:
            with self._lock:
                self._in_flight.discard(norm_key)

    @staticmethod
    def _can_read_file(file_path: str) -> bool:
        try:
            with open(file_path, "rb") as handle:
                handle.read(1)
            return True
        except (PermissionError, OSError):
            return False
