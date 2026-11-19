"""Official platform uploaders package for AutoClipShareAuto."""

from __future__ import annotations

from typing import Any

from .base import BaseUploader, UploadResult
from .google_drive import GoogleDriveUploader
from .instagram import InstagramUploader
from .tiktok import TikTokUploader
from .youtube import YouTubeUploader

__all__ = [
    "BaseUploader",
    "UploadResult",
    "YouTubeUploader",
    "GoogleDriveUploader",
    "InstagramUploader",
    "TikTokUploader",
    "create_uploaders",
]


def create_uploaders(config: Any) -> dict[str, BaseUploader]:
    """Instantiate all supported official platform uploaders with shared config."""
    drive_uploader = GoogleDriveUploader(config)
    return {
        "youtube": YouTubeUploader(config),
        "gdrive": drive_uploader,
        "google_drive": drive_uploader,
        "instagram": InstagramUploader(config),
        "tiktok": TikTokUploader(config),
    }
