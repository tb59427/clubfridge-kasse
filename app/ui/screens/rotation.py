"""
RotationScreen – Display-Drehung beim ersten Start (Tastatur-only).

Wird angezeigt wenn noch keine Display-Rotation gespeichert ist.
Keine Touch-Eingabe nötig — nur Tastatur:
  D = 90° drehen (App startet neu)
  Enter = bestätigen, weiter zum Setup
"""

import logging
import os
import sys

from kivy.core.window import Window
from kivy.lang import Builder
from kivy.uix.screenmanager import Screen

from app.display_rotation import confirm_rotation, save_rotation

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
        spacing: 10

        Widget:
            size_hint_y: 1

        Label:
            text: '[color=ffffff]club[/color][color=ff6b35][b]fridge[/b][/color]'
            markup: True
            font_size: 28
            size_hint_y: None
            height: 36

        Widget:
            size_hint_y: 0.3

        Label:
            text: 'Ist diese Anzeige richtig herum?'
            font_size: 18
            color: 0.85, 0.85, 0.85, 1
            size_hint_y: None
            height: 28

        Widget:
            size_hint_y: 0.3

        Label:
            text: '[b]D[/b]  =  Display um 90\\u00b0 drehen'
            markup: True
            font_size: 16
            color: 0.65, 0.65, 0.65, 1
            size_hint_y: None
            height: 24

        Label:
            text: '[b]Enter[/b]  =  Passt, weiter'
            markup: True
            font_size: 16
            color: 1.0, 0.42, 0.208, 1
            size_hint_y: None
            height: 24

        Widget:
            size_hint_y: 1
""")

_ROTATIONS = [0, 90, 180, 270]


class RotationScreen(Screen):

    def on_enter(self):
        Window.bind(on_key_down=self._on_key)

    def on_leave(self):
        Window.unbind(on_key_down=self._on_key)

    def _on_key(self, window, key, scancode, codepoint, modifiers):
        if codepoint == 'd':
            self._rotate()
            return True
        if key == 13:  # Enter
            self._confirm()
            return True
        return False

    def _get_current(self):
        from kivy.config import Config
        try:
            return int(Config.get("graphics", "rotation"))
        except (ValueError, KeyError):
            return 0

    def _rotate(self):
        current = self._get_current()
        idx = _ROTATIONS.index(current) if current in _ROTATIONS else 0
        new_rotation = _ROTATIONS[(idx + 1) % len(_ROTATIONS)]
        log.info("Display-Rotation: %d -> %d", current, new_rotation)
        save_rotation(new_rotation)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _confirm(self):
        current = self._get_current()
        log.info("Display-Rotation bestaetigt: %d", current)
        save_rotation(current)
        confirm_rotation()
        os.execv(sys.executable, [sys.executable] + sys.argv)
