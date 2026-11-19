"""Official YouTube Data API v3 uploader for YouTube Shorts."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from .base import (
    DEFAULT_GOOGLE_SECRETS_PATH,
    DEFAULT_YOUTUBE_TOKEN_PATH,
    YOUTUBE_OAUTH_SCOPES,
    BaseUploader,
    UploadResult,
    get_google_credentials,
)

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS_TOTAL_CHARS = 500
RETRIABLE_STATUS_CODES = (500, 502, 503, 504)
MAX_RETRIES = 4


class YouTubeUploader(BaseUploader):
    """Uploads vertical clips to YouTube Shorts via YouTube Data API v3."""

    platform_name: str = "youtube"

    def _secrets_path(self) -> str:
        return str(
            getattr(
                self.config,
                "google_client_secrets_path",
                DEFAULT_GOOGLE_SECRETS_PATH,
            )
            or DEFAULT_GOOGLE_SECRETS_PATH
        )

    def _token_path(self) -> str:
        base_path = Path(
            str(
                getattr(
                    self.config,
                    "google_token_path",
                    DEFAULT_YOUTUBE_TOKEN_PATH,
                )
                or DEFAULT_YOUTUBE_TOKEN_PATH
            )
        )
        if base_path.name == "google_token.json":
            return str(base_path.with_name("youtube_token.json"))
        return str(base_path)

    def is_configured(self) -> bool:
        secrets = Path(self._secrets_path())
        token = Path(self._token_path())
        return secrets.is_file() or token.is_file()

    def _build_service(self) -> Any:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google API istemcisi yüklü değil. Lütfen şu komutu çalıştırın:\n"
                "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            ) from exc

        creds = get_google_credentials(
            client_secrets_path=self._secrets_path(),
            token_path=self._token_path(),
            scopes=YOUTUBE_OAUTH_SCOPES,
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def test_connection(self) -> tuple[bool, str]:
        if not self.is_configured():
            msg = (
                f"Google OAuth dosyası bulunamadı ({self._secrets_path()}). "
                "SETUP_GUIDE.md adımlarını izleyerek client_secret JSON dosyasını ekleyin."
            )
            if self.is_dry_run:
                msg += " (Test Modu açık olduğu için simülasyon yüklemeleri çalışır.)"
            return False, msg

        try:
            self._build_service()
            return (
                True,
                "YouTube Data API v3 bağlantısı hazır (Google OAuth2 yetkilendirmesi geçerli).",
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"YouTube bağlantı testi başarısız: {exc}"

    @staticmethod
    def _ensure_shorts_tag(title: str, description: str) -> tuple[str, str]:
        """Ensure '#Shorts' is present in title or description for Shorts classification."""
        clean_title = (title or "Yeni Oyun Klibi").strip()
        clean_desc = (description or "").strip()

        has_shorts = bool(
            re.search(r"#shorts\b", f"{clean_title}\n{clean_desc}", re.IGNORECASE)
        )
        if not has_shorts:
            if len(clean_title) + len(" #Shorts") <= MAX_TITLE_LENGTH:
                clean_title = f"{clean_title} #Shorts"
            else:
                clean_desc = f"{clean_desc}\n\n#Shorts".strip()

        if len(clean_title) > MAX_TITLE_LENGTH:
            clean_title = clean_title[: MAX_TITLE_LENGTH - 1].rstrip() + "…"
        if len(clean_desc) > MAX_DESCRIPTION_LENGTH:
            clean_desc = clean_desc[: MAX_DESCRIPTION_LENGTH - 1].rstrip() + "…"

        return clean_title, clean_desc

    @staticmethod
    def _extract_tags(hashtags: str) -> list[str]:
        """Parse hashtags string into a YouTube-compliant tag list."""
        if not hashtags:
            return ["Shorts"]

        raw_tokens = re.split(r"[\s,]+", hashtags.strip())
        tags: list[str] = []
        seen: set[str] = set()
        total_len = 0

        for token in raw_tokens:
            cleaned = token.lstrip("#").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            if total_len + len(cleaned) + 1 > MAX_TAGS_TOTAL_CHARS:
                break
            seen.add(key)
            tags.append(cleaned)
            total_len += len(cleaned) + 1

        if "shorts" not in seen and total_len + 7 <= MAX_TAGS_TOTAL_CHARS:
            tags.append("Shorts")
        return tags

    def upload(
        self,
        file_path: str,
        title: str,
        description: str,
        hashtags: str,
        **kwargs: Any,
    ) -> UploadResult:
        if self.is_dry_run:
            return self._simulate_upload(file_path, title)

        video_path, err = self._validate_video_file(file_path)
        if err or video_path is None:
            return UploadResult(success=False, platform=self.platform_name, message=err)

        if not self.is_configured():
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=(
                    f"YouTube yapılandırılmamış. Google OAuth dosyası eksik: "
                    f"{self._secrets_path()}"
                ),
            )

        try:
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Google API kütüphaneleri yüklü değil. Lütfen şu komutu çalıştırın: "
                    "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
                ),
            )

        try:
            service = self._build_service()

            full_desc = description or ""
            if hashtags and hashtags.strip():
                full_desc = f"{full_desc}\n\n{hashtags.strip()}".strip()

            final_title, final_desc = self._ensure_shorts_tag(title, full_desc)
            tags = self._extract_tags(hashtags)

            privacy_status = str(kwargs.get("privacy_status", "public") or "public")
            category_id = str(kwargs.get("category_id", "20") or "20")  # 20 = Gaming

            body = {
                "snippet": {
                    "title": final_title,
                    "description": final_desc,
                    "tags": tags,
                    "categoryId": category_id,
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            }

            media = MediaFileUpload(
                str(video_path),
                mimetype=self._guess_video_mimetype(video_path),
                chunksize=5 * 1024 * 1024,
                resumable=True,
            )

            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            retry = 0
            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        logger.info(
                            "YouTube yükleme ilerlemesi (%s): %%%d",
                            video_path.name,
                            int(status.progress() * 100),
                        )
                except HttpError as http_err:
                    status_code = getattr(http_err.resp, "status", None)
                    if status_code in RETRIABLE_STATUS_CODES and retry < MAX_RETRIES:
                        retry += 1
                        sleep_sec = 2**retry
                        logger.warning(
                            "YouTube geçici sunucu hatası (%s), %ds sonra yeniden denenecek (%d/%d).",
                            status_code,
                            sleep_sec,
                            retry,
                            MAX_RETRIES,
                        )
                        time.sleep(sleep_sec)
                        continue
                    raise

            video_id = str(response.get("id", ""))
            shorts_url = (
                f"https://www.youtube.com/shorts/{video_id}" if video_id else ""
            )
            return UploadResult(
                success=True,
                platform=self.platform_name,
                url=shorts_url,
                remote_id=video_id,
                message="YouTube Shorts yüklemesi başarıyla tamamlandı.",
            )

        except HttpError as http_err:
            err_text = str(http_err)
            if "quotaExceeded" in err_text:
                friendly = (
                    "YouTube API günlük yükleme kotası doldu (quotaExceeded). "
                    "Kota Pasifik saatiyle gece yarısında sıfırlanır."
                )
            elif "uploadLimitExceeded" in err_text:
                friendly = "YouTube kanalınızın günlük video yükleme sınırına ulaşıldı."
            else:
                friendly = f"YouTube API hatası: {err_text}"
            logger.exception("YouTube yükleme hatası: %s", friendly)
            return UploadResult(
                success=False, platform=self.platform_name, message=friendly
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("YouTube yükleme sırasında beklenmeyen hata")
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"YouTube yükleme hatası: {exc}",
            )
