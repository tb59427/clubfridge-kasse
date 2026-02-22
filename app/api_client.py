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
    # Konnektivität
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        try:
            with httpx.Client(timeout=_HEALTH_TIMEOUT) as c:
                r = c.get(f"{settings.server_url}/health")
                return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Cache-Daten holen
    # ------------------------------------------------------------------

    def fetch_members(self) -> list[RemoteMember]:
        with self._client() as c:
            r = c.get(f"{self._base}/members")
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
