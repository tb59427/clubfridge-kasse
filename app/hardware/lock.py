"""
Abstraktes Lock-Interface und Factory für die Kühlschrank-Entriegelung.

Unterstützte Backends:
- GPIO-Relais (Original MagneticLockRelay-Verhalten)
- Shelly 1 Gen 4 (HTTP RPC)
- Tasmota (HTTP Command)
- NoopLock (kein Schloss konfiguriert)

Schaltlogik (per ``invert``-Flag pro Kühlschrank konfigurierbar):
- ``invert=False`` (Default): Strom an = Schloss offen, Strom aus = Schloss zu.
  Klassisches fail-secure Magnethaft-Schloss.
- ``invert=True``: umgekehrt — Strom an = Schloss zu, Strom aus = Schloss offen.
  Z. B. Magnetspule die mit Strom verriegelt und stromlos öffnet.
"""
import abc
import logging
import threading

import httpx

log = logging.getLogger(__name__)


class Lock(abc.ABC):
    """Abstrakte Basisklasse für Kühlschrank-Schloss-Treiber."""

    def __init__(self, open_duration_ms: int, invert: bool = False) -> None:
        self._duration = open_duration_ms / 1000.0
        self._invert = invert
        self._lock = threading.Lock()
        self._close_event = threading.Event()

    @abc.abstractmethod
    def _activate(self) -> None:
        """Schloss öffnen (entriegeln)."""

    @abc.abstractmethod
    def _deactivate(self) -> None:
        """Schloss schließen (verriegeln)."""

    def signature(self) -> dict | None:
        """Aktuelle Lock-Konfiguration im Server-Config-Format.

        Wird vom Sync-Manager genutzt um zu erkennen ob ein Hot-Swap nötig
        ist: stimmt die neue Server-Config mit der aktuell laufenden
        Instanz überein, kann der Swap übersprungen werden — was bei
        GpioLock einen GPIO-Race vermeidet (RPi.GPIO ist nicht thread-safe;
        Hot-Swap mitten in einer laufenden Pulse-Session kann segfaulten).
        """
        return None

    def open(self) -> None:
        """Schloss für die konfigurierte Dauer öffnen (non-blocking)."""
        log.info("Lock.open() aufgerufen (%s, %.1fs)", type(self).__name__, self._duration)
        self._close_event.clear()
        t = threading.Thread(target=self._pulse, daemon=True, name="LockPulse")
        t.start()

    def close(self) -> None:
        """Schloss vorzeitig schließen (z. B. bei Abbruch oder Kaufabschluss)."""
        log.info("Lock.close() aufgerufen (%s)", type(self).__name__)
        self._close_event.set()

    def _pulse(self) -> None:
        with self._lock:
            try:
                self._activate()
                self._close_event.wait(timeout=self._duration)
            finally:
                self._deactivate()

    def cleanup(self) -> None:
        """Optionales Aufräumen beim Shutdown."""


class GpioLock(Lock):
    """GPIO-Relais-Schloss (BCM-Modus). Nur auf Raspberry Pi verwenden."""

    def __init__(
        self,
        gpio_pin: int,
        open_duration_ms: int,
        invert: bool = False,
    ) -> None:
        super().__init__(open_duration_ms, invert=invert)
        self._pin = gpio_pin
        self._gpio_ready = False
        self._gpio_failed = False
        import RPi.GPIO as GPIO
        self._GPIO = GPIO
        # Eager-Init: Pin sofort in den Ruhezustand (Schloss zu) bringen, damit
        # zwischen Boot und erster Lock-Operation nichts unbeabsichtigt offen ist.
        self._ensure_gpio()

    def _idle_level(self):
        """GPIO-Level für den Ruhezustand (Schloss zu)."""
        return self._GPIO.HIGH if self._invert else self._GPIO.LOW

    def _open_level(self):
        """GPIO-Level beim aktivierten Schloss (offen)."""
        return self._GPIO.LOW if self._invert else self._GPIO.HIGH

    def _ensure_gpio(self) -> None:
        """GPIO initialisieren und in den Ruhezustand (Schloss zu) bringen."""
        if self._gpio_ready:
            return
        if self._gpio_failed:
            return
        try:
            self._GPIO.setmode(self._GPIO.BCM)
            self._GPIO.setup(self._pin, self._GPIO.OUT, initial=self._idle_level())
            self._gpio_ready = True
            log.info(
                "GpioLock initialisiert: Pin %d (idle=%s, invert=%s)",
                self._pin,
                "HIGH" if self._idle_level() == self._GPIO.HIGH else "LOW",
                self._invert,
            )
        except RuntimeError as e:
            self._gpio_failed = True
            log.error(
                "GPIO-Initialisierung fehlgeschlagen (Pin %d): %s – "
                "auf Pi 5 wird 'rpi-lgpio' statt 'RPi.GPIO' benötigt",
                self._pin, e,
            )

    def _activate(self) -> None:
        self._ensure_gpio()
        if not self._gpio_ready:
            log.warning("GPIO nicht bereit – _activate() übersprungen (Pin %d)", self._pin)
            return
        level = self._open_level()
        self._GPIO.output(self._pin, level)
        log.info("GPIO %s (Pin %d, Schloss offen)", "HIGH" if level == self._GPIO.HIGH else "LOW", self._pin)

    def _deactivate(self) -> None:
        self._ensure_gpio()
        if not self._gpio_ready:
            return
        level = self._idle_level()
        self._GPIO.output(self._pin, level)
        log.info("GPIO %s (Pin %d, Schloss zu)", "HIGH" if level == self._GPIO.HIGH else "LOW", self._pin)

    def cleanup(self) -> None:
        if self._gpio_ready and not self._gpio_failed:
            # Kein GPIO.cleanup() – das setzt den Pin auf INPUT und lässt ihn
            # floaten, was bei Relay-Boards mit Pull-Up ein kurzes Schalten
            # auslöst. Pin bleibt im Ruhezustand (Schloss zu).
            self._GPIO.output(self._pin, self._idle_level())
            log.info("GpioLock: Pin %d bleibt im Ruhezustand (kein cleanup)", self._pin)

    def signature(self) -> dict:
        return {
            "lock_type": "gpio",
            "lock_host": None,
            "lock_gpio_pin": self._pin,
            "lock_open_duration_ms": int(round(self._duration * 1000)),
            "lock_invert": self._invert,
        }


