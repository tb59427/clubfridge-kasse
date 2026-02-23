"""
SetupScreen – Ersteinrichtungs-Assistent.

Wird beim ersten Start angezeigt, wenn noch keine Konfiguration (.env mit api_key)
vorhanden ist. Bietet zwei Einrichtungswege:

  1. Token-Einrichtung: Server-URL + Tenant-ID + Setup-Code eingeben
     → ruft POST /api/v1/kasse/{slug}/provision auf
  2. USB-Stick: config.json automatisch von Boot-Partition oder USB erkennen

Nach erfolgreicher Einrichtung wird der Prozess neu gestartet (os.execv),
damit pydantic-settings die neue .env lädt.
"""

import logging
import os
import sys
import threading

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import ListProperty, StringProperty
from kivy.uix.screenmanager import Screen

from app.provision import find_usb_config, provision_with_token, write_env

log = logging.getLogger(__name__)

Builder.load_string("""
#:kivy 2.3

# Kompaktes Layout für 10" RPi-Touchscreen (1024×600).
# Kein ScrollView – alle Elemente passen auf den Bildschirm.
# Zwei flexible Widget-Spacer zentrieren die Felder vertikal.

<SetupScreen>:
    canvas.before:
        Color:
            rgba: 0.067, 0.067, 0.067, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        padding: [36, 20, 36, 16]

        # ── Header: Wordmark links, Titel rechts ───────────────────────
        BoxLayout:
            size_hint_y: None
            height: 46

            Label:
                text: '[color=ffffff]club[/color][color=ff6b35][b]fridge[/b][/color]'
                markup: True
                font_size: 28
                size_hint_x: None
                width: 170
                halign: 'left'
                valign: 'middle'
                text_size: self.width, self.height

            Widget:

            Label:
                text: 'Kasse einrichten'
                font_size: 20
                color: 0.78, 0.78, 0.78, 1
                size_hint_x: None
                width: 230
                halign: 'right'
                valign: 'middle'
                text_size: self.width, self.height

        # ── Hinweis ────────────────────────────────────────────────────
        Label:
            text: 'Daten aus dem Admin-UI eingeben – oder USB-Stick mit config.json verwenden.'
            font_size: 15
            color: 0.48, 0.48, 0.48, 1
            size_hint_y: None
            height: 26
            halign: 'left'
            text_size: self.width, None

        # ── Flex-Spacer oben (zentriert Felder vertikal) ───────────────
        Widget:
            size_hint_y: 1

        # ── Eingabefelder ──────────────────────────────────────────────
        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: 272
            spacing: 10

            # Server-URL
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: 76
                spacing: 4
                Label:
                    text: 'Server-URL'
                    font_size: 14
                    color: 0.58, 0.58, 0.58, 1
                    size_hint_y: None
                    height: 18
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: server_url_input
                    text: root.server_url_text
                    hint_text: 'https://api.clubfridge.de'
                    font_size: 20
                    size_hint_y: None
                    height: 54
                    multiline: False
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [12, 14, 12, 0]
                    on_text: root.server_url_text = self.text

            # Tenant-ID
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: 76
                spacing: 4
                Label:
                    text: 'Tenant-ID (Verein)'
                    font_size: 14
                    color: 0.58, 0.58, 0.58, 1
                    size_hint_y: None
                    height: 18
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: tenant_input
                    text: root.tenant_text
                    hint_text: 'meinverein'
                    font_size: 20
                    size_hint_y: None
                    height: 54
                    multiline: False
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [12, 14, 12, 0]
                    on_text: root.tenant_text = self.text

            # Einrichtungscode (größere Schrift für Touchscreen-Eingabe)
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: 100
                spacing: 4
                Label:
                    text: 'Einrichtungscode'
                    font_size: 14
                    color: 0.58, 0.58, 0.58, 1
                    size_hint_y: None
                    height: 18
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: token_input
                    text: root.token_text
                    hint_text: 'XXXX-XXXX-XXXX'
                    font_size: 30
                    size_hint_y: None
                    height: 78
                    multiline: False
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [12, 20, 12, 0]
                    on_text: root.token_text = self.text

        # ── Flex-Spacer unten ──────────────────────────────────────────
        Widget:
            size_hint_y: 1

        # ── Buttons ────────────────────────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 68
            spacing: 16

            Button:
                text: 'USB-Stick suchen'
                font_size: 18
                size_hint_x: 0.38
                background_normal: ''
                background_color: 0.18, 0.26, 0.42, 1
                on_press: root.try_usb()

            Button:
                text: 'Einrichten'
                font_size: 22
                bold: True
                size_hint_x: 0.62
                background_normal: ''
                background_color: 1.0, 0.42, 0.208, 1
                on_press: root.do_provision()

        # ── Statuszeile ────────────────────────────────────────────────
        Label:
            text: root.status_text
            font_size: 16
            color: root.status_color
            size_hint_y: None
            height: 32
            halign: 'center'
            text_size: self.width, None
""")


