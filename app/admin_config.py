"""Backend-Helper fuer den Admin-Config-Screen.

Alle Shell-Outs, .env-Manipulation, cmdline.txt-Patches, nmcli-Aufrufe
leben zentral hier — die UI ruft nur high-level-Funktionen auf und muss
sich mit sudo/subprocess nicht befassen. Erlaubt Testing auf dem Dev-Mac
via Monkeypatch der jeweiligen Funktion.

Alle privilegierten Aufrufe gehen ueber sudo NOPASSWD — die
sudoers-Regel wird vom install.sh deployed (deploy/clubfridge-admin.sudoers).
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


ENV_PATH = Path("/opt/clubfridge/kasse/.env")
CMDLINE_PATHS = [
    Path("/boot/firmware/cmdline.txt"),  # Bookworm+/Trixie
    Path("/boot/cmdline.txt"),           # aeltere Images
]
BY_ID_PATH = Path("/dev/input/by-id")


# ---------------------------------------------------------------------------
# .env-Manipulation
# ---------------------------------------------------------------------------

def read_env() -> dict[str, str]:
    """Liest die aktuelle .env als key→value dict. Fehlende Datei → {}."""
    if not ENV_PATH.exists():
        return {}
    result: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def write_env(updates: dict[str, str]) -> None:
    """Aktualisiert bestehende Keys in .env, fuegt neue an. Erhalten
    bleiben Kommentare und Reihenfolge, nur die betroffenen Zeilen werden
    ersetzt."""
    existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    content = "\n".join(new_lines) + "\n"
    # Wir schreiben ueber sudo tee, damit die .env-Eigentumsverhaeltnisse
    # nicht kippen (Datei gehoert dem Service-User, App laeuft aber auch als
    # dieser — direktes Schreiben ist ok wenn wir Rechte haben. Fallback
    # ueber sudo).
    try:
        ENV_PATH.write_text(content, encoding="utf-8")
    except PermissionError:
        _sudo_write(ENV_PATH, content)


def _sudo_write(path: Path, content: str) -> None:
    """Schreibt via `sudo tee` — braucht NOPASSWD-Sudoers-Eintrag."""
    subprocess.run(
        ["sudo", "tee", str(path)],
        input=content.encode("utf-8"),
        check=True,
        stdout=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Bildschirm-Rotation (cmdline.txt + .env)
# ---------------------------------------------------------------------------

def _cmdline_path() -> Path | None:
    for p in CMDLINE_PATHS:
        if p.exists():
            return p
    return None


def set_rotation(rotation: int, invert_touch: bool = False) -> None:
    """Setzt Bildschirmdrehung persistent.

    - .env: DISPLAY_ROTATION + INVERT_TOUCH
    - cmdline.txt: fbcon=rotate:X (Console) + video=DSI-1:...,rotate=X (Pi 4)

    Braucht Reboot damit's greift.
    """
    if rotation not in (0, 90, 180, 270):
        raise ValueError(f"Ungueltige Rotation: {rotation}")

    write_env({"DISPLAY_ROTATION": str(rotation), "INVERT_TOUCH": "true" if invert_touch else "false"})

    path = _cmdline_path()
    if path is None:
        log.warning("cmdline.txt nicht gefunden — Console-Rotation kann nicht gesetzt werden")
        return

    current = path.read_text(encoding="utf-8").strip()
    # Bestehende Rotations-Argumente entfernen
    cleaned = re.sub(r"\s*fbcon=rotate:\d+", "", current)
    cleaned = re.sub(r"\s*video=DSI-1:[^\s]+", "", cleaned)

    # Neue Argumente anhaengen — fbcon-Codes: 0=0°, 1=90°, 2=180°, 3=270°
    fbcon_code = {0: 0, 90: 1, 180: 2, 270: 3}[rotation]
    new_line = cleaned.rstrip()
    if rotation != 0:
        new_line = f"{new_line} fbcon=rotate:{fbcon_code}"

    _sudo_write(path, new_line + "\n")
    log.info("cmdline.txt aktualisiert: rotation=%s", rotation)


def reboot_system() -> None:
    """Loest einen sauberen Reboot aus (sudo reboot)."""
    log.info("Reboot ausgeloest vom Admin-Config")
    subprocess.run(["sudo", "/sbin/reboot"], check=False)


# ---------------------------------------------------------------------------
# Eingabegeraete
# ---------------------------------------------------------------------------

@dataclass
class InputDevice:
    """Ein USB-HID-Keyboard (RFID/Barcode-Scanner sind USB-HID-Keyboards)."""
    by_id_path: str          # /dev/input/by-id/usb-....-event-kbd
    display_name: str        # menschenlesbar, aus dem by-id-Namen abgeleitet


def list_input_devices() -> list[InputDevice]:
    """Alle USB-HID-Keyboards die als by-id-Symlink existieren.

    Bei jedem Reboot bleibt der by-id-Pfad stabil, im Gegensatz zu
    /dev/input/eventN. Das ist der Weg, den wir in der Kasse-.env
    persistieren.
    """
    if not BY_ID_PATH.exists():
        return []
    devices: list[InputDevice] = []
    for entry in sorted(BY_ID_PATH.iterdir()):
        name = entry.name
        if not name.endswith("event-kbd"):
            continue
        # Anzeigename aus dem by-id-Filenamen: Underscores in Spaces, USB-Prefix + Suffix weg
        display = name
        if display.startswith("usb-"):
            display = display[4:]
        if display.endswith("-event-kbd"):
            display = display[: -len("-event-kbd")]
        display = display.replace("_", " ")
        devices.append(InputDevice(by_id_path=str(entry), display_name=display))
    return devices


# ---------------------------------------------------------------------------
# WLAN via nmcli
# ---------------------------------------------------------------------------

@dataclass
class WifiNetwork:
    ssid: str
    signal: int           # 0-100
    security: str         # "WPA2", "OPEN", ...
    in_use: bool          # gerade verbunden


def wifi_scan() -> list[WifiNetwork]:
    """Scannt und liefert sichtbare WLAN-Netzwerke, sortiert nach Signalstaerke.

    Nutzt nmcli mit stabiler Terse-Ausgabe (--terse --fields IN-USE,SSID,SIGNAL,SECURITY).
    """
    try:
        subprocess.run(
            ["sudo", "/usr/bin/nmcli", "dev", "wifi", "rescan"],
            check=False,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        r = subprocess.run(
            ["/usr/bin/nmcli", "--terse", "--fields", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warning("WLAN-Scan fehlgeschlagen: %s", e)
        return []

    seen: set[str] = set()
    networks: list[WifiNetwork] = []
    for line in r.stdout.splitlines():
        # Terse-Format nutzt : als Separator, escapte : sind \: — wir splitten simpel
        parts = line.split(":")
        if len(parts) < 4:
            continue
        in_use = parts[0].strip() == "*"
        ssid = parts[1].strip()
        try:
            signal = int(parts[2].strip() or "0")
        except ValueError:
            signal = 0
        security = parts[3].strip() or "OPEN"
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        networks.append(WifiNetwork(ssid=ssid, signal=signal, security=security, in_use=in_use))
    networks.sort(key=lambda n: (not n.in_use, -n.signal))
    return networks


def wifi_connect(ssid: str, password: str | None) -> tuple[bool, str]:
    """Versucht Verbindung zu einem WLAN. Returns (ok, message)."""
    args = ["sudo", "/usr/bin/nmcli", "dev", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=45)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"nmcli-Aufruf fehlgeschlagen: {e}"
    if r.returncode == 0:
        log.info("WLAN verbunden: %s", ssid)
        return True, r.stdout.strip() or "Verbunden"
    return False, (r.stderr.strip() or r.stdout.strip() or f"Fehler-Code {r.returncode}")
