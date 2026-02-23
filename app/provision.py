"""Provisioning-Logik für den Erststart der Kasse.

Zwei Einrichtungswege:
  1. USB-Stick / Boot-Partition: Liest config.json aus bekannten Pfaden
  2. Setup-Token: Ruft POST /api/v1/kasse/{slug}/provision auf und erhält API-Key
"""

import json
import logging
from pathlib import Path

import httpx

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


def detect_input_devices() -> tuple[str, str]:
    """
    Erkennt RFID-Leser und Barcode-Scanner anhand von /dev/input/by-id/.

    Verwendet stabile by-id-Symlinks (ändern sich nicht beim Neustart).
    Identifiziert RFID-Leser anhand von Name-Patterns; der erste verbleibende
    USB-HID-Keyboard-Eintrag wird als Barcode-Scanner angenommen.

    Gibt (rfid_device, barcode_device) zurück – fällt auf event0/event1 zurück
    wenn die Erkennung fehlschlägt.
    """
    DEFAULT_RFID = "/dev/input/event0"
    DEFAULT_BARCODE = "/dev/input/event1"

    by_id = Path("/dev/input/by-id")
    if not by_id.exists():
        log.warning("Geräteerkennung: /dev/input/by-id nicht vorhanden – verwende Defaults")
        return DEFAULT_RFID, DEFAULT_BARCODE

    # Nur Haupt-Tastaturinterfaces (event-kbd), keine Sub-Interfaces (event-if01 etc.)
    kbd_devices = sorted(by_id.glob("usb-*-event-kbd"))
    if not kbd_devices:
        log.warning("Geräteerkennung: Keine USB-HID-Tastaturen gefunden – verwende Defaults")
        return DEFAULT_RFID, DEFAULT_BARCODE

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

    # Barcode-Scanner: bevorzuge explizit benannte Scanner, fallback auf erstes verbleibendes Gerät
    BARCODE_PATTERNS = ("barcode", "scanner", "honeywell", "zebra", "symbol", "datalogic", "point_of_sale")
    barcode_path: Path | None = None
    for dev in other_paths:
        if any(p in dev.name.lower() for p in BARCODE_PATTERNS):
            barcode_path = dev
            break
    if barcode_path is None and other_paths:
        barcode_path = other_paths[0]

    if barcode_path:
        log.info("Geräteerkennung: Barcode-Scanner zugewiesen: %s", barcode_path.name)

    if rfid_path is None:
        log.warning("Geräteerkennung: Kein RFID-Leser erkannt – verwende Default %s", DEFAULT_RFID)
    if barcode_path is None:
        log.warning("Geräteerkennung: Kein Barcode-Scanner erkannt – verwende Default %s", DEFAULT_BARCODE)

    return (
        str(rfid_path) if rfid_path else DEFAULT_RFID,
        str(barcode_path) if barcode_path else DEFAULT_BARCODE,
    )


def write_env(api_url: str, tenant_slug: str, api_key: str) -> Path:
    """
    Schreibt die .env-Datei mit der Kassen-Konfiguration.

    Erstellt das Verzeichnis falls nötig und gibt den Pfad zurück.
    Gerätepfade werden automatisch erkannt (RFID, Barcode).
    """
    import datetime

    rfid_device, barcode_device = detect_input_devices()

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
