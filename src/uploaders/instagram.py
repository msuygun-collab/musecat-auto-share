"""Official Meta Graph API v21.0 uploader for Instagram Reels."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .base import BaseUploader, UploadResult

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
INSTAGRAM_GRAPH_API_BASE = "https://graph.instagram.com/v21.0"
MAX_CAPTION_LENGTH = 2200
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_POLL_TIMEOUT = 180.0
HTTP_TIMEOUT = 30


class InstagramUploader(BaseUploader):
    """Publishes Reels to Instagram via the official Meta/Instagram Graph API v21.0."""

    platform_name: str = "instagram"

    def _access_token(self) -> str:
        return str(getattr(self.config, "instagram_access_token", "") or "").strip()

    def _api_base(self, access_token: str | None = None) -> str:
        """Auto-select graph.instagram.com for Instagram Login tokens (IG...) or graph.facebook.com."""
        tok = (access_token if access_token is not None else self._access_token()).strip()
        if tok.startswith("IG"):
            return INSTAGRAM_GRAPH_API_BASE
        return GRAPH_API_BASE

    def _account_id(self) -> str:
        return str(getattr(self.config, "instagram_account_id", "") or "").strip()

    def _public_url_mode(self) -> str:
        return str(
            getattr(self.config, "instagram_public_url_mode", "google_drive")
            or "google_drive"
        ).strip().lower()

    def _custom_base_url(self) -> str:
        return str(getattr(self.config, "instagram_custom_base_url", "") or "").strip()

    def is_configured(self) -> bool:
        return bool(self._access_token() and self._account_id())

    @staticmethod
    def _extract_meta_error(response: requests.Response) -> str:
        try:
            payload = response.json()
            err = payload.get("error", {})
            if isinstance(err, dict):
                msg = err.get("message") or str(err)
                code = err.get("code")
                subcode = err.get("error_subcode")
                if code == 190:
                    return (
                        f"Instagram Access Token geçersiz veya süresi dolmuş "
                        f"(Kod: {code}/{subcode}): {msg}"
                    )
                return f"Meta Graph API hatası (Kod: {code}): {msg}"
        except ValueError:
            pass
        return f"HTTP {response.status_code}: {response.text[:300]}"

    def test_connection(self) -> tuple[bool, str]:
        if not self.is_configured():
            msg = (
                "Instagram Access Token veya Instagram Account ID eksik. "
                "Ayarlar sekmesinden bilgilerinizi girin (SETUP_GUIDE.md)."
            )
            if self.is_dry_run:
                msg += " (Test Modu açık olduğu için simülasyon yüklemeleri çalışır.)"
            return False, msg

        url = f"{self._api_base()}/{self._account_id()}"
        try:
            resp = requests.get(
                url,
                params={
                    "fields": "id,username",
                    "access_token": self._access_token(),
                },
                timeout=HTTP_TIMEOUT,
            )
            if not resp.ok:
                return False, self._extract_meta_error(resp)

            data = resp.json()
            username = data.get("username") or data.get("id")
            return (
                True,
                f"Instagram Graph API bağlantısı başarılı (Hesap: @{username}).",
            )
        except requests.RequestException as exc:
            return False, f"Instagram bağlantı hatası (ağ sorunu): {exc}"

    def _resolve_public_video_url(
        self, file_path: str, kwargs: dict[str, Any]
    ) -> str:
        passed_url = str(kwargs.get("public_video_url") or "").strip()
        if passed_url:
            return passed_url

        custom_base = self._custom_base_url()
        if custom_base and file_path:
            file_name = quote(Path(file_path).name)
            return f"{custom_base.rstrip('/')}/{file_name}"

        return ""

    def _wait_for_container(
        self,
        creation_id: str,
        access_token: str,
        poll_interval: float,
        poll_timeout: float,
    ) -> tuple[bool, str]:
        """Poll Instagram media container status until FINISHED or error/timeout."""
        status_url = f"{self._api_base(access_token)}/{creation_id}"
        deadline = time.monotonic() + poll_timeout

        while time.monotonic() < deadline:
            resp = requests.get(
                status_url,
                params={
                    "fields": "status_code,status",
                    "access_token": access_token,
                },
                timeout=HTTP_TIMEOUT,
            )
            if not resp.ok:
                return False, self._extract_meta_error(resp)

            data = resp.json()
            status_code = str(data.get("status_code") or "").upper()
            logger.info(
                "Instagram Reels işleme durumu (%s): %s", creation_id, status_code
            )

            if status_code == "FINISHED":
                return True, ""
            if status_code in ("ERROR", "EXPIRED"):
                detail = data.get("status") or status_code
                return (
                    False,
                    f"Instagram video işleme hatası ({status_code}): {detail}. "
                    "Video URL'sinin herkese açık ve doğrudan indirilebilir MP4 olduğundan emin olun.",
                )

            time.sleep(poll_interval)

        return (
            False,
            f"Instagram video işleme zaman aşımına uğradı ({int(poll_timeout)} saniye).",
        )

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

        if not self.is_configured():
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Instagram yapılandırılmamış. Ayarlar'dan Instagram Access Token "
                    "ve Instagram Account ID bilgilerini girin."
                ),
            )

        public_video_url = self._resolve_public_video_url(file_path, kwargs)
        if not public_video_url:
            mode = self._public_url_mode()
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Instagram Reels yüklemesi için herkese açık (public) bir video URL'si "
                    f"gereklidir (mevcut mod: '{mode}'). Lütfen Google Drive yedeklemesini "
                    "Instagram ile birlikte etkinleştirerek otomatik Drive bağlantısı kullanın "
                    "veya Ayarlar'dan özel herkese açık taban URL (instagram_custom_base_url) tanımlayın."
                ),
            )

        ig_user_id = self._account_id()
        access_token = self._access_token()
        caption = self._compose_text(
            title, description, hashtags, max_length=MAX_CAPTION_LENGTH
        )
        share_to_feed = bool(kwargs.get("share_to_feed", True))
        poll_interval = float(kwargs.get("poll_interval", DEFAULT_POLL_INTERVAL))
        poll_timeout = float(kwargs.get("poll_timeout", DEFAULT_POLL_TIMEOUT))

        try:
            # 1. Adım: Reels medya konteyneri oluştur
            api_base = self._api_base(access_token)
            create_url = f"{api_base}/{ig_user_id}/media"
            create_resp = requests.post(
                create_url,
                data={
                    "media_type": "REELS",
                    "video_url": public_video_url,
                    "caption": caption,
                    "share_to_feed": "true" if share_to_feed else "false",
                    "access_token": access_token,
                },
                timeout=HTTP_TIMEOUT,
            )
            if not create_resp.ok:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    message=(
                        "Instagram Reels konteyneri oluşturulamadı: "
                        + self._extract_meta_error(create_resp)
                    ),
                )

            creation_id = str(create_resp.json().get("id") or "")
            if not creation_id:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    message="Instagram API konteyner kimliği (creation_id) döndürmedi.",
                )

            # 2. Adım: Video işlenene kadar bekle
            ready, wait_err = self._wait_for_container(
                creation_id=creation_id,
                access_token=access_token,
                poll_interval=poll_interval,
                poll_timeout=poll_timeout,
            )
            if not ready:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    remote_id=creation_id,
                    message=wait_err,
                )

            # 3. Adım: Reels'i yayınla
            publish_url = f"{api_base}/{ig_user_id}/media_publish"
            publish_resp = requests.post(
                publish_url,
                data={
                    "creation_id": creation_id,
                    "access_token": access_token,
                },
                timeout=HTTP_TIMEOUT,
            )
            if not publish_resp.ok:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    remote_id=creation_id,
                    message=(
                        "Instagram Reels yayınlanamadı: "
                        + self._extract_meta_error(publish_resp)
                    ),
                )

            media_id = str(publish_resp.json().get("id") or "")
            permalink = f"https://www.instagram.com/reel/{media_id}/" if media_id else ""

            # Mümkünse gerçek permalink bilgisini çek
            if media_id:
                try:
                    link_resp = requests.get(
                        f"{api_base}/{media_id}",
                        params={
                            "fields": "permalink",
                            "access_token": access_token,
                        },
                        timeout=15,
                    )
                    if link_resp.ok:
                        fetched_link = link_resp.json().get("permalink")
                        if fetched_link:
                            permalink = str(fetched_link)
                except requests.RequestException:
                    pass

            return UploadResult(
                success=True,
                platform=self.platform_name,
                url=permalink,
                remote_id=media_id,
                message="Instagram Reels başarıyla yayınlandı.",
            )

        except requests.RequestException as exc:
            logger.exception("Instagram Reels yükleme ağ hatası")
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"Instagram bağlantı hatası: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Instagram Reels yükleme sırasında beklenmeyen hata")
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"Instagram yükleme hatası: {exc}",
            )
