"""Application configuration dataclass and JSON persistence manager."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IS_FROZEN: bool = bool(getattr(sys, "frozen", False))
APP_ROOT: Path = (
    Path(sys.executable).resolve().parent
    if IS_FROZEN
    else Path(__file__).resolve().parent.parent
)
RESOURCE_ROOT: Path = (
    Path(getattr(sys, "_MEIPASS", APP_ROOT))
    if IS_FROZEN
    else APP_ROOT
)
DATA_DIR: Path = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuseCatAutoShare" / "data"
    if IS_FROZEN
    else APP_ROOT / "data"
)
CREDENTIALS_DIR: Path = DATA_DIR / "credentials"


def _default_enabled_platforms() -> dict[str, bool]:
    return {
        "youtube": True,
        "instagram": True,
        "tiktok": True,
        "twitter": False,
        "gdrive": True,
    }


def _default_video_extensions() -> list[str]:
    return [".mp4", ".mov", ".mkv"]


@dataclass
class AppConfig:
    """Persistent settings for AutoClipShareAuto."""

    watch_folder: str = ""
    language: str = "tr"
    stream_safe_mode: bool = True
    require_approval_before_social: bool = True
    minimize_to_tray_on_close: bool = True
    auto_remove_deleted_files: bool = False
    dry_run: bool = True
    default_hashtags: str = "#shorts #reels #tiktok #kick #gaming"
    auto_backup_drive: bool = True
    drive_folder_name: str = "AutoClipShare_Backups"
    drive_organize_by_date: bool = True
    enabled_platforms: dict[str, bool] = field(default_factory=_default_enabled_platforms)
    google_client_secrets_path: str = field(
        default_factory=lambda: str(CREDENTIALS_DIR / "google_client_secret.json")
    )
    google_token_path: str = field(
        default_factory=lambda: str(CREDENTIALS_DIR / "google_token.json")
    )
    instagram_access_token: str = ""
    instagram_account_id: str = ""
    instagram_public_url_mode: str = "gdrive"  # "gdrive" or "custom_base_url"
    instagram_custom_base_url: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_access_token: str = ""
    tiktok_post_mode: str = "inbox"  # "inbox" or "direct"
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""
    video_extensions: list[str] = field(default_factory=_default_video_extensions)
    file_stability_seconds: float = 2.0
    # MuseCat Pro (Gumroad License + Smart Scheduler)
    license_key: str = ""
    license_status: str = "free"  # "free" or "pro"
    license_email: str = ""
    license_last_verified: str = ""
    gumroad_product_id: str = "aITe8QziVIs_bdYXGB43Aw=="
    gumroad_checkout_url: str = "https://suygun.gumroad.com/l/musecat-pro"
    scheduler_enabled: bool = False
    scheduler_interval_minutes: int = 180
    anti_spam_delay_seconds: int = 180
    drive_stock_folder_name: str = "MuseCat_Stok_Kuyruk"
    drive_stock_sync_enabled: bool = False
    drive_stock_last_run: str = ""
    # MuseCat Pro AI Auto-Captions (Local faster-whisper + Groq Whisper API)
    auto_caption_enabled: bool = False
    caption_engine: str = "local"  # "local" or "groq"
    caption_style: str = "streamer"  # "streamer", "classic", "neon"
    caption_language: str = "auto"  # "auto", "tr", "en"
    whisper_model_size: str = "small"
    groq_api_key: str = ""


_CONFIG_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in fields(AppConfig))


class ConfigManager:
    """Thread-safe manager for loading, updating, and saving AppConfig."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.config_path: Path = Path(config_path) if config_path is not None else DATA_DIR / "config.json"
        self._ensure_directories()
        self.config: AppConfig = self.load()

    def _ensure_directories(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig:
        """Load configuration from disk, falling back to defaults if missing or invalid."""
        with self._lock:
            self._ensure_directories()
            if not self.config_path.exists():
                self.config = AppConfig()
                self.save()
                return self.config

            try:
                raw_text = self.config_path.read_text(encoding="utf-8")
                data = json.loads(raw_text)
                if not isinstance(data, dict):
                    raise ValueError("Config JSON root must be an object.")
            except Exception as exc:
                logger.warning("Failed to read config from %s (%s); using defaults.", self.config_path, exc)
                self.config = AppConfig()
                return self.config

            filtered: dict[str, Any] = {k: v for k, v in data.items() if k in _CONFIG_FIELD_NAMES}

            if "enabled_platforms" in filtered and isinstance(filtered["enabled_platforms"], dict):
                merged = _default_enabled_platforms()
                for key, val in filtered["enabled_platforms"].items():
                    merged[str(key)] = bool(val)
                filtered["enabled_platforms"] = merged

            if "video_extensions" in filtered and isinstance(filtered["video_extensions"], list):
                filtered["video_extensions"] = [
                    ext.lower() if str(ext).startswith(".") else f".{str(ext).lower()}"
                    for ext in filtered["video_extensions"]
                    if str(ext).strip()
                ]

            self.config = AppConfig(**filtered)
            return self.config

    def save(self) -> None:
        """Atomically persist the current configuration to disk as UTF-8 JSON."""
        with self._lock:
            self._ensure_directories()
            payload = json.dumps(asdict(self.config), indent=2, ensure_ascii=False)
            tmp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=str(self.config_path.parent),
                    prefix=".config_",
                    suffix=".tmp",
                    delete=False,
                ) as tmp_file:
                    tmp_file.write(payload)
                    tmp_path = tmp_file.name
                os.replace(tmp_path, self.config_path)
            except Exception:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise

    def update(self, **kwargs: Any) -> AppConfig:
        """Update known AppConfig fields and save to disk."""
        with self._lock:
            for key, value in kwargs.items():
                if key not in _CONFIG_FIELD_NAMES:
                    logger.debug("Ignoring unknown config field: %s", key)
                    continue
                if key == "enabled_platforms" and isinstance(value, dict):
                    merged = dict(self.config.enabled_platforms)
                    for platform, enabled in value.items():
                        merged[str(platform)] = bool(enabled)
                    setattr(self.config, key, merged)
                elif key == "video_extensions" and isinstance(value, list):
                    normalized = [
                        ext.lower() if str(ext).startswith(".") else f".{str(ext).lower()}"
                        for ext in value
                        if str(ext).strip()
                    ]
                    setattr(self.config, key, normalized)
                else:
                    setattr(self.config, key, value)
            self.save()
            return self.config
