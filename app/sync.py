"""
Background-Sync-Manager.

Läuft als Daemon-Thread und erledigt periodisch:
1. Konnektivitäts-Check (online/offline)
2. Heartbeat: Credentials und Tenant-Status beim Server prüfen
3. Pending Bookings an den Server übermitteln
4. Mitglieder- und Produkt-Cache vom Server aktualisieren

Alle DB-Operationen gehen über local_db.py (sync SQLite).
Der Status (online, last_sync) kann von der UI abgefragt werden.

Deprovisioning:
  Wenn der Server beim Heartbeat mit 401/403 (ungültiger Key) oder 404
  (Tenant gelöscht) antwortet, wird die Kasse automatisch deprovisioned:
  lokaler Cache und .env werden gelöscht und der Prozess neu gestartet
  → SetupScreen erscheint für die Neueinrichtung.
"""
import logging
import threading
import time
from datetime import datetime, timezone

import json

from app.api_client import ApiClient, AuthError
from app.config import settings
from app.local_db import (
    clear_all_caches,
    get_cached_lock_config,
    get_pending_bookings,
    mark_bookings_synced,
    replace_member_cache,
    replace_product_cache,
    save_lock_config,
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
        self._last_lock_config_json: str | None = None

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
                    # Expliziter Credentials-Check: Heartbeat schlägt sofort an
                    # wenn Tenant gelöscht oder API-Key widerrufen wurde.
                    try:
                        self._api.heartbeat()
                    except AuthError as e:
                        log.error("Heartbeat: Kasse nicht mehr autorisiert – %s", e)
                        self._deprovision()
                        return

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
        except AuthError as e:
            log.warning("Cache-Refresh Mitglieder: Authentifizierungsfehler: %s", e)
            return
        except Exception as e:
            log.warning("Cache-Refresh Mitglieder fehlgeschlagen: %s", e)
            return

        try:
            products = self._api.fetch_products()
        except AuthError as e:
            log.warning("Cache-Refresh Produkte: Authentifizierungsfehler: %s", e)
            products = None
        except Exception as e:
            log.warning("Cache-Refresh Produkte fehlgeschlagen: %s", e)
            products = None

        replace_member_cache([
            {"id": m.id, "name": m.name, "rfid_token": m.rfid_token}
            for m in members
        ])
        if products is not None:
            replace_product_cache([
                {"id": p.id, "name": p.name, "barcode": p.barcode, "price": str(p.price)}
                for p in products
            ])

        self._try_refresh_config()

        self._last_cache_refresh_ts = time.monotonic()
        self.last_cache_at = datetime.now(timezone.utc)
        if products is not None:
            log.info("Cache aktualisiert: %d Mitglieder, %d Produkte", len(members), len(products))
        else:
            log.info("Cache aktualisiert: %d Mitglieder (Produkte nicht verfügbar)", len(members))

    # ------------------------------------------------------------------
    # Config-Refresh (Lock-Konfiguration vom Server)
    # ------------------------------------------------------------------

    def _try_refresh_config(self) -> None:
        """KasseConfig vom Server abrufen und Lock-Config lokal cachen."""
        try:
            config = self._api.fetch_config()
        except AuthError:
            return
        except Exception as e:
            log.warning("Config-Refresh fehlgeschlagen: %s", e)
            return

        if config is None:
            return

        new_lock = config.get("lock")
        save_lock_config(new_lock)

        # Hot-Swap: Lock-Treiber austauschen wenn sich die Config geändert hat
        new_json = json.dumps(new_lock, sort_keys=True) if new_lock else None
        if new_json != self._last_lock_config_json:
            self._last_lock_config_json = new_json
            self._hot_swap_lock(new_lock)

    def _hot_swap_lock(self, lock_config: dict | None) -> None:
        """Lock-Treiber im Kivy-Main-Thread austauschen."""
        from kivy.app import App
        from kivy.clock import Clock

        from app.hardware.lock import create_lock

        def _swap(_dt):
            app = App.get_running_app()
            if app and hasattr(app, "lock"):
                old = app.lock
                old.cleanup()
                if lock_config:
                    app.lock = create_lock(
                        lock_type=lock_config["lock_type"],
                        host=lock_config.get("lock_host"),
                        gpio_pin=lock_config.get("lock_gpio_pin"),
                        open_duration_ms=lock_config.get("lock_open_duration_ms", 3000),
                    )
                else:
                    app.lock = create_lock(lock_type=None)
                log.info("Lock-Treiber gewechselt: %s", type(app.lock).__name__)

        Clock.schedule_once(_swap, 0)

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

    def get_member_balance(self, member_id: str):
        """
        Gibt den offenen Saldo des Mitglieds zurück (Decimal) oder None wenn offline/Fehler.
        Blockierend – aus einem Hintergrund-Thread aufrufen.
        """
        if not self.online:
            return None
        return self._api.get_member_balance(member_id)

    def force_refresh(self) -> None:
        """Cache sofort neu laden (z.B. nach manuellem Anstoß aus der UI)."""
        t = threading.Thread(target=self._try_refresh_cache, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Deprovisioning (Tenant gelöscht / API-Key widerrufen)
    # ------------------------------------------------------------------

    def _deprovision(self) -> None:
        """
        Kasse hat ungültige Credentials (Tenant gelöscht oder API-Key widerrufen).

        Löscht den lokalen Cache (Mitglieder, Produkte, ausstehende Buchungen) und
        die .env-Konfiguration, dann wird der Prozess neu gestartet → SetupScreen
        erscheint für die Neueinrichtung.

        Wird aufgerufen wenn der Heartbeat 401/403/404 zurückgibt – d.h. nur wenn
        der Server explizit erreichbar ist und die Ablehnung bestätigt.
        """
        import os
        import sys

        from kivy.clock import Clock

        from app.provision import get_env_file

        log.error("Deprovisioning: lokaler Cache und Konfiguration werden gelöscht")

        self._running = False

        clear_all_caches()
        log.info("Lokaler Cache gelöscht")

        env = get_env_file()
        env.unlink(missing_ok=True)
        log.info("Konfiguration gelöscht – Einrichtungs-Assistent wird gestartet")

        Clock.schedule_once(
            lambda _dt: os.execv(sys.executable, [sys.executable] + sys.argv),
            2.0,
        )
