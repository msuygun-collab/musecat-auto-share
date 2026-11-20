"""Gumroad-powered license verification manager for MuseCat Pro (zero server cost)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from src.config import ConfigManager

logger = logging.getLogger(__name__)

GUMROAD_VERIFY_URL = "https://api.gumroad.com/v2/licenses/verify"
OFFLINE_GRACE_DAYS = 7
# Owner/developer local preview key (works only when gumroad_product_id is not yet locked)
_DEV_PREVIEW_KEY = "MUSECAT-DEV-PRO"


class LicenseManager:
    """Verifies and persists MuseCat Pro licenses using Gumroad's official License API."""

    def __init__(self, config_manager: ConfigManager) -> None:
        self.config_manager = config_manager

    @property
    def is_pro(self) -> bool:
        """Return True if an active Pro license is stored and within offline grace window."""
        cfg = self.config_manager.config
        if (cfg.license_status or "").lower() != "pro" or not (cfg.license_key or "").strip():
            return False

        last_ver = (cfg.license_last_verified or "").strip()
        if not last_ver:
            return True
        try:
            verified_dt = datetime.fromisoformat(last_ver)
            if verified_dt.tzinfo is None:
                verified_dt = verified_dt.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - verified_dt
            if age > timedelta(days=OFFLINE_GRACE_DAYS):
                # Allow caller to revalidate online; still return True until online check explicitly revokes
                return True
        except ValueError:
            pass
        return True

    def activate(self, license_key: str, lang: str = "tr") -> tuple[bool, str]:
        """Verify license key against Gumroad API and activate MuseCat Pro."""
        key = license_key.strip()
        if not key:
            msg = (
                "Lütfen geçerli bir lisans anahtarı girin."
                if lang == "tr"
                else "Please enter a valid license key."
            )
            return False, msg

        cfg = self.config_manager.config
        product_id = (cfg.gumroad_product_id or "").strip()

        # Allow local developer preview testing before Gumroad Product ID is configured
        if not product_id and key.upper() == _DEV_PREVIEW_KEY:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.config_manager.update(
                license_key=key.upper(),
                license_status="pro",
                license_email="owner@musecat.local",
                license_last_verified=now_iso,
            )
            self.config_manager.save()
            msg = (
                "MuseCat Pro (Geliştirici Önizleme) etkinleştirildi!"
                if lang == "tr"
                else "MuseCat Pro (Developer Preview) activated!"
            )
            return True, msg

        if not product_id:
            msg = (
                "Gumroad Ürün Kimliği (Product ID) henüz yapılandırılmamış. "
                "Test etmek için MUSECAT-DEV-PRO anahtarını kullanabilir veya Gumroad ürününüzü oluşturup Product ID ekleyebilirsiniz."
                if lang == "tr"
                else "Gumroad Product ID is not configured yet. Use MUSECAT-DEV-PRO for local testing or configure your Gumroad Product ID."
            )
            return False, msg

        try:
            resp = requests.post(
                GUMROAD_VERIFY_URL,
                data={
                    "product_id": product_id,
                    "license_key": key,
                    "increment_uses_count": "true",
                },
                timeout=20,
            )
            payload: dict[str, Any] = resp.json()
        except requests.RequestException as exc:
            msg = (
                f"Gumroad sunucusuna bağlanılamadı (internet bağlantınızı kontrol edin): {exc}"
                if lang == "tr"
                else f"Could not reach Gumroad license server: {exc}"
            )
            return False, msg
        except ValueError:
            msg = (
                f"Gumroad geçersiz yanıt döndürdü (HTTP {resp.status_code})."
                if lang == "tr"
                else f"Unexpected response from Gumroad (HTTP {resp.status_code})."
            )
            return False, msg

        if not payload.get("success"):
            err = payload.get("message") or "Geçersiz lisans anahtarı."
            msg = (
                f"Lisans doğrulanamadı: {err}"
                if lang == "tr"
                else f"License verification failed: {err}"
            )
            return False, msg

        purchase = payload.get("purchase") or {}
        if purchase.get("refunded") or purchase.get("chargebacked"):
            self.deactivate()
            msg = (
                "Bu lisans iade edildiği için artık geçerli değil."
                if lang == "tr"
                else "This license has been refunded and is no longer valid."
            )
            return False, msg

        if purchase.get("subscription_ended_at") or purchase.get("subscription_failed_at"):
            self.deactivate()
            msg = (
                "Bu abonelik lisansının süresi dolmuş."
                if lang == "tr"
                else "This subscription license has expired."
            )
            return False, msg

        email = str(purchase.get("email") or "")
        now_iso = datetime.now(timezone.utc).isoformat()
        self.config_manager.update(
            license_key=key,
            license_status="pro",
            license_email=email,
            license_last_verified=now_iso,
        )
        self.config_manager.save()
        msg = (
            f"MuseCat Pro başarıyla etkinleştirildi! ({email or 'Onaylı Lisans'})"
            if lang == "tr"
            else f"MuseCat Pro activated successfully! ({email or 'Verified License'})"
        )
        return True, msg

    def deactivate(self) -> None:
        """Remove stored Pro license and revert to Free tier."""
        self.config_manager.update(
            license_key="",
            license_status="free",
            license_email="",
            license_last_verified="",
            scheduler_enabled=False,
        )
        self.config_manager.save()
