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

Config.set("kivy", "keyboard_mode", "system")
Config.set("graphics", "resizable", "0")

if settings.fullscreen:
    Config.set("graphics", "fullscreen", "auto")
else:
    Config.set("graphics", "width", str(settings.window_width))
    Config.set("graphics", "height", str(settings.window_height))

# Kein Multi-Touch-Emulation mit der Maus (stört auf dem Touchscreen)
Config.set("input", "mouse", "mouse,disable_multitouch")

from app.ui.app import KasseApp  # noqa: E402

if __name__ == "__main__":
    KasseApp().run()