class ShellyLock(Lock):
    """Shelly 1 Gen 4 WiFi-Schalter via HTTP RPC-API."""

    def __init__(
        self,
        host: str,
        open_duration_ms: int,
        invert: bool = False,
    ) -> None:
        super().__init__(open_duration_ms, invert=invert)
        self._host = host
        self._url = f"http://{host}/rpc/Switch.Set"
        log.info("ShellyLock initialisiert: %s (invert=%s)", self._url, invert)
        # Ruhezustand setzen — Schloss zu.
        self._set(on=self._invert)

    def signature(self) -> dict:
        return {
            "lock_type": "shelly",
            "lock_host": self._host,
            "lock_gpio_pin": None,
            "lock_open_duration_ms": int(round(self._duration * 1000)),
            "lock_invert": self._invert,
        }

    def _set(self, on: bool) -> None:
        try:
            r = httpx.post(self._url, json={"id": 0, "on": on}, timeout=5.0)
            r.raise_for_status()
            log.debug("Shelly Switch.Set on=%s: %s", on, r.status_code)
        except Exception as e:
            log.error("Shelly Switch.Set on=%s fehlgeschlagen: %s", on, e)

    def _activate(self) -> None:
        # Schloss offen: invert=False → on=True, invert=True → on=False.
        self._set(on=not self._invert)

    def _deactivate(self) -> None:
        # Schloss zu: invert=False → on=False, invert=True → on=True.
        self._set(on=self._invert)


class TasmotaLock(Lock):
    """Tasmota WiFi-Schalter via HTTP Command-API."""

    def __init__(
        self,
        host: str,
        open_duration_ms: int,
        invert: bool = False,
    ) -> None:
        super().__init__(open_duration_ms, invert=invert)
        self._host = host
        self._base = f"http://{host}/cm"
        log.info("TasmotaLock initialisiert: %s (invert=%s)", self._base, invert)
        # Ruhezustand setzen — Schloss zu.
        self._send("Power On" if self._invert else "Power Off")

    def signature(self) -> dict:
        return {
            "lock_type": "tasmota",
            "lock_host": self._host,
            "lock_gpio_pin": None,
            "lock_open_duration_ms": int(round(self._duration * 1000)),
            "lock_invert": self._invert,
        }

    def _send(self, command: str) -> None:
        try:
            r = httpx.get(self._base, params={"cmnd": command}, timeout=5.0)
            r.raise_for_status()
            log.debug("Tasmota %s: %s", command, r.status_code)
        except Exception as e:
            log.error("Tasmota %s fehlgeschlagen: %s", command, e)

    def _activate(self) -> None:
        self._send("Power Off" if self._invert else "Power On")

    def _deactivate(self) -> None:
        self._send("Power On" if self._invert else "Power Off")


class NoopLock(Lock):
    """Platzhalter wenn kein Schloss konfiguriert ist."""

    def __init__(self) -> None:
        super().__init__(0)

    def open(self) -> None:
        log.debug("NoopLock: kein Schloss konfiguriert")

    def close(self) -> None:
        pass

    def _activate(self) -> None:
        pass

    def _deactivate(self) -> None:
        pass


def _is_gpio_available() -> bool:
    """Prüft ob GPIO-Hardware verfügbar ist (nur auf Raspberry Pi)."""
    try:
        import RPi.GPIO  # noqa: F401
        return True
    except (ImportError, RuntimeError):
        return False


def create_lock(
    lock_type: str | None,
    *,
    host: str | None = None,
    gpio_pin: int | None = None,
    open_duration_ms: int = 3000,
    invert: bool = False,
) -> Lock:
    """Factory: erstellt den passenden Lock-Treiber anhand der Konfiguration."""
    log.info(
        "create_lock: type=%s, host=%s, gpio_pin=%s, duration=%dms, invert=%s",
        lock_type, host, gpio_pin, open_duration_ms, invert,
    )
    if lock_type == "gpio":
        if gpio_pin is None:
            raise ValueError("gpio_pin erforderlich für GPIO-Lock")
        if not _is_gpio_available():
            log.warning("GPIO-Lock konfiguriert, aber RPi.GPIO nicht verfügbar – Lock deaktiviert")
            return NoopLock()
        return GpioLock(
            gpio_pin=gpio_pin,
            open_duration_ms=open_duration_ms,
            invert=invert,
        )
    elif lock_type == "shelly":
        if host is None:
            raise ValueError("host erforderlich für Shelly-Lock")
        return ShellyLock(host=host, open_duration_ms=open_duration_ms, invert=invert)
    elif lock_type == "tasmota":
        if host is None:
            raise ValueError("host erforderlich für Tasmota-Lock")
        return TasmotaLock(host=host, open_duration_ms=open_duration_ms, invert=invert)
    else:
        log.info("Kein Lock-Typ konfiguriert – NoopLock erstellt")
        return NoopLock()
