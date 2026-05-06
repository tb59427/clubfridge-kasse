"""
Clubfridge Kasse – Einstiegspunkt

Startet die Kivy-App für die Digitale Kasse auf dem Raspberry Pi.
Kivy muss vor dem Import der App-Klasse konfiguriert werden.
"""
import os
import subprocess
import sys

# Kivy-Konfiguration muss VOR dem ersten Kivy-Import gesetzt werden
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")


def _check_kmsdrm_blockers() -> None:
    """Warnt laut wenn KMSDRM gewünscht ist, aber ein Compositor das Display hält.

    Im Service-Mode setzt der install.sh-Drop-in `SDL_VIDEODRIVER=kmsdrm`. Ist
    dann gleichzeitig labwc/wayfire/Xorg/lightdm aktiv, hält dieser DRM-Master
    auf /dev/dri/cardN — KMSDRM-Init scheitert, SDL2 fällt stillschweigend auf
    Xwayland zurück (falls DISPLAY gesetzt ist) und die Display-Rotation wird
    gegenüber dem Compositor verdoppelt. Sehr verwirrendes Symptom — daher
    einmal beim Start klar im Journal anschreien.
    """
    if sys.platform != "linux":
        return
    if os.environ.get("SDL_VIDEODRIVER") != "kmsdrm":
        return
    blockers = []
    for name in ("labwc", "wayfire", "Xorg", "Xwayland", "lightdm", "gdm", "sddm"):
        try:
            r = subprocess.run(
                ["pgrep", "-x", name], capture_output=True, timeout=2
            )
            if r.returncode == 0:
                blockers.append(name)
        except Exception:
            pass
    if blockers:
        sys.stderr.write(
            "FEHLER: KMSDRM ist angefordert (SDL_VIDEODRIVER=kmsdrm), aber "
            f"folgender Prozess hält das Display: {', '.join(blockers)}.\n"
            "Die Kasse fällt damit auf X11/Xwayland zurück — Display-Rotation "
            "und Fullscreen sind nicht zuverlässig.\n"
            "Reparatur: sudo systemctl mask lightdm display-manager "
            "&& sudo systemctl set-default multi-user.target && sudo reboot\n"
        )


_check_kmsdrm_blockers()

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

# Touch-Provider: ggf. invert_x/y wenn Display per DRM rotiert wird.
# (Sonst greifen die rotierten Touch-Koordinaten nicht zur sichtbaren UI.)
if settings.invert_touch:
    Config.set(
        "input",
        "%(name)s",
        "probesysfs,provider=mtdev,param=invert_x=1,param=invert_y=1",
    )
else:
    Config.set("input", "%(name)s", "probesysfs,provider=mtdev")

# Mauszeiger auf Touchscreens ausblenden
if sys.platform == "linux":
    Config.set("graphics", "show_cursor", "0")

from app.ui.app import KasseApp  # noqa: E402

if __name__ == "__main__":
    KasseApp().run()
