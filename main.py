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
    if settings.display_rotation and not os.path.exists("/tmp/.X11-unix/X0"):
        # Nur bei Portrait-Displays (H > W) rotieren. Landscape-Displays
        # (z.B. Touch Display 1, 800x480) brauchen keine Kivy-Rotation.
        _need_rotation = True
        try:
            _fb_size = open("/sys/class/graphics/fb0/virtual_size").read().strip()
            _fb_w, _fb_h = (int(x) for x in _fb_size.split(","))
            if _fb_h <= _fb_w:
                # Landscape-Display (z.B. Touch Display 1): 180° für kopfüber montierte Gehäuse
                Config.set("graphics", "rotation", "180")
                _need_rotation = False
        except Exception:
            pass  # Im Zweifel rotieren
        if _need_rotation:
            Config.set("graphics", "rotation", str(settings.display_rotation))
    if settings.fullscreen or not is_configured():
        Config.set("graphics", "fullscreen", "auto")

# Kein Multi-Touch-Emulation mit der Maus (stört auf dem Touchscreen)
Config.set("input", "mouse", "mouse,disable_multitouch")

# Mauszeiger auf Touchscreens ausblenden (nur Linux/Pi)
if sys.platform == "linux":
    Config.set("graphics", "show_cursor", "0")

from app.ui.app import KasseApp  # noqa: E402

if __name__ == "__main__":
    KasseApp().run()
