"""Official TikTok Content Posting API v2 uploader (Inbox & Direct modes)."""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .base import BaseUploader, UploadResult

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2/post/publish"
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
DEFAULT_TIKTOK_REDIRECT_URI = "http://127.0.0.1:8765/callback"
SINGLE_CHUNK_MAX_BYTES = 64 * 1024 * 1024  # 64 MB
MULTI_CHUNK_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB (5 MB - 64 MB aralığında)
MAX_TITLE_LENGTH = 2200
HTTP_TIMEOUT = 60


class TikTokUploader(BaseUploader):
    """Uploads clips to TikTok via official Content Posting API v2."""

    platform_name: str = "tiktok"

    def _access_token(self) -> str:
        return str(getattr(self.config, "tiktok_access_token", "") or "").strip()

    def _post_mode(self) -> str:
        mode = str(getattr(self.config, "tiktok_post_mode", "inbox") or "inbox")
        mode = mode.strip().lower()
        return mode if mode in ("inbox", "direct") else "inbox"

    def is_configured(self) -> bool:
        return bool(self._access_token())

    @staticmethod
    def authorize_desktop_oauth(
        client_key: str,
        client_secret: str,
        redirect_uri: str = DEFAULT_TIKTOK_REDIRECT_URI,
        scopes: str = "user.info.basic,video.upload",
        timeout_seconds: int = 180,
    ) -> tuple[bool, str, str]:
        """Run local browser OAuth2 PKCE flow for TikTok Desktop Login Kit.

        Returns (success, access_token_or_empty, turkish_status_message).
        """
        ck = client_key.strip()
        cs = client_secret.strip()
        if not ck or not cs:
            return False, "", "Önce TikTok Client Key ve Client Secret alanlarını doldurun."

        parsed_uri = urlparse(redirect_uri)
        host = parsed_uri.hostname or "127.0.0.1"
        port = parsed_uri.port or 8765

        state = secrets.token_urlsafe(16)
        code_verifier = secrets.token_urlsafe(48)
        code_challenge = hashlib.sha256(code_verifier.encode("ascii")).hexdigest()

        result_box: dict[str, str] = {}
        done_event = threading.Event()

        class _CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def do_GET(self) -> None:  # noqa: N802
                qs = parse_qs(urlparse(self.path).query)
                if "code" in qs:
                    result_box["code"] = qs["code"][0]
                    result_box["state"] = qs.get("state", [""])[0]
                    body = (
                        "<html><body style='font-family:Segoe UI,sans-serif;background:#0b1020;"
                        "color:#e6ecff;text-align:center;padding:60px;'>"
                        "<h2>&#10004; TikTok girisi basarili!</h2>"
                        "<p>Bu pencereyi kapatip MuseCat Auto Share uygulamasina donebilirsiniz.</p>"
                        "</body></html>"
                    ).encode("utf-8")
                else:
                    err = qs.get("error_description", qs.get("error", ["Bilinmeyen hata"]))[0]
                    result_box["error"] = err
                    body = (
                        f"<html><body style='font-family:Segoe UI,sans-serif;background:#0b1020;"
                        f"color:#fca5a5;text-align:center;padding:60px;'>"
                        f"<h2>TikTok girisi tamamlanamadi</h2><p>{err}</p></body></html>"
                    ).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                done_event.set()

        try:
            server = HTTPServer((host, port), _CallbackHandler)
        except OSError as exc:
            return False, "", f"Yerel port ({port}) açılamadı: {exc}"

        server.timeout = 1.0

        def _serve() -> None:
            while not done_event.is_set():
                server.handle_request()

        srv_thread = threading.Thread(target=_serve, daemon=True)
        srv_thread.start()

        auth_params = {
            "client_key": ck,
            "scope": scopes,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{TIKTOK_AUTH_URL}?{urlencode(auth_params)}"
        webbrowser.open(auth_url)

        got_callback = done_event.wait(timeout=timeout_seconds)
        done_event.set()
        try:
            server.server_close()
        except Exception:
            pass

        if not got_callback:
            return False, "", "TikTok giriş zaman aşımına uğradı. Lütfen tekrar deneyin."

        if "error" in result_box:
            return False, "", f"TikTok yetkilendirme hatası: {result_box['error']}"

        code = result_box.get("code", "")
        if not code:
            return False, "", "TikTok yetkilendirme kodu (code) alınamadı."

        try:
            token_resp = requests.post(
                TIKTOK_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "client_key": ck,
                    "client_secret": cs,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                },
                timeout=30,
            )
            payload = token_resp.json()
            access_token = str(payload.get("access_token") or "")
            if not access_token:
                err_desc = payload.get("error_description") or payload.get("error") or token_resp.text[:250]
                return False, "", f"TikTok token alınamadı: {err_desc}"
            return True, access_token, "TikTok girişi başarılı! Access Token otomatik kaydedildi."
        except Exception as exc:  # noqa: BLE001
            return False, "", f"TikTok token değişimi hatası: {exc}"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    @staticmethod
    def _extract_tiktok_error(response: requests.Response) -> str:
        try:
            payload = response.json()
            err = payload.get("error", {})
            if isinstance(err, dict):
                code = err.get("code", "")
                message = err.get("message", "")
                if code and code != "ok":
                    if code in ("access_token_invalid", "token_expired"):
                        return (
                            f"TikTok Access Token geçersiz veya süresi dolmuş ({code}): "
                            f"{message}"
                        )
                    if code == "unaudited_client_can_only_post_to_private_accounts":
                        return (
                            "TikTok uygulamanız henüz denetlenmemiş (unaudited). "
                            "Ayarlar'dan TikTok modunu 'inbox' (Taslak/Gelen Kutusu) "
                            "olarak seçin veya yalnızca gizli hesapta deneyin."
                        )
                    return f"TikTok API hatası ({code}): {message}"
        except ValueError:
            pass
        return f"HTTP {response.status_code}: {response.text[:300]}"

    def test_connection(self) -> tuple[bool, str]:
        if not self.is_configured():
            msg = (
                "TikTok Access Token eksik. Ayarlar sekmesinden TikTok Access Token "
                "bilgisini girin (SETUP_GUIDE.md)."
            )
            if self.is_dry_run:
                msg += " (Test Modu açık olduğu için simülasyon yüklemeleri çalışır.)"
            return False, msg

        url = f"{TIKTOK_API_BASE}/creator_info/query/"
        try:
            resp = requests.post(
                url,
                headers=self._auth_headers(),
                json={},
                timeout=30,
            )
            if not resp.ok:
                return False, self._extract_tiktok_error(resp)

            payload = resp.json()
            err = payload.get("error", {})
            if err.get("code") not in (None, "", "ok"):
                return False, self._extract_tiktok_error(resp)

            data = payload.get("data", {})
            creator_name = (
                data.get("creator_nickname")
                or data.get("creator_username")
                or "Doğrulandı"
            )
            mode_label = (
                "Taslak / Gelen Kutusu (inbox)"
                if self._post_mode() == "inbox"
                else "Doğrudan Yayın (direct)"
            )
            return (
                True,
                f"TikTok API v2 bağlantısı başarılı (Hesap: {creator_name}, Mod: {mode_label}).",
            )
        except requests.RequestException as exc:
            return False, f"TikTok bağlantı hatası (ağ sorunu): {exc}"

    @staticmethod
    def _calculate_chunks(file_size: int) -> tuple[int, int]:
        """Compute (chunk_size, total_chunk_count) matching TikTok API v2 rules."""
        if file_size <= SINGLE_CHUNK_MAX_BYTES:
            return file_size, 1
        chunk_size = MULTI_CHUNK_SIZE_BYTES
        total_chunk_count = file_size // chunk_size
        return chunk_size, max(total_chunk_count, 1)

    def _upload_binary_chunks(
        self,
        video_path: Path,
        upload_url: str,
        file_size: int,
        chunk_size: int,
        total_chunk_count: int,
    ) -> tuple[bool, str]:
        content_type = self._guess_video_mimetype(video_path)
        with video_path.open("rb") as fh:
            for idx in range(total_chunk_count):
                start = idx * chunk_size
                if idx == total_chunk_count - 1:
                    # Son parça kalan tüm baytları içerir (TikTok kuralı)
                    bytes_to_read = file_size - start
                else:
                    bytes_to_read = chunk_size

                chunk = fh.read(bytes_to_read)
                end = start + len(chunk) - 1
                headers = {
                    "Content-Type": content_type,
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                }
                put_resp = requests.put(
                    upload_url,
                    headers=headers,
                    data=chunk,
                    timeout=HTTP_TIMEOUT,
                )
                if put_resp.status_code not in (200, 201, 206):
                    return (
                        False,
                        f"TikTok video parçası ({idx + 1}/{total_chunk_count}) yüklenemedi: "
                        f"HTTP {put_resp.status_code} - {put_resp.text[:250]}",
                    )
                logger.info(
                    "TikTok parça yüklendi (%s): %d/%d",
                    video_path.name,
                    idx + 1,
                    total_chunk_count,
                )
        return True, ""

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
                    "TikTok yapılandırılmamış. Ayarlar'dan TikTok Access Token "
                    "bilgisini girin."
                ),
            )

        file_size = video_path.stat().st_size
        chunk_size, total_chunk_count = self._calculate_chunks(file_size)
        mode = self._post_mode()

        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        }

        if mode == "direct":
            init_url = f"{TIKTOK_API_BASE}/video/init/"
            caption = self._compose_text(
                title, description, hashtags, max_length=MAX_TITLE_LENGTH
            )
            privacy_level = str(
                kwargs.get("privacy_level", "PUBLIC_TO_EVERYONE")
                or "PUBLIC_TO_EVERYONE"
            )
            init_payload: dict[str, Any] = {
                "post_info": {
                    "title": caption or video_path.stem,
                    "privacy_level": privacy_level,
                    "disable_duet": bool(kwargs.get("disable_duet", False)),
                    "disable_comment": bool(kwargs.get("disable_comment", False)),
                    "disable_stitch": bool(kwargs.get("disable_stitch", False)),
                },
                "source_info": source_info,
            }
        else:
            init_url = f"{TIKTOK_API_BASE}/inbox/video/init/"
            init_payload = {
                "source_info": source_info,
            }

        try:
            init_resp = requests.post(
                init_url,
                headers=self._auth_headers(),
                json=init_payload,
                timeout=30,
            )
            if not init_resp.ok:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    message=(
                        "TikTok yükleme oturumu başlatılamadı: "
                        + self._extract_tiktok_error(init_resp)
                    ),
                )

            payload = init_resp.json()
            err_obj = payload.get("error", {})
            if err_obj.get("code") not in (None, "", "ok"):
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    message=self._extract_tiktok_error(init_resp),
                )

            data = payload.get("data", {})
            publish_id = str(data.get("publish_id") or "")
            upload_url = str(data.get("upload_url") or "")
            if not upload_url:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    remote_id=publish_id,
                    message="TikTok API geçerli bir yükleme adresi (upload_url) döndürmedi.",
                )

            ok, chunk_err = self._upload_binary_chunks(
                video_path=video_path,
                upload_url=upload_url,
                file_size=file_size,
                chunk_size=chunk_size,
                total_chunk_count=total_chunk_count,
            )
            if not ok:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    remote_id=publish_id,
                    message=chunk_err,
                )

            if mode == "direct":
                msg = (
                    "Video TikTok'a doğrudan yayınlanmak üzere başarıyla yüklendi "
                    "(işlenme birkaç saniye sürebilir)."
                )
            else:
                msg = (
                    "Video TikTok Taslaklar / Gelen Kutusu'na (Inbox) başarıyla gönderildi. "
                    "TikTok uygulamanızdaki bildirimden tek dokunuşla yayınlayabilirsiniz."
                )

            return UploadResult(
                success=True,
                platform=self.platform_name,
                url="https://www.tiktok.com/creator-center/content",
                remote_id=publish_id,
                message=msg,
            )

        except requests.RequestException as exc:
            logger.exception("TikTok yükleme ağ hatası")
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"TikTok bağlantı hatası: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("TikTok yükleme sırasında beklenmeyen hata")
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"TikTok yükleme hatası: {exc}",
            )
