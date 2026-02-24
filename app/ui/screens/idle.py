"""
IdleScreen – Wartebildschirm.

Zeigt die Aufforderung, die RFID-Karte zu scannen.
Wechselt automatisch zum ShoppingScreen, sobald ein RFID-Token
einem bekannten Mitglied zugeordnet werden kann.

Entwicklungsmodus:
  R → RFID-Scan mit dem ersten bekannten Mitglied simulieren
  F → Cache-Aktualisierung anstoßen
"""
import logging
import threading

try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("clubfridge-kasse")
except Exception:
    _VERSION = "0.1.0"

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.screenmanager import Screen

from app.config import settings
from app.local_db import find_member_by_rfid

log = logging.getLogger(__name__)

Builder.load_string("""
#:kivy 2.3

<IdleScreen>:
    _status_text: status_label.text

    canvas.before:
        # Hintergrundbild
        Rectangle:
            pos: self.pos
            size: self.size
            source: 'assets/bg.jpg'
        # Dunkle Überlagerung für Lesbarkeit
        Color:
            rgba: 0, 0, 0, 0.65
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        padding: [24, 20, 24, 20]
        spacing: 10

        # ── Statusleiste oben ──────────────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 40
            Widget:
            Label:
                id: status_label
                text: root.status_text
                color: root.status_color
                font_size: 18
                size_hint_x: None
                width: 150
                halign: 'right'
                valign: 'middle'
                text_size: self.size

        Widget:
            size_hint_y: 0.08

        # ── Brand Logo ─────────────────────────────────────────────────
        # Kuehlschrank-Icon (canvas) + "club" / "fridge" Wordmark
        BoxLayout:
            size_hint_y: None
            height: 110

            Widget:

            # Kuehlschrank-Icon (56x128 skaliert auf 52x110)
            Widget:
                size_hint: None, 1
                width: 52
                canvas:
                    Color:
                        rgba: 1.0, 0.42, 0.208, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [9]
                    # Gefrierfach-Trennlinie (38% von oben = 68px von unten)
                    Color:
                        rgba: 1, 1, 1, 0.22
                    Rectangle:
                        pos: self.x, self.y + 68
                        size: self.width, 2
                    # Gefrierfach-Griff
                    Color:
                        rgba: 1, 1, 1, 0.75
                    RoundedRectangle:
                        pos: self.x + 33, self.y + 94
                        size: 10, 3
                        radius: [1.5]
                    # Kuehlschrank-Griff
                    RoundedRectangle:
                        pos: self.x + 33, self.y + 51
                        size: 10, 3
                        radius: [1.5]
                    # Dekorative Punkte
                    Color:
                        rgba: 1, 1, 1, 0.22
                    Ellipse:
                        pos: self.x + 12, self.y + 16
                        size: 6, 6
                    Ellipse:
                        pos: self.x + 12, self.y + 28
                        size: 6, 6
                    Color:
                        rgba: 1, 1, 1, 0.15
                    Ellipse:
                        pos: self.x + 12, self.y + 40
                        size: 6, 6

            Widget:
                size_hint: None, 1
                width: 18

            # Wordmark: "club" (weiss) + "fridge" (orange, fett)
            BoxLayout:
                size_hint: None, 1
                width: 210
                orientation: 'vertical'
                Label:
                    text: 'club'
                    font_size: 50
                    color: 1, 1, 1, 0.95
                    halign: 'left'
                    text_size: self.width, None
                Label:
                    text: 'fridge'
                    font_size: 50
                    bold: True
                    color: 1.0, 0.42, 0.208, 1
                    halign: 'left'
                    text_size: self.width, None

            Widget:

        Widget:
            size_hint_y: 0.06

        # ── Scan-Aufforderung ──────────────────────────────────────────
        Label:
            id: prompt_label
            text: root.prompt_text
            font_size: 32
            color: 0.9, 0.9, 0.9, 1
            halign: 'center'
            text_size: self.width, None

        # ── Fehlermeldung ──────────────────────────────────────────────
        Label:
            id: error_label
            text: root.error_text
            font_size: 22
            color: 1.0, 0.35, 0.2, 1
            halign: 'center'
            text_size: self.width, None
            opacity: 1 if root.error_text else 0

        Widget:
            size_hint_y: 0.10

        # ── Versionszeile ──────────────────────────────────────────────
        Label:
            text: root.version_text
            font_size: 13
            color: 1, 1, 1, 0.20
            halign: 'center'
            text_size: self.width, None
            size_hint_y: None
            height: 22
""")


