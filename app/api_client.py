"""
HTTP-Client für die Kommunikation mit dem Clubfridge Cloud Server.

Alle Calls sind synchron (kein asyncio) – Kivy hat seinen eigenen Event-Loop
und ruft den Client aus Background-Threads auf.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Timeout für reguläre Requests; Konnektivitätscheck ist kürzer
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_HEALTH_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

# HTTP-Statuscodes, die auf ungültige/widerrufene Credentials hinweisen
_AUTH_ERROR_CODES = frozenset({401, 403, 404})


class AuthError(Exception):
    """
    Wird ausgelöst wenn der Server Authentifizierung ablehnt (401/403/404).

    Tritt auf wenn:
    - Der API-Key ungültig oder widerrufen wurde (401/403)
    - Der Tenant nicht mehr existiert (404 via require_active_subscription)

    Der SyncManager reagiert darauf mit Deprovisioning.
    """


@dataclass
class RemoteMember:
    id: str
    name: str
    rfid_token: str | None


@dataclass
class RemoteProduct:
    id: str
    name: str
    barcode: str | None
    price: Decimal


class ApiClient:
    """Zustandsloser HTTP-Client – kann jederzeit neu instanziiert werden."""

    def __init__(self) -> None:
        self._base = f"{settings.server_url}/api/v1/kasse/{settings.tenant_slug}"
        self._headers = {"X-API-Key": settings.api_key}

    def _client(self) -> httpx.Client:
        return httpx.Client(headers=self._headers, timeout=_TIMEOUT)

    # ------------------------------------------------------------------
    # Konnektivität und Credential-Check
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        try:
            with httpx.Client(timeout=_HEALTH_TIMEOUT) as c:
                r = c.get(f"{settings.server_url}/health")
                return r.status_code == 200
        except Exception:
            return False

    def heartbeat(self) -> None:
        """
        Prüft ob Kasse und Tenant beim Server noch gültig sind.

        Wirft AuthError wenn der Server Credentials ablehnt (401/403)
        oder der Tenant nicht mehr existiert (404).
        Wirft httpx.RequestError bei Verbindungsproblemen.
        """
        with self._client() as c:
            r = c.get(f"{self._base}/heartbeat")
            if r.status_code in _AUTH_ERROR_CODES:
                raise AuthError(
                    f"Heartbeat HTTP {r.status_code}: "
                    f"{r.json().get('detail', r.text)}"
                )
            r.raise_for_status()

    # ------------------------------------------------------------------
    # Cache-Daten holen
    # ------------------------------------------------------------------

    def fetch_members(self) -> list[RemoteMember]:
        with self._client() as c:
            r = c.get(f"{self._base}/members")
            if r.status_code in _AUTH_ERROR_CODES:
                raise AuthError(f"HTTP {r.status_code} beim Abrufen der Mitglieder")
            r.raise_for_status()
            return [
                RemoteMember(
                    id=m["id"],
                    name=m["name"],
                    rfid_token=m.get("rfid_token"),
                )
                for m in r.json()
            ]

    def fetch_products(self) -> list[RemoteProduct]:
        with self._client() as c:
            r = c.get(f"{self._base}/products")
            if r.status_code in _AUTH_ERROR_CODES:
                raise AuthError(f"HTTP {r.status_code} beim Abrufen der Produkte")
            r.raise_for_status()
            return [
                RemoteProduct(
                    id=p["id"],
                    name=p["name"],
                    barcode=p.get("barcode"),
                    price=Decimal(str(p["price"])),
                )
                for p in r.json()
            ]

    # ------------------------------------------------------------------
    # Mitglieds-Saldo
    # ------------------------------------------------------------------

    def get_member_balance(self, member_id: str) -> Decimal | None:
        """
        Gibt den offenen Saldo des Mitglieds seit der letzten Abrechnung zurück.
        Gibt None zurück wenn offline, nicht aktiviert oder ein Fehler auftritt.
        """
        try:
            with self._client() as c:
                r = c.get(f"{self._base}/members/{member_id}/balance")
                r.raise_for_status()
                return Decimal(str(r.json()["open_amount"]))
        except Exception as e:
            log.debug("Saldo-Abfrage fehlgeschlagen: %s", e)
            return None

    # ------------------------------------------------------------------
    # Buchungen synchronisieren
    # ------------------------------------------------------------------

    def sync_bookings(self, bookings: list[dict[str, Any]]) -> bool:
        """
        Überträgt eine Batch-Liste von Buchungen an den Server.
        Gibt True zurück, wenn der Server 200/201 antwortet.
        """
        if not bookings:
            return True
        try:
            with self._client() as c:
                r = c.post(
                    f"{self._base}/sync/bookings",
                    json={"bookings": bookings},
                )
                r.raise_for_status()
                log.info("Sync OK: %d Buchungen übertragen", len(bookings))
                return True
        except httpx.HTTPStatusError as e:
            log.warning("Sync HTTP-Fehler %s: %s", e.response.status_code, e.response.text)
            return False
        except Exception as e:
            log.warning("Sync fehlgeschlagen: %s", e)
            return False
