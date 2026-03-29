"""
RotationScreen – Display-Drehung beim ersten Start.

Wird angezeigt wenn noch keine Display-Rotation gespeichert ist.
Der User kann das Display um 90° drehen bis es passt.
Nach Bestätigung wird die Rotation gespeichert und die App neu gestartet.
"""

import logging
import os
import sys

from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import Screen

from app.display_rotation import save_rotation

log = logging.getLogger(__name__)

Builder.load_string("""
#:kivy 2.3

<RotationScreen>:
    canvas.before:
        Color:
            rgba: 0.067, 0.067, 0.067, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        padding: [40, 30, 40, 30]
        spacing: 20

        Widget:
            size_hint_y: 1

        Label:
            text: '[color=ffffff]club[/color][color=ff6b35][b]fridge[/b][/color]'
            markup: True
            font_size: 32
            size_hint_y: None
            height: 40

        Label:
            text: 'Ist diese Anzeige richtig herum?'
            font_size: 20
            color: 0.85, 0.85, 0.85, 1
            size_hint_y: None
            height: 30

        Widget:
            size_hint_y: 0.5

        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: 50
            spacing: 20
            padding: [40, 0, 40, 0]

            Button:
                text: 'Drehen (90\\u00b0)'
                font_size: 18
                background_normal: ''
                background_color: 0.25, 0.25, 0.25, 1
                on_press: root.rotate()

            Button:
                text: 'Ja, weiter'
                font_size: 18
                background_normal: ''
                background_color: 1.0, 0.42, 0.208, 1
                on_press: root.confirm()

        Widget:
            size_hint_y: 1
""")


# Rotations-Reihenfolge beim Durchklicken
_ROTATIONS = [0, 90, 180, 270]


class RotationScreen(Screen):
    """Zeigt einen Dialog zum Drehen des Displays um 90°."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Aktuelle Rotation aus Kivy-Config lesen
        from kivy.config import Config
        try:
            self._current = int(Config.get("graphics", "rotation"))
        except (ValueError, KeyError):
            self._current = 0

    def rotate(self):
        """Display um 90° drehen und App neu starten."""
        idx = _ROTATIONS.index(self._current) if self._current in _ROTATIONS else 0
        new_rotation = _ROTATIONS[(idx + 1) % len(_ROTATIONS)]
        log.info("Display-Rotation: %d° → %d°", self._current, new_rotation)
        save_rotation(new_rotation)
        # App neu starten damit Kivy die neue Rotation übernimmt
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def confirm(self):
        """Aktuelle Rotation bestätigen und zum Setup weiter."""
        save_rotation(self._current)
        log.info("Display-Rotation bestätigt: %d°", self._current)
        # App neu starten — main.py liest jetzt die gespeicherte Rotation
        # und überspringt den RotationScreen
        os.execv(sys.executable, [sys.executable] + sys.argv)
