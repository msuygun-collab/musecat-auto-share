"""Official Google Drive API v3 uploader for clip backups and public Reels links."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import (
    DEFAULT_DRIVE_TOKEN_PATH,
    DEFAULT_GOOGLE_SECRETS_PATH,
    DRIVE_OAUTH_SCOPES,
    BaseUploader,
    UploadResult,
    get_google_credentials,
)

logger = logging.getLogger(__name__)

DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_DRIVE_FOLDER_NAME = "AutoClipShare_Backups"
RETRIABLE_STATUS_CODES = (500, 502, 503, 504)
MAX_RETRIES = 4


class GoogleDriveUploader(BaseUploader):
    """Backs up video clips to Google Drive via Google Drive API v3."""

    platform_name: str = "google_drive"

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
                    DEFAULT_DRIVE_TOKEN_PATH,
                )
                or DEFAULT_DRIVE_TOKEN_PATH
            )
        )
        if base_path.name == "google_token.json":
            return str(base_path.with_name("drive_token.json"))
        return str(base_path)

    def _root_folder_name(self) -> str:
        return str(
            getattr(self.config, "drive_folder_name", DEFAULT_DRIVE_FOLDER_NAME)
            or DEFAULT_DRIVE_FOLDER_NAME
        ).strip()

    def _organize_by_date(self) -> bool:
        return bool(getattr(self.config, "drive_organize_by_date", True))

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
            scopes=DRIVE_OAUTH_SCOPES,
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

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
            service = self._build_service()
            # drive.file scope ile güvenle çalışabilen hafif sorgu
            service.files().list(
                pageSize=1,
                fields="files(id, name)",
                q="trashed = false",
            ).execute()
            return (
                True,
                f"Google Drive API v3 bağlantısı başarılı (Hedef klasör: '{self._root_folder_name()}').",
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"Google Drive bağlantı testi başarısız: {exc}"

    @staticmethod
    def extract_file_id_from_url(url: str) -> str:
        """Extract Drive file ID from a webViewLink or uc?id= URL."""
        if not url:
            return ""
        import re
        match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        return ""

    def ensure_public_download_url(self, file_id: str) -> str:
        """Ensure an already-uploaded Drive file has anyone/reader permission and return direct download URL."""
        if not file_id:
            return ""
        if self.is_dry_run:
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        try:
            service = self._build_service()
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ).execute()
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Mevcut Drive dosyası herkese açık yapılamadı (%s): %s", file_id, exc)
            return ""

    @staticmethod
    def _escape_drive_query(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _find_or_create_folder(
        self,
        service: Any,
        folder_name: str,
        parent_id: str | None = None,
    ) -> str:
        escaped_name = self._escape_drive_query(folder_name)
        query_parts = [
            f"name = '{escaped_name}'",
            f"mimeType = '{DRIVE_FOLDER_MIME}'",
            "trashed = false",
        ]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")
        else:
            query_parts.append("'root' in parents")

        query = " and ".join(query_parts)
        result = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name)",
                pageSize=1,
            )
            .execute()
        )
        files = result.get("files", [])
        if files:
            return str(files[0]["id"])

        metadata: dict[str, Any] = {
            "name": folder_name,
            "mimeType": DRIVE_FOLDER_MIME,
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        created = (
            service.files()
            .create(body=metadata, fields="id")
            .execute()
        )
        return str(created["id"])

    def upload(
        self,
        file_path: str,
        title: str,
        description: str,
        hashtags: str,
        **kwargs: Any,
    ) -> UploadResult:
        make_public = bool(kwargs.get("make_public_for_instagram", False))

        if self.is_dry_run:
            return self._simulate_upload(
                file_path, title, make_public_url=make_public
            )

        video_path, err = self._validate_video_file(file_path)
        if err or video_path is None:
            return UploadResult(success=False, platform=self.platform_name, message=err)

        if not self.is_configured():
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=(
                    f"Google Drive yapılandırılmamış. Google OAuth dosyası eksik: "
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

            root_folder_id = self._find_or_create_folder(
                service, self._root_folder_name()
            )
            target_folder_id = root_folder_id

            if self._organize_by_date():
                today_folder = datetime.now().strftime("%Y-%m-%d")
                target_folder_id = self._find_or_create_folder(
                    service, today_folder, parent_id=root_folder_id
                )

            drive_description = self._compose_text(title, description, hashtags)
            file_metadata: dict[str, Any] = {
                "name": video_path.name,
                "parents": [target_folder_id],
            }
            if drive_description:
                file_metadata["description"] = drive_description

            media = MediaFileUpload(
                str(video_path),
                mimetype=self._guess_video_mimetype(video_path),
                chunksize=5 * 1024 * 1024,
                resumable=True,
            )

            request = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, webViewLink, webContentLink",
            )

            response = None
            retry = 0
            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        logger.info(
                            "Google Drive yükleme ilerlemesi (%s): %%%d",
                            video_path.name,
                            int(status.progress() * 100),
                        )
                except HttpError as http_err:
                    status_code = getattr(http_err.resp, "status", None)
                    if status_code in RETRIABLE_STATUS_CODES and retry < MAX_RETRIES:
                        retry += 1
                        sleep_sec = 2**retry
                        logger.warning(
                            "Google Drive geçici sunucu hatası (%s), %ds sonra yeniden denenecek (%d/%d).",
                            status_code,
                            sleep_sec,
                            retry,
                            MAX_RETRIES,
                        )
                        time.sleep(sleep_sec)
                        continue
                    raise

            file_id = str(response.get("id", ""))
            web_view_link = str(
                response.get("webViewLink")
                or (f"https://drive.google.com/file/d/{file_id}/view" if file_id else "")
            )
            public_download_url = ""

            if make_public and file_id:
                service.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "reader"},
                ).execute()
                public_download_url = (
                    f"https://drive.google.com/uc?export=download&id={file_id}"
                )

            msg = "Google Drive yedeklemesi başarıyla tamamlandı."
            if public_download_url:
                msg += " (Instagram Reels için herkese açık indirme bağlantısı oluşturuldu.)"

            return UploadResult(
                success=True,
                platform=self.platform_name,
                url=web_view_link,
                remote_id=file_id,
                message=msg,
                public_download_url=public_download_url,
            )

        except HttpError as http_err:
            err_text = str(http_err)
            if "storageQuotaExceeded" in err_text:
                friendly = "Google Drive depolama alanınız dolu (storageQuotaExceeded)."
            else:
                friendly = f"Google Drive API hatası: {err_text}"
            logger.exception("Google Drive yükleme hatası: %s", friendly)
            return UploadResult(
                success=False, platform=self.platform_name, message=friendly
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Google Drive yükleme sırasında beklenmeyen hata")
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"Google Drive yükleme hatası: {exc}",
            )
