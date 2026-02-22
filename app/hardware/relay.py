"""
GPIO-Relais für das Magnetschloss des Kühlschranks (optional).

Das Relais wird aktiviert, wenn ein Mitglied identifiziert wurde,
und nach `open_duration_ms` Millisekunden automatisch wieder deaktiviert.

Auf Nicht-Pi-Hardware wird ein Mock bereitgestellt, der nur loggt.
"""
import logging
import threading
import time

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except (ImportError, RuntimeError):
    _HAS_GPIO = False


class MagneticLockRelay:
    """
    Steuert das Magnetschloss via GPIO.

    open() aktiviert das Relais für `open_duration_ms` ms (non-blocking).
    """

    def __init__(self, gpio_pin: int, open_duration_ms: int, enabled: bool = True) -> None:
        self._pin = gpio_pin
        self._duration = open_duration_ms / 1000.0  # → Sekunden
        self._enabled = enabled and _HAS_GPIO
        self._lock = threading.Lock()

        if self._enabled:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.OUT, initial=GPIO.LOW)
            log.info("Relais initialisiert: GPIO-Pin %d", self._pin)
        elif enabled and not _HAS_GPIO:
            log.warning(
                "RPi.GPIO nicht verfügbar – Relais deaktiviert (Mock-Modus). "
                "Schloss-Öffnung wird nur geloggt."
            )

    def open(self) -> None:
        """
        Öffnet das Schloss für `open_duration_ms` Millisekunden.
        Nicht-blockierend: läuft in einem Daemon-Thread.
        """
        if not self._enabled:
            log.info("Relais (Mock): Schloss öffnet für %.1f s", self._duration)
            return

        t = threading.Thread(target=self._pulse, daemon=True, name="RelayPulse")
        t.start()

    def _pulse(self) -> None:
        with self._lock:
            try:
                GPIO.output(self._pin, GPIO.HIGH)
                log.debug("Relais HIGH (Pin %d)", self._pin)
                time.sleep(self._duration)
            finally:
                GPIO.output(self._pin, GPIO.LOW)
                log.debug("Relais LOW (Pin %d)", self._pin)

    def cleanup(self) -> None:
        if self._enabled:
            GPIO.cleanup(self._pin)
            log.info("Relais GPIO aufgeräumt")
