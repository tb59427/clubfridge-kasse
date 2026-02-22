"""
RFID-Leser (USB HID Keyboard-Emulation).

Der RFID-Leser verhält sich wie eine USB-Tastatur: er "tippt" die Karten-ID
als Zeichenkette ein und schließt mit Enter ab. Wir öffnen das evdev-Gerät
exklusiv (grab), damit die Zeichen nicht in andere Felder gelangen.

Auf Nicht-Linux-Systemen (Entwicklung auf macOS/Windows) wird ein Mock
bereitgestellt, der Simulationen per `simulate(token)` erlaubt.
"""
import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

try:
    import evdev
    from evdev import InputDevice, categorize, ecodes
    _HAS_EVDEV = True
except ImportError:
    _HAS_EVDEV = False

# Mapping evdev-Keyname → Zeichen (Standardbelegung ohne Modifier)
_KEY_MAP: dict[str, str] = {
    "KEY_0": "0", "KEY_1": "1", "KEY_2": "2", "KEY_3": "3", "KEY_4": "4",
    "KEY_5": "5", "KEY_6": "6", "KEY_7": "7", "KEY_8": "8", "KEY_9": "9",
    "KEY_A": "A", "KEY_B": "B", "KEY_C": "C", "KEY_D": "D", "KEY_E": "E",
    "KEY_F": "F", "KEY_G": "G", "KEY_H": "H", "KEY_I": "I", "KEY_J": "J",
    "KEY_K": "K", "KEY_L": "L", "KEY_M": "M", "KEY_N": "N", "KEY_O": "O",
    "KEY_P": "P", "KEY_Q": "Q", "KEY_R": "R", "KEY_S": "S", "KEY_T": "T",
    "KEY_U": "U", "KEY_V": "V", "KEY_W": "W", "KEY_X": "X", "KEY_Y": "Y",
    "KEY_Z": "Z",
    "KEY_MINUS": "-", "KEY_DOT": ".", "KEY_SLASH": "/",
}


class RFIDReader:
    """
    Liest RFID-Token von einem evdev-Gerät.

    `on_scan(token: str)` wird im Kivy-Main-Thread aufgerufen
    (via Clock.schedule_once).
    """

    def __init__(self, device_path: str, on_scan: Callable[[str], None]) -> None:
        self._device_path = device_path
        self._on_scan = on_scan
        self._buffer = ""
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if not _HAS_EVDEV:
            log.warning(
                "evdev nicht verfügbar – RFID-Leser läuft im Mock-Modus. "
                "Im UI mit 'R' simulieren."
            )
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="RFIDReader"
        )
        self._thread.start()
        log.info("RFID-Leser gestartet: %s", self._device_path)

    def stop(self) -> None:
        self._running = False

    def _read_loop(self) -> None:
        try:
            device = InputDevice(self._device_path)
            device.grab()  # Exklusiver Zugriff – verhindert System-Tastatureingaben
        except Exception as e:
            log.error("RFID: Gerät %s konnte nicht geöffnet werden: %s", self._device_path, e)
            return

        log.info("RFID: Lese von %s", device.name)
        try:
            for event in device.read_loop():
                if not self._running:
                    break
                if event.type != ecodes.EV_KEY:
                    continue
                key_event = categorize(event)
                # Nur Key-Down-Events
                if key_event.keystate != 1:
                    continue

                scancode = key_event.scancode
                key_name = ecodes.KEY.get(scancode, "")
                if isinstance(key_name, list):
                    key_name = key_name[0] if key_name else ""

                if key_name == "KEY_ENTER":
                    token = self._buffer.strip()
                    self._buffer = ""
                    if token:
                        self._fire(token)
                else:
                    self._buffer += _KEY_MAP.get(key_name, "")
        except Exception as e:
            log.error("RFID: Lesefehler: %s", e)
        finally:
            try:
                device.ungrab()
            except Exception:
                pass

    def _fire(self, token: str) -> None:
        """UI-sicherer Callback via Kivy Clock."""
        try:
            from kivy.clock import Clock
            Clock.schedule_once(lambda _dt: self._on_scan(token), 0)
        except Exception:
            # Fallback wenn Kivy noch nicht initialisiert ist
            self._on_scan(token)

    def simulate(self, token: str) -> None:
        """Simuliert einen RFID-Scan (Entwicklungsmodus)."""
        log.debug("RFID simuliert: %s", token)
        self._fire(token)
