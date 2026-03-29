"""
Clubfridge Kasse – Einstiegspunkt

Startet die Kivy-App für die Digitale Kasse auf dem Raspberry Pi.
Kivy muss vor dem Import der App-Klasse konfiguriert werden.
"""
import os

# Kivy-Konfiguration muss VOR dem ersten Kivy-Import gesetzt werden
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")

from app.config import settings  # noqa: E402


from kivy.config import Config  # noqa: E402

import sys

Config.set("kivy", "keyboard_mode", "system")
Config.set("graphics", "resizable", "0")
Config.set("graphics", "width", str(settings.window_width))
Config.set("graphics", "height", str(settings.window_height))

from app.provision import is_configured  # noqa: E402

# Auf dem Pi (Linux): Fullscreen + Rotation für Touchscreen-Gehäuse.
# Auf Mac/Windows: normales Fenster ohne Rotation (Entwicklung).
if sys.platform == "linux":
    if settings.display_rotation:
        # Rotation basierend auf nativer Auflösung (für offizielle Pi Touch Displays).
        # Portrait (H > W, z.B. Touch Display 2): 270° → Landscape
        # Landscape (W >= H, z.B. Touch Display 1): 180° → kopfüber montiertes Gehäuse
        # Bei 3rd-Party-Displays die schon richtig orientiert sind:
        # DISPLAY_ROTATION=0 in .env setzen.
        _rotation = str(settings.display_rotation)  # Default: 270
        try:
            _fb_size = open("/sys/class/graphics/fb0/virtual_size").read().strip()
            _fb_w, _fb_h = (int(x) for x in _fb_size.split(","))
            if _fb_h <= _fb_w:
                _rotation = "180"
        except Exception:
            pass
        Config.set("graphics", "rotation", _rotation)
    # Auf Linux immer Fullscreen (Pi-Touchscreen)
    Config.set("graphics", "fullscreen", "auto")

# Kein Multi-Touch-Emulation mit der Maus (stört auf dem Touchscreen)
Config.set("input", "mouse", "mouse,disable_multitouch")

# Mauszeiger auf Touchscreens ausblenden (nur Linux/Pi)
if sys.platform == "linux":
    Config.set("graphics", "show_cursor", "0")

from app.ui.app import KasseApp  # noqa: E402

if __name__ == "__main__":
    KasseApp().run()
