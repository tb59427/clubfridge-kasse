"""
Abstraktes Lock-Interface und Factory für die Kühlschrank-Entriegelung.

Unterstützte Backends:
- GPIO-Relais (Original MagneticLockRelay-Verhalten)
- Shelly 1 Gen 4 (HTTP RPC)
- Tasmota (HTTP Command)
- NoopLock (kein Schloss konfiguriert)
"""
import abc
import logging
import threading
import time

import httpx

log = logging.getLogger(__name__)


class Lock(abc.ABC):
    """Abstrakte Basisklasse für Kühlschrank-Schloss-Treiber."""

    def __init__(self, open_duration_ms: int) -> None:
        self._duration = open_duration_ms / 1000.0
        self._lock = threading.Lock()
        self._close_event = threading.Event()

    @abc.abstractmethod
    def _activate(self) -> None:
        """Schloss öffnen (entriegeln / Relais anziehen)."""

    @abc.abstractmethod
    def _deactivate(self) -> None:
        """Schloss schließen (verriegeln / Relais abfallen)."""

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

    def __init__(self, gpio_pin: int, open_duration_ms: int) -> None:
        super().__init__(open_duration_ms)
        self._pin = gpio_pin
        self._gpio_ready = False
        self._gpio_failed = False
        import RPi.GPIO as GPIO
        self._GPIO = GPIO

    def _ensure_gpio(self) -> None:
        """GPIO erst bei Bedarf initialisieren (nicht im Konstruktor)."""
        if self._gpio_ready:
            return
        if self._gpio_failed:
            return
        try:
            self._GPIO.setmode(self._GPIO.BCM)
            self._GPIO.setup(self._pin, self._GPIO.OUT, initial=self._GPIO.LOW)
            self._gpio_ready = True
            log.info("GpioLock initialisiert: Pin %d", self._pin)
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
        self._GPIO.output(self._pin, self._GPIO.HIGH)
        log.info("GPIO HIGH (Pin %d)", self._pin)

    def _deactivate(self) -> None:
        self._ensure_gpio()
        if not self._gpio_ready:
            return
        self._GPIO.output(self._pin, self._GPIO.LOW)
        log.info("GPIO LOW (Pin %d)", self._pin)

    def cleanup(self) -> None:
        if self._gpio_ready and not self._gpio_failed:
            # Kein GPIO.cleanup() – das setzt den Pin auf INPUT und lässt ihn
            # floaten, was bei Relay-Boards mit Pull-Up ein kurzes Schalten
            # auslöst. Pin bleibt als OUTPUT/LOW stehen (sicher).
            self._GPIO.output(self._pin, self._GPIO.LOW)
            log.info("GpioLock: Pin %d bleibt LOW (kein cleanup)", self._pin)


class ShellyLock(Lock):
    """Shelly 1 Gen 4 WiFi-Schalter via HTTP RPC-API."""

    def __init__(self, host: str, open_duration_ms: int) -> None:
        super().__init__(open_duration_ms)
        self._url = f"http://{host}/rpc/Switch.Set"
        log.info("ShellyLock initialisiert: %s", self._url)

    def _activate(self) -> None:
        try:
            r = httpx.post(self._url, json={"id": 0, "on": True}, timeout=5.0)
            r.raise_for_status()
            log.debug("Shelly ON: %s", r.status_code)
        except Exception as e:
            log.error("Shelly activate fehlgeschlagen: %s", e)

    def _deactivate(self) -> None:
        try:
            r = httpx.post(self._url, json={"id": 0, "on": False}, timeout=5.0)
            r.raise_for_status()
            log.debug("Shelly OFF: %s", r.status_code)
        except Exception as e:
            log.error("Shelly deactivate fehlgeschlagen: %s", e)


class TasmotaLock(Lock):
    """Tasmota WiFi-Schalter via HTTP Command-API."""

    def __init__(self, host: str, open_duration_ms: int) -> None:
        super().__init__(open_duration_ms)
        self._base = f"http://{host}/cm"
        log.info("TasmotaLock initialisiert: %s", self._base)

    def _activate(self) -> None:
        try:
            r = httpx.get(self._base, params={"cmnd": "Power On"}, timeout=5.0)
            r.raise_for_status()
            log.debug("Tasmota ON: %s", r.status_code)
        except Exception as e:
            log.error("Tasmota activate fehlgeschlagen: %s", e)

    def _deactivate(self) -> None:
        try:
            r = httpx.get(self._base, params={"cmnd": "Power Off"}, timeout=5.0)
            r.raise_for_status()
            log.debug("Tasmota OFF: %s", r.status_code)
        except Exception as e:
            log.error("Tasmota deactivate fehlgeschlagen: %s", e)


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
) -> Lock:
    """Factory: erstellt den passenden Lock-Treiber anhand der Konfiguration."""
    log.info(
        "create_lock: type=%s, host=%s, gpio_pin=%s, duration=%dms",
        lock_type, host, gpio_pin, open_duration_ms,
    )
    if lock_type == "gpio":
        if gpio_pin is None:
            raise ValueError("gpio_pin erforderlich für GPIO-Lock")
        if not _is_gpio_available():
            log.warning("GPIO-Lock konfiguriert, aber RPi.GPIO nicht verfügbar – Lock deaktiviert")
            return NoopLock()
        return GpioLock(gpio_pin=gpio_pin, open_duration_ms=open_duration_ms)
    elif lock_type == "shelly":
        if host is None:
            raise ValueError("host erforderlich für Shelly-Lock")
        return ShellyLock(host=host, open_duration_ms=open_duration_ms)
    elif lock_type == "tasmota":
        if host is None:
            raise ValueError("host erforderlich für Tasmota-Lock")
        return TasmotaLock(host=host, open_duration_ms=open_duration_ms)
    else:
        log.info("Kein Lock-Typ konfiguriert – NoopLock erstellt")
        return NoopLock()