class IdleScreen(Screen):
    status_text = StringProperty("• OFFLINE")
    status_color = [1.0, 0.42, 0.208, 1]
    prompt_text = StringProperty("Bitte RFID-Karte scannen")
    error_text = StringProperty("")
    version_text = StringProperty(f"v{_VERSION}  ·  © 2026 Torsten Beyer")

    def on_enter(self) -> None:
        """Wird aufgerufen, wenn der Screen aktiv wird."""
        self.error_text = ""
        self.prompt_text = "Bitte RFID-Karte scannen"
        # Online-Status alle 5 Sekunden aktualisieren
        Clock.schedule_interval(self._update_status, 5)
        self._update_status(0)

    def on_leave(self) -> None:
        Clock.unschedule(self._update_status)

    def _update_status(self, _dt) -> None:
        app = App.get_running_app()
        if app.sync_manager.online:
            self.status_text = "• ONLINE"
            self.status_color = [0.2, 0.85, 0.3, 1]
        else:
            self.status_text = "• OFFLINE"
            self.status_color = [1.0, 0.42, 0.208, 1]

    # ------------------------------------------------------------------
    # RFID-Callback (wird von RFIDReader im Main-Thread aufgerufen)
    # ------------------------------------------------------------------

    def on_rfid_scan(self, token: str) -> None:
        log.info("RFID-Scan: %s", token)
        member = find_member_by_rfid(token)

        if member is None:
            log.warning("Unbekannte RFID-Karte: %s", token)
            self.error_text = "Unbekannte Karte – bitte beim Admin melden"
            Clock.schedule_once(lambda _dt: self._clear_error(), 3)
            return

        log.info("Mitglied erkannt: %s (%s)", member.name, member.id)
        app = App.get_running_app()

        # Kuehlschrank entriegeln (falls Relais konfiguriert)
        app.relay.open()

        # Zum Shopping-Screen wechseln
        shopping = app.root.get_screen("shopping")
        shopping.start_session(member)
        app.root.current = "shopping"

        # Saldo im Hintergrund abrufen (nicht blockierend, Fehler werden ignoriert)
        if settings.show_member_balance:
            def _fetch_balance():
                balance = app.sync_manager.get_member_balance(member.id)
                if balance is not None:
                    Clock.schedule_once(lambda _dt: shopping.set_balance(balance), 0)
            threading.Thread(target=_fetch_balance, daemon=True).start()

    def _clear_error(self) -> None:
        self.error_text = ""

    # ------------------------------------------------------------------
    # Tastatur-Shortcuts fuer Entwicklungsmodus
    # ------------------------------------------------------------------

    def on_key_down(self, _window, key, _scancode, _codepoint, _modifiers) -> bool:
        """Wird von Window.bind(on_key_down=...) aufgerufen."""
        if key == ord("r") or key == ord("R"):
            # Ersten gecachten Member simulieren
            from app.local_db import get_session, CachedMember
            with get_session() as db:
                m = db.query(CachedMember).filter(CachedMember.rfid_token.isnot(None)).first()
            if m:
                self.on_rfid_scan(m.rfid_token)
            else:
                self.error_text = "Kein Mitglied im Cache – bitte Server verbinden"
                Clock.schedule_once(lambda _dt: self._clear_error(), 3)
            return True

        if key == ord("f") or key == ord("F"):
            App.get_running_app().sync_manager.force_refresh()
            self.prompt_text = "Cache wird aktualisiert ..."
            Clock.schedule_once(
                lambda _dt: setattr(self, "prompt_text", "Bitte RFID-Karte scannen"), 3
            )
            return True

        return False
