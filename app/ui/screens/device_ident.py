"""
DeviceIdentScreen – Interaktive Geräte-Identifikation.

Wird nach der Ersteinrichtung angezeigt, wenn die automatische Erkennung
von RFID-Leser und Barcode-Scanner unsicher war (generische Gerätenamen).

2-Schritt-Assistent:
  1. RFID-Karte scannen → identifiziert den RFID-Leser
  2. Barcode scannen → identifiziert den Barcode-Scanner

Lauscht auf allen angeschlossenen USB-HID-Keyboards gleichzeitig und
ordnet die Geräte anhand der tatsächlichen Eingabe zu.
"""

import logging
import os
import sys
import threading

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.screenmanager import Screen

from app.provision import probe_device, update_env_devices

log = logging.getLogger(__name__)

Builder.load_string("""
#:kivy 2.3

<DeviceIdentScreen>:
    canvas.before:
        Color:
            rgba: 0.067, 0.067, 0.067, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        padding: [40, 20, 40, 20]

        # ── Header ───────────────────────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 34

            Label:
                text: '[color=ffffff]club[/color][color=ff6b35][b]fridge[/b][/color]'
                markup: True
                font_size: 22
                size_hint_x: None
                width: 140
                halign: 'left'
                valign: 'middle'
                text_size: self.width, self.height

            Widget:

            Label:
                text: 'Geräte zuordnen'
                font_size: 15
                color: 0.78, 0.78, 0.78, 1
                size_hint_x: None
                width: 190
                halign: 'right'
                valign: 'middle'
                text_size: self.width, self.height

        # ── Flex-Spacer oben ─────────────────────────────────────────
        Widget:
            size_hint_y: 1

        # ── Schritt-Anzeige ──────────────────────────────────────────
        Label:
            text: root.step_label
            font_size: 14
            color: 0.58, 0.58, 0.58, 1
            size_hint_y: None
            height: 20
            halign: 'center'
            text_size: self.width, None

        # ── Hauptanweisung ───────────────────────────────────────────
        Label:
            text: root.instruction_text
            font_size: 26
            bold: True
            color: 1, 1, 1, 1
            size_hint_y: None
            height: 80
            halign: 'center'
            valign: 'middle'
            text_size: self.width, self.height

        # ── Status ───────────────────────────────────────────────────
        Label:
            text: root.status_text
            font_size: 15
            color: root.status_color
            size_hint_y: None
            height: 24
            halign: 'center'
            text_size: self.width, None

        # ── Flex-Spacer unten ────────────────────────────────────────
        Widget:
            size_hint_y: 1

        # ── Buttons (Probe-Phase) ───────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 50 if not root.confirm_visible else 0
            opacity: 0 if root.confirm_visible else 1
            spacing: 12

            Button:
                text: 'Überspringen'
                font_size: 15
                size_hint_x: 0.38
                background_normal: ''
                background_color: 0.18, 0.26, 0.42, 1
                on_press: root.skip()
                disabled: root.confirm_visible

            Button:
                text: 'Erneut versuchen'
                font_size: 15
                size_hint_x: 0.62
                background_normal: ''
                background_color: 0.35, 0.35, 0.35, 1
                on_press: root.retry()
                disabled: root.confirm_visible

        # ── Buttons (Bestätigung) ───────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 50 if root.confirm_visible else 0
            opacity: 1 if root.confirm_visible else 0
            spacing: 12

            Button:
                text: 'Nein'
                font_size: 15
                size_hint_x: 0.38
                background_normal: ''
                background_color: 0.8, 0.25, 0.15, 1
                on_press: root.confirm_no()
                disabled: not root.confirm_visible

            Button:
                text: 'Ja'
                font_size: 15
                size_hint_x: 0.62
                background_normal: ''
                background_color: 0.15, 0.6, 0.2, 1
                on_press: root.confirm_yes()
                disabled: not root.confirm_visible

        # ── Padding unten ────────────────────────────────────────────
        Widget:
            size_hint_y: None
            height: 10
""")


