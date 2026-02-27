"""
SSE Event-Listener für Echtzeit-Befehle vom Server.

Läuft als Daemon-Thread. Nutzt httpx.stream() zum Konsumieren von
Server-Sent Events. Bei ``lock:open``-Events wird das Schloss via
Kivy's Clock.schedule_once im Hauptthread geöffnet.

Reconnect automatisch mit exponentiellem Backoff bei Verbindungsabbruch.
"""

import json
import logging
import threading
import time

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 30.0


class SSEListener:
    """Background-Thread der Server-Sent Events konsumiert."""

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._base = f"{settings.server_url}/api/v1/kasse/{settings.tenant_slug}"
        self._headers = {"X-API-Key": settings.api_key}

    def start(self) -> None:
        if not settings.api_key:
            log.warning("SSE: Kein API-Key konfiguriert – Listener nicht gestartet")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="SSEListener"
        )
        self._thread.start()
        log.info("SSE: Listener gestartet (%s/events)", self._base)

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        backoff = _INITIAL_BACKOFF
        while self._running:
            try:
                self._connect_and_consume()
                # Normales Ende (Server hat Verbindung geschlossen)
                backoff = _INITIAL_BACKOFF
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    log.error(
                        "SSE: Authentifizierungsfehler %s – stoppe Listener",
                        e.response.status_code,
                    )
                    self._running = False
                    return
                log.warning(
                    "SSE: HTTP-Fehler %s – Reconnect in %.0fs",
                    e.response.status_code,
                    backoff,
                )
            except Exception as e:
                log.warning(
                    "SSE: Verbindungsfehler (%s) – Reconnect in %.0fs", e, backoff
                )

            if not self._running:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)

    def _connect_and_consume(self) -> None:
        """SSE-Verbindung öffnen und Events verarbeiten bis Disconnect."""
        with httpx.Client(
            headers=self._headers,
            timeout=httpx.Timeout(None, connect=10.0),
        ) as client:
            with client.stream("GET", f"{self._base}/events") as response:
                response.raise_for_status()
                log.info("SSE: Verbunden")

                event_type: str | None = None
                data_lines: list[str] = []

                for line in response.iter_lines():
                    if not self._running:
                        return

                    if line.startswith(":"):
                        # SSE-Comment (Keepalive) – ignorieren
                        continue
                    elif line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data_lines.append(line[6:])
                    elif line == "":
                        # Leerzeile = Event-Ende
                        if event_type and data_lines:
                            data_str = "\n".join(data_lines)
                            self._handle_event(event_type, data_str)
                        event_type = None
                        data_lines = []

    def _handle_event(self, event_type: str, data_str: str) -> None:
        """Empfangenes SSE-Event dispatchen."""
        log.info("SSE: Event empfangen: %s", event_type)
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            log.warning("SSE: Ungueltiges JSON: %s", data_str)
            return

        if event_type == "lock:open":
            self._trigger_lock_open(data)
        else:
            log.debug("SSE: Unbekannter Event-Typ: %s", event_type)

    def _trigger_lock_open(self, data: dict) -> None:
        """Kühlschrank-Schloss im Kivy-Hauptthread öffnen."""
        from kivy.app import App
        from kivy.clock import Clock

        member_name = data.get("member_name", "Unbekannt")
        log.info("SSE: Lock-Open fuer Mitglied %s (Web-Einkauf)", member_name)

        def _open(_dt: float) -> None:
            app = App.get_running_app()
            if app and hasattr(app, "lock"):
                app.lock.open()
                log.info("SSE: Lock geoeffnet (Web-Einkauf von %s)", member_name)

        Clock.schedule_once(_open, 0)
