"""Base uploader interface, result model, and shared Google OAuth2 helper."""

from __future__ import annotations

import logging
import mimetypes
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Google, youtube.upload ve drive.file kapsamlarının aynı OAuth isteğinde
# birleştirilmesine izin vermediği için ayrı kapsamlar ve ayrı token dosyaları kullanılır.
YOUTUBE_OAUTH_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/youtube.upload",
]
DRIVE_OAUTH_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive.file",
]
GOOGLE_OAUTH_SCOPES: list[str] = YOUTUBE_OAUTH_SCOPES

DEFAULT_GOOGLE_SECRETS_PATH = "data/credentials/google_client_secret.json"
DEFAULT_GOOGLE_TOKEN_PATH = "data/credentials/google_token.json"
DEFAULT_YOUTUBE_TOKEN_PATH = "data/credentials/youtube_token.json"
DEFAULT_DRIVE_TOKEN_PATH = "data/credentials/drive_token.json"


@dataclass
class UploadResult:
    """Standardized result object returned by all platform uploaders."""

    success: bool
    platform: str
    url: str = ""
    remote_id: str = ""
    message: str = ""
    dry_run: bool = False
    public_download_url: str = ""


class BaseUploader(ABC):
    """Abstract base class for all official platform uploaders."""

    platform_name: str = ""

    def __init__(self, config: Any) -> None:
        self.config = config

    @property
    def is_dry_run(self) -> bool:
        return bool(getattr(self.config, "dry_run", False))

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required credentials/settings exist for live uploads."""

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Validate credentials/API access and return (ok, turkish_status_message)."""

    @abstractmethod
    def upload(
        self,
        file_path: str,
        title: str,
        description: str,
        hashtags: str,
        **kwargs: Any,
    ) -> UploadResult:
        """Upload a video clip to the target platform."""

    def _simulate_upload(
        self,
        file_path: str,
        title: str,
        make_public_url: bool = False,
    ) -> UploadResult:
        """Simulate an upload in dry-run mode with a realistic URL and brief delay."""
        time.sleep(0.4)
        sim_id = uuid.uuid4().hex[:11]
        platform = self.platform_name or "unknown"

        url_templates = {
            "youtube": f"https://www.youtube.com/shorts/sim_{sim_id}",
            "google_drive": f"https://drive.google.com/file/d/sim_{sim_id}/view",
            "instagram": f"https://www.instagram.com/reel/sim_{sim_id}/",
            "tiktok": f"https://www.tiktok.com/@autoclipshare/video/sim_{sim_id}",
        }
        simulated_url = url_templates.get(
            platform, f"https://example.com/{platform}/sim_{sim_id}"
        )
        public_dl = (
            f"https://drive.google.com/uc?export=download&id=sim_{sim_id}"
            if (platform == "google_drive" and make_public_url)
            else ""
        )
        file_name = Path(file_path).name if file_path else "klip.mp4"
        return UploadResult(
            success=True,
            platform=platform,
            url=simulated_url,
            remote_id=f"sim_{sim_id}",
            message=(
                f"[TEST MODU] '{title or file_name}' videosu {platform} için "
                f"başarıyla simüle edildi (gerçek yükleme yapılmadı)."
            ),
            dry_run=True,
            public_download_url=public_dl,
        )

    @staticmethod
    def _validate_video_file(file_path: str) -> tuple[Path | None, str]:
        """Ensure the video file exists and is non-empty."""
        if not file_path:
            return None, "Video dosya yolu boş."
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return None, f"Video dosyası bulunamadı: {file_path}"
        if path.stat().st_size <= 0:
            return None, f"Video dosyası boş (0 bayt): {file_path}"
        return path, ""

    @staticmethod
    def _guess_video_mimetype(path: Path) -> str:
        """Guess MIME type for a video file, defaulting to video/mp4."""
        mime, _ = mimetypes.guess_type(str(path))
        return mime or "video/mp4"

    @staticmethod
    def _compose_text(
        title: str,
        description: str,
        hashtags: str,
        max_length: int | None = None,
    ) -> str:
        """Combine title, description, and hashtags into a clean caption."""
        parts = [p.strip() for p in (title, description, hashtags) if p and p.strip()]
        text = "\n\n".join(parts)
        if max_length is not None and len(text) > max_length:
            text = text[: max_length - 1].rstrip() + "…"
        return text


def get_google_credentials(
    client_secrets_path: str,
    token_path: str,
    scopes: list[str] | None = None,
) -> Any:
    """Load, refresh, or interactively obtain shared Google OAuth2 credentials.

    Uses lazy imports so the application can still launch when Google API
    packages are not installed yet.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Google API kütüphaneleri yüklü değil. Lütfen şu komutu çalıştırın:\n"
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    active_scopes = scopes or GOOGLE_OAUTH_SCOPES
    secrets_file = Path(client_secrets_path or DEFAULT_GOOGLE_SECRETS_PATH)
    token_file = Path(token_path or DEFAULT_GOOGLE_TOKEN_PATH)

    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(token_file), active_scopes
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Kayıtlı Google token okunamadı (%s), yeniden giriş yapılacak: %s",
                token_file,
                exc,
            )
            creds = None

    # Mevcut token'da istenen scope'lar eksikse yeniden yetkilendirme gerekir
    if creds and creds.scopes:
        missing_scopes = set(active_scopes) - set(creds.scopes)
        if missing_scopes:
            logger.info(
                "Google token'ında eksik izinler var (%s), yeniden oturum açılıyor.",
                ", ".join(sorted(missing_scopes)),
            )
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Google token yenilenemedi, tarayıcı üzerinden yeniden giriş başlatılıyor: %s",
                    exc,
                )
                creds = None

        if not creds or not creds.valid:
            if not secrets_file.exists():
                raise FileNotFoundError(
                    f"Google OAuth istemci dosyası bulunamadı: {secrets_file}\n"
                    "Lütfen Google Cloud Console'dan indirdiğiniz client_secret JSON "
                    "dosyasını bu konuma yerleştirin (SETUP_GUIDE.md dosyasına bakın)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secrets_file), active_scopes
            )
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                authorization_prompt_message=(
                    "Google hesabınızla giriş yapmak için tarayıcı açılıyor..."
                ),
                success_message=(
                    "AutoClipShareAuto Google yetkilendirmesi tamamlandı! "
                    "Bu sekmeyi kapatabilirsiniz."
                ),
            )

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return creds
