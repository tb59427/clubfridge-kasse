"""Provisioning-Logik für den Erststart der Kasse.

Zwei Einrichtungswege:
  1. USB-Stick / Boot-Partition: Liest config.json aus bekannten Pfaden
  2. Setup-Token: Ruft POST /api/v1/kasse/{slug}/provision auf und erhält API-Key

Geräte-Erkennung:
  Automatische Erkennung von RFID-Leser und Barcode-Scanner anhand von
  /dev/input/by-id/ Symlinks. Bei unsicherer Erkennung (generische Gerätenamen)
  kann ein interaktiver Probe-Modus gestartet werden.
"""

import json
import logging
import select as _select
from dataclasses import dataclass, field
from pathlib import Path

import httpx

try:
    from evdev import InputDevice as _EvdevDevice, ecodes as _ecodes
    _HAS_EVDEV = True
except ImportError:
    _HAS_EVDEV = False

log = logging.getLogger(__name__)

# Mögliche Pfade für USB-Stick / Boot-Partition Konfiguration
USB_CONFIG_PATHS = [
    Path("/boot/clubfridge/config.json"),          # RPi (Bullseye, Bookworm)
    Path("/boot/firmware/clubfridge/config.json"), # Ubuntu RPi / Pi OS Bookworm arm64
    Path("/media/pi/CLUBFRIDGE/config.json"),      # automounted USB-Stick (Debian/Pi OS)
    Path("/media/pi/BOOT/clubfridge/config.json"), # automounted boot-Partition
    Path("/mnt/usb/config.json"),                  # manuell gemounted
]

# .env liegt im Kasse-Wurzelverzeichnis (Elternverzeichnis von app/)
_ENV_FILE = Path(__file__).parent.parent / ".env"

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def get_env_file() -> Path:
    """Gibt den Pfad der .env-Datei zurück."""
    return _ENV_FILE


def find_usb_config() -> dict | None:
    """
    Sucht config.json auf USB-Stick oder Boot-Partition.

    Gibt das geparste Dict zurück wenn eine gültige Konfiguration gefunden wurde,
    sonst None. Eine gültige Konfiguration enthält api_url, tenant_slug und api_key.
    """
    for path in USB_CONFIG_PATHS:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                required = {"api_url", "tenant_slug", "api_key"}
                if required.issubset(data.keys()) and data.get("api_key"):
                    log.info("USB-Konfiguration gefunden: %s", path)
                    return data
            except Exception as e:
                log.warning("Fehler beim Lesen von %s: %s", path, e)
    return None


def provision_with_token(api_url: str, tenant_slug: str, token: str) -> dict:
    """
    Löst einen Setup-Token ein und gibt die Konfiguration zurück.

    Sendet POST /api/v1/kasse/{tenant_slug}/provision mit dem Token.
    Gibt dict mit {api_url, tenant_slug, register_id, register_name, api_key} zurück.

    Wirft httpx.HTTPStatusError bei HTTP-Fehlern (404=ungültig, 410=abgelaufen).
    Wirft httpx.RequestError bei Verbindungsproblemen.
    """
    api_url = api_url.rstrip("/")
    token_clean = token.replace("-", "").upper().strip()

    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.post(
            f"{api_url}/api/v1/kasse/{tenant_slug}/provision",
            json={"token": token_clean},
        )
        r.raise_for_status()
        return r.json()


DEFAULT_RFID = "/dev/input/event0"
DEFAULT_BARCODE = "/dev/input/event1"


@dataclass
class DeviceDetectionResult:
    """Ergebnis der automatischen Geräte-Erkennung."""
    rfid_device: str = DEFAULT_RFID
    barcode_device: str = DEFAULT_BARCODE
    rfid_confident: bool = False
    barcode_confident: bool = False
    all_kbd_devices: list[str] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        return self.rfid_confident and self.barcode_confident


def detect_input_devices() -> DeviceDetectionResult:
    """
    Erkennt RFID-Leser und Barcode-Scanner anhand von /dev/input/by-id/.

    Verwendet stabile by-id-Symlinks (ändern sich nicht beim Neustart).
    Identifiziert RFID-Leser anhand von Name-Patterns; der erste verbleibende
    USB-HID-Keyboard-Eintrag wird als Barcode-Scanner angenommen.

    Gibt DeviceDetectionResult mit Geräte-Pfaden und Confidence-Info zurück.
    """
    result = DeviceDetectionResult()

    by_id = Path("/dev/input/by-id")
    if not by_id.exists():
        log.warning("Geräteerkennung: /dev/input/by-id nicht vorhanden – verwende Defaults")
        return result

    # Nur Haupt-Tastaturinterfaces (event-kbd), keine Sub-Interfaces (event-if01 etc.)
    kbd_devices = sorted(by_id.glob("usb-*-event-kbd"))
    if not kbd_devices:
        log.warning("Geräteerkennung: Keine USB-HID-Tastaturen gefunden – verwende Defaults")
        return result

    result.all_kbd_devices = [str(d) for d in kbd_devices]

    # RFID-Leser anhand bekannter Name-Patterns erkennen
    RFID_PATTERNS = ("rfid", "nfc", "reader", "sycreader", "acr", "mifare", "id_ic")

    rfid_path: Path | None = None
    other_paths: list[Path] = []

    for dev in kbd_devices:
        if rfid_path is None and any(p in dev.name.lower() for p in RFID_PATTERNS):
            rfid_path = dev
            log.info("Geräteerkennung: RFID-Leser erkannt: %s", dev.name)
        else:
            other_paths.append(dev)

    # Barcode-Scanner: bevorzuge explizit benannte Scanner, dann Geräte mit
    # eindeutiger Seriennummer (längerer Name), zuletzt erstes verbleibendes Gerät.
    BARCODE_PATTERNS = (
        "barcode", "scanner", "honeywell", "zebra", "symbol", "datalogic",
        "point_of_sale", "m4_yx", "m4", "ls2208", "ls4278",
    )
    barcode_path: Path | None = None
    barcode_by_pattern = False
    for dev in other_paths:
        if any(p in dev.name.lower() for p in BARCODE_PATTERNS):
            barcode_path = dev
            barcode_by_pattern = True
            break
    if barcode_path is None and other_paths:
        barcode_path = max(other_paths, key=lambda p: len(p.name))

    if rfid_path:
        result.rfid_device = str(rfid_path)
        result.rfid_confident = True
    else:
        log.warning("Geräteerkennung: Kein RFID-Leser erkannt – verwende Default %s", DEFAULT_RFID)

    if barcode_path:
        result.barcode_device = str(barcode_path)
        result.barcode_confident = barcode_by_pattern
        log.info("Geräteerkennung: Barcode-Scanner zugewiesen: %s", barcode_path.name)
    else:
        log.warning("Geräteerkennung: Kein Barcode-Scanner erkannt – verwende Default %s", DEFAULT_BARCODE)

    return result


