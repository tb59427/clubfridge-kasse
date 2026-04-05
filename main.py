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

from app.provision import is_configured  # noqa: E402

if sys.platform == "linux":
    # Rotation: IMMER explizit setzen (sonst überschreibt gecachte config.ini)
    Config.set("graphics", "rotation", str(settings.display_rotation))

    # Fullscreen: IMMER explizit setzen (sonst überschreibt gecachte config.ini)
    if settings.fullscreen:
        Config.set("graphics", "fullscreen", "auto")
    elif not is_configured() and "WAYLAND_DISPLAY" not in os.environ:
        Config.set("graphics", "fullscreen", "auto")
    else:
        Config.set("graphics", "fullscreen", "0")

# Kein Multi-Touch-Emulation mit der Maus
Config.set("input", "mouse", "mouse,disable_multitouch")

# Mauszeiger auf Touchscreens ausblenden
if sys.platform == "linux":
    Config.set("graphics", "show_cursor", "0")

from app.ui.app import KasseApp  # noqa: E402

if __name__ == "__main__":
    KasseApp().run()