class SetupScreen(Screen):
    status_text = StringProperty("")
    status_color = ListProperty([0.7, 0.7, 0.7, 1])
    server_url_text = StringProperty("")
    tenant_text = StringProperty("")
    token_text = StringProperty("")

    def on_enter(self) -> None:
        self._set_status("Bereit – bitte Daten aus dem Admin-UI eingeben.", color="normal")
        # Kurz nach Anzeige automatisch nach USB-Stick suchen (silent)
        Clock.schedule_once(lambda _dt: self._search_usb(silent=True), 0.8)

    def try_usb(self) -> None:
        """Öffentlicher Button-Handler: USB-Stick suchen (mit Statusmeldung)."""
        self._set_status("USB-Stick wird gesucht…", color="normal")
        Clock.schedule_once(lambda _dt: self._search_usb(silent=False), 0.1)

    def _search_usb(self, silent: bool) -> None:
        config = find_usb_config()
        if config:
            api_url = config.get("api_url", "")
            tenant_slug = config.get("tenant_slug", "")
            api_key = config.get("api_key", "")
            if api_key:
                self._set_status("USB-Konfiguration gefunden – wird angewendet…", color="ok")
                Clock.schedule_once(
                    lambda _dt: self._apply_config(api_url, tenant_slug, api_key), 1.0
                )
            else:
                self.server_url_text = api_url
                self.tenant_text = tenant_slug
                self._set_status("USB-Konfiguration gefunden – bitte Einrichtungscode eingeben.", color="ok")
        elif not silent:
            self._set_status("Keine USB-Konfiguration gefunden.", color="error")

    def do_provision(self) -> None:
        """Token-Einrichtung starten (HTTP-Aufruf im Hintergrund-Thread)."""
        api_url = self.server_url_text.strip()
        tenant = self.tenant_text.strip()
        token = self.token_text.strip()

        if not api_url:
            self._set_status("Bitte Server-URL eingeben.", color="error")
            return
        if not tenant:
            self._set_status("Bitte Tenant-ID eingeben.", color="error")
            return
        if not token:
            self._set_status("Bitte Einrichtungscode eingeben.", color="error")
            return

        self._set_status("Verbinde mit Server…", color="normal")
        threading.Thread(
            target=self._provision_bg,
            args=(api_url, tenant, token),
            daemon=True,
        ).start()

    def _provision_bg(self, api_url: str, tenant: str, token: str) -> None:
        """Läuft im Hintergrund-Thread – kein Kivy-API aufrufen außer via Clock."""
        try:
            data = provision_with_token(api_url, tenant, token)
            Clock.schedule_once(
                lambda _dt: self._apply_config(
                    data["api_url"], data["tenant_slug"], data["api_key"]
                )
            )
        except Exception as e:
            log.error("Provision fehlgeschlagen: %s", e)
            err = _http_error_text(e)
            Clock.schedule_once(
                lambda _dt: self._set_status(f"Fehler: {err}", color="error")
            )

    def _apply_config(self, api_url: str, tenant_slug: str, api_key: str) -> None:
        """Schreibt .env und startet den Prozess neu."""
        try:
            env_path = write_env(api_url, tenant_slug, api_key)
            log.info("Konfiguration gespeichert: %s – Neustart in 2 Sekunden", env_path)
            self._set_status("Konfiguration gespeichert – Neustart…", color="ok")
            Clock.schedule_once(lambda _dt: _restart_process(), 2.0)
        except Exception as e:
            log.error("Fehler beim Speichern der Konfiguration: %s", e)
            self._set_status(f"Fehler beim Speichern: {e}", color="error")

    def _set_status(self, text: str, color: str = "normal") -> None:
        self.status_text = text
        self.status_color = {
            "ok":     [0.2, 0.85, 0.3, 1.0],
            "error":  [1.0, 0.35, 0.2, 1.0],
            "normal": [0.7, 0.70, 0.7, 1.0],
        }.get(color, [0.7, 0.7, 0.7, 1.0])


def _http_error_text(e: Exception) -> str:
    """Menschenlesbarer Fehlertext für HTTP- und Verbindungsfehler."""
    import httpx
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 404:
            return "Ungültiger Code oder falsche Tenant-ID"
        if e.response.status_code == 410:
            return "Code abgelaufen – bitte neuen Code generieren"
        return f"Server-Fehler {e.response.status_code}"
    if isinstance(e, httpx.ConnectError):
        return "Server nicht erreichbar – bitte URL und WLAN prüfen"
    if isinstance(e, httpx.TimeoutException):
        return "Timeout – Server antwortet nicht"
    return str(e)


def _restart_process() -> None:
    """Startet den Python-Prozess neu, damit pydantic-settings die neue .env lädt."""
    log.info("Prozess-Neustart wird eingeleitet…")
    os.execv(sys.executable, [sys.executable] + sys.argv)