def probe_device(candidate_paths: list[str], timeout: float = 30.0) -> str | None:
    """
    Lauscht auf allen Kandidaten-Geräten und gibt den Pfad zurück,
    auf dem zuerst eine Eingabe erkannt wird.

    Wird im Hintergrund-Thread aufgerufen (blockiert bis Eingabe oder Timeout).
    Gibt None zurück bei Timeout oder wenn evdev nicht verfügbar ist.
    """
    if not _HAS_EVDEV or not candidate_paths:
        return None

    devices: list[_EvdevDevice] = []
    path_by_fd: dict[int, str] = {}

    try:
        for path in candidate_paths:
            try:
                dev = _EvdevDevice(path)
                devices.append(dev)
                path_by_fd[dev.fd] = path
            except Exception as e:
                log.warning("Probe: Gerät %s konnte nicht geöffnet werden: %s", path, e)

        if not devices:
            return None

        deadline = __import__("time").monotonic() + timeout

        while True:
            remaining = deadline - __import__("time").monotonic()
            if remaining <= 0:
                log.info("Probe: Timeout nach %.0fs – keine Eingabe erkannt", timeout)
                return None

            r, _, _ = _select.select(devices, [], [], min(remaining, 1.0))
            for dev in r:
                try:
                    for event in dev.read():
                        if (
                            event.type == _ecodes.EV_KEY
                            and event.value == 1  # KEY_DOWN
                        ):
                            detected = path_by_fd[dev.fd]
                            log.info("Probe: Eingabe erkannt auf %s", detected)
                            return detected
                except Exception:
                    pass
    finally:
        for dev in devices:
            try:
                dev.close()
            except Exception:
                pass


def write_env(
    api_url: str,
    tenant_slug: str,
    api_key: str,
    *,
    rfid_device: str | None = None,
    barcode_device: str | None = None,
) -> Path:
    """
    Schreibt die .env-Datei mit der Kassen-Konfiguration.

    Erstellt das Verzeichnis falls nötig und gibt den Pfad zurück.
    Gerätepfade werden automatisch erkannt, können aber per Parameter
    überschrieben werden (z.B. nach interaktiver Identifikation).
    """
    import datetime

    if rfid_device is None or barcode_device is None:
        detected = detect_input_devices()
        if rfid_device is None:
            rfid_device = detected.rfid_device
        if barcode_device is None:
            barcode_device = detected.barcode_device

    env_path = get_env_file()
    env_path.parent.mkdir(parents=True, exist_ok=True)

    content = (
        "# Automatisch generiert – Clubfridge Kassen-Einrichtung\n"
        f"# Datum: {datetime.date.today().isoformat()}\n\n"
        "# Cloud Server\n"
        f"SERVER_URL={api_url.rstrip('/')}\n"
        f"TENANT_SLUG={tenant_slug}\n"
        f"API_KEY={api_key}\n\n"
        "# Hardware – automatisch erkannte Gerätepfade (bei Bedarf anpassen)\n"
        f"RFID_DEVICE={rfid_device}\n"
        f"BARCODE_DEVICE={barcode_device}\n"
        "HAS_RELAY=false\n"
        "RELAY_GPIO_PIN=18\n"
        "RELAY_OPEN_DURATION_MS=3000\n\n"
        "LOCAL_DB_PATH=kasse_local.db\n"
        "SYNC_INTERVAL_SECONDS=60\n"
        "CACHE_REFRESH_INTERVAL_SECONDS=300\n\n"
        "FULLSCREEN=true\n"
    )

    env_path.write_text(content, encoding="utf-8")
    log.info("Konfiguration geschrieben: %s", env_path)
    return env_path


def update_env_devices(rfid_device: str, barcode_device: str) -> None:
    """Aktualisiert RFID_DEVICE und BARCODE_DEVICE in der bestehenden .env."""
    env_path = get_env_file()
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        if line.startswith("RFID_DEVICE="):
            new_lines.append(f"RFID_DEVICE={rfid_device}")
        elif line.startswith("BARCODE_DEVICE="):
            new_lines.append(f"BARCODE_DEVICE={barcode_device}")
        else:
            new_lines.append(line)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log.info("Gerätepfade aktualisiert: RFID=%s, Barcode=%s", rfid_device, barcode_device)


def is_configured() -> bool:
    """
    Gibt True zurück, wenn die Kasse bereits konfiguriert ist.

    Prüft ob .env existiert und ein api_key gesetzt ist (nicht leer).
    """
    env_path = get_env_file()
    if not env_path.exists():
        return False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_KEY="):
            val = line.split("=", 1)[1].strip()
            return bool(val)
    return False