class DeviceIdentScreen(Screen):
    step_label = StringProperty("Schritt 1 von 2")
    instruction_text = StringProperty("Bitte RFID-Karte scannen…")
    status_text = StringProperty("Warte auf Eingabe…")
    status_color = ListProperty([0.7, 0.7, 0.7, 1])
    confirm_visible = BooleanProperty(False)

    def __init__(self, candidate_devices: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._candidates = candidate_devices
        self._rfid_device: str | None = None
        self._barcode_device: str | None = None
        self._probe_thread: threading.Thread | None = None
        self._cancelled = False

    def on_enter(self) -> None:
        self._start_rfid_probe()

    def on_leave(self) -> None:
        self._cancelled = True

    def _start_rfid_probe(self) -> None:
        self._cancelled = False
        self.step_label = "Schritt 1 von 2"
        self.instruction_text = "Bitte RFID-Karte\nan den Leser halten…"
        self._set_status("Warte auf Eingabe…", "normal")
        self._probe_thread = threading.Thread(
            target=self._probe_bg,
            args=(self._candidates, self._on_rfid_detected),
            daemon=True,
        )
        self._probe_thread.start()

    def _start_barcode_probe(self) -> None:
        self._cancelled = False
        remaining = [d for d in self._candidates if d != self._rfid_device]
        if not remaining:
            self._set_status("Kein weiteres Gerät vorhanden – Barcode-Scanner bleibt Default.", "warn")
            Clock.schedule_once(lambda _dt: self._finish(), 2.0)
            return
        self.step_label = "Schritt 2 von 2"
        self.instruction_text = "Bitte jetzt einen\nBarcode scannen…"
        self._set_status("Warte auf Eingabe…", "normal")
        self._probe_thread = threading.Thread(
            target=self._probe_bg,
            args=(remaining, self._on_barcode_detected),
            daemon=True,
        )
        self._probe_thread.start()

    def _probe_bg(self, paths: list[str], callback) -> None:
        detected = probe_device(paths, timeout=30.0)
        if self._cancelled:
            return
        if detected:
            Clock.schedule_once(lambda _dt: callback(detected))
        else:
            Clock.schedule_once(lambda _dt: self._on_timeout())

    def _on_rfid_detected(self, path: str) -> None:
        self._rfid_device = path
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        self._set_status(f"RFID-Leser erkannt: {name}", "ok")
        Clock.schedule_once(lambda _dt: self._start_barcode_probe(), 1.5)

    def _on_barcode_detected(self, path: str) -> None:
        self._barcode_device = path
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        self._set_status(f"Barcode-Scanner erkannt: {name}", "ok")
        Clock.schedule_once(lambda _dt: self._show_confirmation(), 1.5)

    def _show_confirmation(self) -> None:
        rfid_name = self._rfid_device.rsplit("/", 1)[-1] if self._rfid_device and "/" in self._rfid_device else (self._rfid_device or "–")
        barcode_name = self._barcode_device.rsplit("/", 1)[-1] if self._barcode_device and "/" in self._barcode_device else (self._barcode_device or "–")
        self.step_label = "Zuordnung prüfen"
        self.instruction_text = "Zuordnung korrekt?"
        self._set_status(f"RFID: {rfid_name}  ·  Barcode: {barcode_name}", "normal")
        self.confirm_visible = True

    def confirm_yes(self) -> None:
        self.confirm_visible = False
        self._finish()

    def confirm_no(self) -> None:
        self.confirm_visible = False
        self._rfid_device = None
        self._barcode_device = None
        self._start_rfid_probe()

    def _on_timeout(self) -> None:
        self._set_status("Timeout – keine Eingabe erkannt. Erneut versuchen oder überspringen.", "error")

    def retry(self) -> None:
        self._cancelled = True
        if self._rfid_device is None:
            self._start_rfid_probe()
        else:
            self._start_barcode_probe()

    def skip(self) -> None:
        self._cancelled = True
        self._set_status("Verwende automatisch erkannte Geräte – Neustart…", "warn")
        Clock.schedule_once(lambda _dt: _restart_process(), 1.5)

    def _finish(self) -> None:
        rfid = self._rfid_device
        barcode = self._barcode_device
        if rfid and barcode:
            update_env_devices(rfid, barcode)
            self._set_status("Geräte zugeordnet – Neustart…", "ok")
        elif rfid:
            update_env_devices(rfid, self._candidates[0] if self._candidates else "/dev/input/event1")
            self._set_status("RFID-Leser zugeordnet – Neustart…", "ok")
        Clock.schedule_once(lambda _dt: _restart_process(), 2.0)

    def _set_status(self, text: str, color: str = "normal") -> None:
        self.status_text = text
        self.status_color = {
            "ok":    [0.2, 0.85, 0.3, 1.0],
            "error": [1.0, 0.35, 0.2, 1.0],
            "warn":  [1.0, 0.75, 0.2, 1.0],
            "normal": [0.7, 0.70, 0.7, 1.0],
        }.get(color, [0.7, 0.7, 0.7, 1.0])


def _restart_process() -> None:
    """Startet den Python-Prozess neu."""
    log.info("Prozess-Neustart wird eingeleitet…")
    os.execv(sys.executable, [sys.executable] + sys.argv)
