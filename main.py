"""
Clubfridge Kasse – Einstiegspunkt

Startet die Kivy-App für die Digitale Kasse auf dem Raspberry Pi.
Kivy muss vor dem Import der App-Klasse konfiguriert werden.
"""
import os
import sys

# Kivy-Konfiguration muss VOR dem ersten Kivy-Import gesetzt werden
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")

from app.config import settings  # noqa: E402
from kivy.config import Config  # noqa: E402

Config.set("kivy", "keyboard_mode", "system")
Config.set("graphics", "resizable", "0")
Config.set("graphics", "width", str(settings.window_width))
Config.set("graphics", "height", str(settings.window_height))

from app.display_rotation import get_saved_rotation  # noqa: E402
from app.provision import is_configured  # noqa: E402

if sys.platform == "linux":
    # 1. Gespeicherte Rotation hat Vorrang (vom Drehen-Dialog oder manuell)
    _saved = get_saved_rotation()
    if _saved is not None and _saved != 0:
        Config.set("graphics", "rotation", str(_saved))
    elif _saved is None and is_configured():
        # 2. Bestandsinstallation ohne gespeicherte Rotation: Auto-Detect
        if settings.display_rotation:
            _rotation = str(settings.display_rotation)
            try:
                _fb_size = open("/sys/class/graphics/fb0/virtual_size").read().strip()
                _fb_w, _fb_h = (int(x) for x in _fb_size.split(","))
                if _fb_h <= _fb_w:
                    _rotation = "180"
            except Exception:
                pass
            Config.set("graphics", "rotation", _rotation)
    # 3. Erster Start ohne Rotation: keine Rotation setzen (Dialog entscheidet)

    # Auf Linux immer Fullscreen
    Config.set("graphics", "fullscreen", "auto")

# Kein Multi-Touch-Emulation mit der Maus
Config.set("input", "mouse", "mouse,disable_multitouch")

# Mauszeiger auf Touchscreens ausblenden
if sys.platform == "linux":
    Config.set("graphics", "show_cursor", "0")

from app.ui.app import KasseApp  # noqa: E402

if __name__ == "__main__":
    KasseApp().run()
