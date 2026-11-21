"""Official X (Twitter) Free API video uploader (OAuth 1.0a + v1.1 chunked media + v2 tweets)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .base import BaseUploader, UploadResult

logger = logging.getLogger(__name__)

X_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
X_TWEETS_URL = "https://api.twitter.com/2/tweets"
X_ME_URL = "https://api.twitter.com/2/users/me"
CHUNK_SIZE_BYTES = 4 * 1024 * 1024  # 4 MB chunks
MAX_TWEET_LENGTH = 280
HTTP_TIMEOUT = 60


def _pct_encode(val: str) -> str:
    return quote(str(val), safe="~-._")


def _build_oauth1_header(
    method: str,
    url: str,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_secret: str,
    extra_params: dict[str, str] | None = None,
) -> str:
    """Build RFC 5849 OAuth 1.0a HMAC-SHA1 Authorization header with zero external dependencies."""
    oauth_params: dict[str, str] = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    sig_params: dict[str, str] = dict(oauth_params)
    if extra_params:
        for k, v in extra_params.items():
            sig_params[str(k)] = str(v)

    sorted_items = sorted((_pct_encode(k), _pct_encode(v)) for k, v in sig_params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    base_url = url.split("?", 1)[0]
    base_string = "&".join([method.upper(), _pct_encode(base_url), _pct_encode(param_str)])
    signing_key = f"{_pct_encode(api_secret)}&{_pct_encode(access_secret)}"

    digest = hmac.new(signing_key.encode("ascii"), base_string.encode("ascii"), hashlib.sha1).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode("ascii")

    header_parts = ", ".join(
        f'{_pct_encode(k)}="{_pct_encode(v)}"' for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


class TwitterUploader(BaseUploader):
    """Uploads vertical MP4 clips to X (Twitter) via official Free API (OAuth 1.0a)."""

    platform_name: str = "twitter"

    def _creds(self) -> tuple[str, str, str, str]:
        ak = str(getattr(self.config, "twitter_api_key", "") or "").strip()
        asec = str(getattr(self.config, "twitter_api_secret", "") or "").strip()
        at = str(getattr(self.config, "twitter_access_token", "") or "").strip()
        atsec = str(getattr(self.config, "twitter_access_token_secret", "") or "").strip()
        return ak, asec, at, atsec

    def is_configured(self) -> bool:
        return all(self._creds())

    def _auth_header(
        self,
        method: str,
        url: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, str]:
        ak, asec, at, atsec = self._creds()
        return {
            "Authorization": _build_oauth1_header(
                method, url, ak, asec, at, atsec, extra_params=extra_params
            )
        }

    def test_connection(self) -> tuple[bool, str]:
        if not self.is_configured():
            msg = (
                "X (Twitter) API anahtarları eksik (API Key, API Secret, Access Token, Access Token Secret). "
                "Hesaplar & API sekmesinden 4 anahtarı da girin."
            )
            if self.is_dry_run:
                msg += " (Test Modu açık olduğu için simülasyon yüklemeleri çalışır.)"
            return False, msg

        try:
            resp = requests.get(
                X_ME_URL,
                headers=self._auth_header("GET", X_ME_URL),
                timeout=20,
            )
            if not resp.ok:
                return False, f"X API hatası (HTTP {resp.status_code}): {resp.text[:220]}"
            data = resp.json().get("data") or {}
            username = data.get("username") or data.get("name") or "OK"
            return True, f"X (Twitter) bağlantısı başarılı (Hesap: @{username})."
        except requests.RequestException as exc:
            return False, f"X bağlantı hatası: {exc}"

    def _upload_video_chunked(self, video_path: Path) -> tuple[bool, str, str]:
        total_bytes = video_path.stat().st_size

        # 1. INIT
        init_params = {
            "command": "INIT",
            "total_bytes": str(total_bytes),
            "media_type": "video/mp4",
            "media_category": "tweet_video",
        }
        init_resp = requests.post(
            X_UPLOAD_URL,
            headers=self._auth_header("POST", X_UPLOAD_URL, extra_params=init_params),
            data=init_params,
            timeout=HTTP_TIMEOUT,
        )
        if not init_resp.ok:
            return False, "", f"X video INIT hatası (HTTP {init_resp.status_code}): {init_resp.text[:240]}"

        media_id = str(init_resp.json().get("media_id_string") or "")
        if not media_id:
            return False, "", "X API media_id döndürmedi."

        # 2. APPEND (multipart upload -> OAuth signature excludes multipart body per RFC 5849)
        segment_index = 0
        with video_path.open("rb") as fh:
            while True:
                chunk = fh.read(CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                append_resp = requests.post(
                    X_UPLOAD_URL,
                    headers=self._auth_header("POST", X_UPLOAD_URL),
                    data={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(segment_index),
                    },
                    files={"media": (video_path.name, chunk, "application/octet-stream")},
                    timeout=120,
                )
                if not append_resp.ok:
                    return (
                        False,
                        "",
                        f"X video parça yükleme hatası (parça {segment_index}, HTTP {append_resp.status_code}): "
                        f"{append_resp.text[:220]}",
                    )
                segment_index += 1

        # 3. FINALIZE
        fin_params = {"command": "FINALIZE", "media_id": media_id}
        fin_resp = requests.post(
            X_UPLOAD_URL,
            headers=self._auth_header("POST", X_UPLOAD_URL, extra_params=fin_params),
            data=fin_params,
            timeout=HTTP_TIMEOUT,
        )
        if not fin_resp.ok:
            return False, "", f"X video FINALIZE hatası (HTTP {fin_resp.status_code}): {fin_resp.text[:240]}"

        proc_info = fin_resp.json().get("processing_info")
        # 4. STATUS poll until succeeded
        deadline = time.monotonic() + 180.0
        while proc_info and time.monotonic() < deadline:
            state = str(proc_info.get("state") or "").lower()
            if state == "succeeded":
                break
            if state == "failed":
                err = proc_info.get("error") or {}
                return False, "", f"X video işleme başarısız: {err.get('message', err)}"
            wait_sec = max(2, int(proc_info.get("check_after_secs", 4) or 4))
            time.sleep(min(wait_sec, 10))
            st_params = {"command": "STATUS", "media_id": media_id}
            st_resp = requests.get(
                X_UPLOAD_URL,
                headers=self._auth_header("GET", X_UPLOAD_URL, extra_params=st_params),
                params=st_params,
                timeout=30,
            )
            if not st_resp.ok:
                break
            proc_info = st_resp.json().get("processing_info")

        return True, media_id, ""

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
                message="X (Twitter) yapılandırılmamış. Hesaplar & API sekmesinden 4 API anahtarını girin.",
            )

        try:
            ok_up, media_id, up_err = self._upload_video_chunked(video_path)
            if not ok_up or not media_id:
                return UploadResult(success=False, platform=self.platform_name, message=up_err)

            tweet_text = self._compose_text(title, description, hashtags, max_length=MAX_TWEET_LENGTH)
            headers = self._auth_header("POST", X_TWEETS_URL)
            headers["Content-Type"] = "application/json"

            tweet_resp = requests.post(
                X_TWEETS_URL,
                headers=headers,
                json={"text": tweet_text, "media": {"media_ids": [media_id]}},
                timeout=HTTP_TIMEOUT,
            )
            if not tweet_resp.ok:
                return UploadResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"X gönderi paylaşılamadı (HTTP {tweet_resp.status_code}): {tweet_resp.text[:260]}",
                )

            tweet_id = str((tweet_resp.json().get("data") or {}).get("id") or "")
            tweet_url = f"https://x.com/i/web/status/{tweet_id}" if tweet_id else ""
            return UploadResult(
                success=True,
                platform=self.platform_name,
                url=tweet_url,
                remote_id=tweet_id,
                message="X (Twitter) video gönderisi paylaşıldı!",
            )
        except requests.RequestException as exc:
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"X ağ hatası: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("X yükleme hatası: %s", exc)
            return UploadResult(
                success=False,
                platform=self.platform_name,
                message=f"X yükleme hatası: {exc}",
            )
