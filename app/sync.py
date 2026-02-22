"""
Background-Sync-Manager.

Läuft als Daemon-Thread und erledigt periodisch:
1. Konnektivitäts-Check (online/offline)
2. Pending Bookings an den Server übermitteln
3. Mitglieder- und Produkt-Cache vom Server aktualisieren

Alle DB-Operationen gehen über local_db.py (sync SQLite).
Der Status (online, last_sync) kann von der UI abgefragt werden.
"""
import logging
import threading
import time
from datetime import datetime, timezone

from app.api_client import ApiClient
from app.config import settings
from app.local_db import (
    get_pending_bookings,
    mark_bookings_synced,
    replace_member_cache,
    replace_product_cache,
    save_pending_booking,
)

log = logging.getLogger(__name__)


class SyncManager:
    def __init__(self) -> None:
        self._api = ApiClient()
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Öffentlicher Status (von der UI lesbar)
        self.online: bool = False
        self.last_sync_at: datetime | None = None
        self.last_cache_at: datetime | None = None

        self._last_cache_refresh_ts: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="SyncManager")
        self._thread.start()
        log.info("SyncManager gestartet (Intervall: %ds)", settings.sync_interval_seconds)

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Hauptschleife
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        # Beim ersten Start sofort Cache laden
        self._try_refresh_cache()

        while self._running:
            try:
                self.online = self._api.is_online()
                if self.online:
                    self._try_sync_bookings()
                    age = time.monotonic() - self._last_cache_refresh_ts
                    if age > settings.cache_refresh_interval_seconds:
                        self._try_refresh_cache()
            except Exception as e:
                log.error("SyncManager unerwarteter Fehler: %s", e, exc_info=True)

            time.sleep(settings.sync_interval_seconds)

    # ------------------------------------------------------------------
    # Cache-Aktualisierung
    # ------------------------------------------------------------------

    def _try_refresh_cache(self) -> None:
        try:
            members = self._api.fetch_members()
            products = self._api.fetch_products()
        except Exception as e:
            log.warning("Cache-Aktualisierung fehlgeschlagen: %s", e)
            return

        replace_member_cache([
            {"id": m.id, "name": m.name, "rfid_token": m.rfid_token}
            for m in members
        ])
        replace_product_cache([
            {"id": p.id, "name": p.name, "barcode": p.barcode, "price": str(p.price)}
            for p in products
        ])

        self._last_cache_refresh_ts = time.monotonic()
        self.last_cache_at = datetime.now(timezone.utc)
        log.info(
            "Cache aktualisiert: %d Mitglieder, %d Produkte",
            len(members), len(products),
        )

    # ------------------------------------------------------------------
    # Buchungs-Sync
    # ------------------------------------------------------------------

    def _try_sync_bookings(self) -> None:
        pending = get_pending_bookings()
        if not pending:
            return

        payload = [
            {
                "member_id": b.member_id,
                "booked_at": b.booked_at.isoformat(),
                "items": b.items,
            }
            for b in pending
        ]

        if self._api.sync_bookings(payload):
            mark_bookings_synced([b.id for b in pending])
            self.last_sync_at = datetime.now(timezone.utc)
            log.info("%d Buchung(en) synchronisiert", len(pending))

    # ------------------------------------------------------------------
    # Von der UI aufgerufen
    # ------------------------------------------------------------------

    def submit_booking(
        self,
        member_id: str,
        items: list[dict],
        total_price,
        booked_at: datetime | None = None,
    ) -> None:
        """
        Speichert eine Buchung lokal und versucht sofortigen Sync.
        Wird aus dem Kivy-Main-Thread aufgerufen – DB-Write ist kurz genug.
        """
        save_pending_booking(member_id, items, total_price, booked_at)
        log.info("Buchung gespeichert: member=%s total=%s", member_id, total_price)

        # Sofortiger Sync-Versuch im Hintergrund-Thread
        if self.online:
            t = threading.Thread(target=self._try_sync_bookings, daemon=True)
            t.start()

    def force_refresh(self) -> None:
        """Cache sofort neu laden (z.B. nach manuellem Anstoß aus der UI)."""
        t = threading.Thread(target=self._try_refresh_cache, daemon=True)
        t.start()
