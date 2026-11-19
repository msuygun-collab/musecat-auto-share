"""Silent, non-intrusive system tray manager for AutoClipShareAuto."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from src.i18n import tr

logger = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image, ImageDraw

    _TRAY_AVAILABLE = True
except Exception:  # pragma: no cover - graceful fallback when optional deps missing
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    _TRAY_AVAILABLE = False


def create_tray_icon_image(size: int = 64) -> Optional["Image.Image"]:
    """Load the MuseCat logo if present, otherwise generate a sleek dark-purple/cyan icon."""
    if Image is None:
        return None

    from src.config import RESOURCE_ROOT

    assets_dir = RESOURCE_ROOT / "assets"
    for candidate in (assets_dir / "musecat_icon_1024.png", assets_dir / "musecat_source.webp"):
        if candidate.is_file():
            try:
                with Image.open(candidate) as logo:
                    return logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            except Exception as exc:
                logger.debug("Özel tray ikonu yüklenemedi (%s): %s", candidate, exc)

    if ImageDraw is None:
        return None

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark purple rounded badge background
    pad = 2
    radius = int(size * 0.24)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(24, 18, 43, 255),
        outline=(139, 92, 246, 255),
        width=3,
    )

    # Inner cyan accent arc / glow ring
    inner_pad = int(size * 0.16)
    draw.ellipse(
        [inner_pad, inner_pad, size - inner_pad, size - inner_pad],
        outline=(34, 211, 238, 190),
        width=2,
    )

    # Crisp cyan play / clip triangle in center
    cx = size * 0.52
    cy = size * 0.50
    tri_r = size * 0.20
    triangle = [
        (cx - tri_r * 0.72, cy - tri_r * 0.90),
        (cx - tri_r * 0.72, cy + tri_r * 0.90),
        (cx + tri_r * 1.00, cy),
    ]
    draw.polygon(triangle, fill=(34, 211, 238, 255))

    # Small purple dot indicator at top-right (live/clip accent)
    dot_r = max(3, int(size * 0.08))
    dx = int(size * 0.76)
    dy = int(size * 0.24)
    draw.ellipse(
        [dx - dot_r, dy - dot_r, dx + dot_r, dy + dot_r],
        fill=(192, 132, 252, 255),
    )

    return img


class TrayManager:
    """Manages the Windows system tray icon and silent notifications."""

    def __init__(
        self,
        on_open_panel: Callable[[], None],
        on_toggle_stream_mode: Callable[[], None],
        on_share_queue_now: Callable[[], None],
        on_quit: Callable[[], None],
        get_stream_mode: Optional[Callable[[], bool]] = None,
        get_language: Optional[Callable[[], str]] = None,
    ) -> None:
        self._on_open_panel = on_open_panel
        self._on_toggle_stream_mode = on_toggle_stream_mode
        self._on_share_queue_now = on_share_queue_now
        self._on_quit = on_quit
        self._get_stream_mode = get_stream_mode
        self._get_language = get_language

        self._icon: Optional["pystray.Icon"] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def _current_lang(self) -> str:
        if self._get_language is None:
            return "tr"
        try:
            return str(self._get_language() or "tr")
        except Exception:
            return "tr"

    @property
    def is_available(self) -> bool:
        """Return True if pystray and Pillow are available."""
        return _TRAY_AVAILABLE

    @property
    def is_running(self) -> bool:
        """Return True if the system tray icon is currently active."""
        return self._running and self._icon is not None

    def _safe_call(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:
            logger.exception("Tray menu callback error: %s", exc)

    def _build_menu(self) -> "pystray.Menu":
        stream_checked = (
            (lambda _item: bool(self._get_stream_mode()))
            if self._get_stream_mode is not None
            else None
        )
        return pystray.Menu(
            pystray.MenuItem(
                lambda _item: tr("tray_open_panel", self._current_lang()),
                lambda icon, item: self._safe_call(self._on_open_panel),
                default=True,
            ),
            pystray.MenuItem(
                lambda _item: tr("tray_stream_mode", self._current_lang()),
                lambda icon, item: self._safe_call(self._on_toggle_stream_mode),
                checked=stream_checked,
            ),
            pystray.MenuItem(
                lambda _item: tr("tray_share_queue", self._current_lang()),
                lambda icon, item: self._safe_call(self._on_share_queue_now),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _item: tr("tray_quit", self._current_lang()),
                lambda icon, item: self._safe_call(self._on_quit),
            ),
        )

    def start(self) -> bool:
        """Start the system tray icon in a background daemon thread."""
        if not _TRAY_AVAILABLE:
            logger.warning("pystray veya Pillow kurulu değil; sistem tepsisi devre dışı.")
            return False

        if self._running:
            return True

        image = create_tray_icon_image(64)
        if image is None:
            return False

        self._icon = pystray.Icon(
            name="MuseCatAutoShare",
            icon=image,
            title=tr("app_title", self._current_lang()),
            menu=self._build_menu(),
        )
        self._running = True

        def _run_tray() -> None:
            try:
                if self._icon is not None:
                    self._icon.run()
            except Exception as exc:
                logger.exception("Sistem tepsisi çalıştırılırken hata: %s", exc)
            finally:
                self._running = False

        self._thread = threading.Thread(target=_run_tray, name="SystemTrayThread", daemon=True)
        self._thread.start()
        return True

    def update_menu(self) -> None:
        """Refresh tray menu state (e.g. after toggling Stream-Safe mode or language)."""
        if self._icon is not None and self._running:
            try:
                self._icon.title = tr("app_title", self._current_lang())
                self._icon.update_menu()
            except Exception as exc:
                logger.debug("Tray menu update failed: %s", exc)

    def notify(self, title: str, message: str) -> None:
        """Send a silent, non-intrusive system tray notification."""
        if not self._running or self._icon is None:
            logger.info("[Bildirim] %s: %s", title, message)
            return
        try:
            # pystray signature: notify(message, title=None)
            self._icon.notify(message, title)
        except Exception as exc:
            logger.debug("Tray notification skipped: %s", exc)

    def stop(self) -> None:
        """Stop and remove the system tray icon cleanly."""
        self._running = False
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception as exc:
                logger.debug("Tray stop error: %s", exc)
            finally:
                self._icon = None
