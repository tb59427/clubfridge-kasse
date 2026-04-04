"""Display-Rotation Persistenz.

Speichert die gewählte Display-Rotation in einer Datei (.display_rotation)
neben der .env. Wird beim Start gelesen, bevor Kivy initialisiert wird.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_ROTATION_FILE = Path(__file__).parent.parent / ".display_rotation"


def get_saved_rotation() -> int | None:
    """Liest die gespeicherte Rotation (0/90/180/270) oder None wenn nicht gesetzt."""
    try:
        val = _ROTATION_FILE.read_text().strip()
        rotation = int(val)
        if rotation in (0, 90, 180, 270):
            return rotation
    except (FileNotFoundError, ValueError):
        pass
    return None


def save_rotation(rotation: int) -> None:
    """Speichert die gewählte Rotation."""
    _ROTATION_FILE.write_text(str(rotation))
    log.info("Display-Rotation gespeichert: %d°", rotation)


_CONFIRMED_FILE = Path(__file__).parent.parent / ".display_rotation_confirmed"


def has_saved_rotation() -> bool:
    """True wenn eine Rotation explizit vom User bestätigt wurde (Enter)."""
    return _CONFIRMED_FILE.exists()


def confirm_rotation() -> None:
    """Markiert die Rotation als bestätigt (Dialog wird nicht mehr angezeigt)."""
    _CONFIRMED_FILE.write_text("ok")
    log.info("Display-Rotation bestätigt")
