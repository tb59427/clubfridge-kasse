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

from app.provision import detect_input_devices, find_usb_config, provision_with_token, write_env

log = logging.getLogger(__name__)

Builder.load_string("""
#:kivy 2.3

# Kompaktes 2-Spalten-Layout für 7" RPi-Touchscreen (800×480).
# Links: WLAN-Einrichtung, Rechts: Kassen-Einrichtung.

<SetupScreen>:
    canvas.before:
        Color:
            rgba: 0.067, 0.067, 0.067, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        padding: [20, 10, 20, 10]

        # ── Header ────────────────────────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 30

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
                text: 'Kasse einrichten'
                font_size: 15
                color: 0.78, 0.78, 0.78, 1
                size_hint_x: None
                width: 190
                halign: 'right'
                valign: 'middle'
                text_size: self.width, self.height

        # ── 2-Spalten-Bereich ─────────────────────────────────────────
        BoxLayout:
            orientation: 'horizontal'
            spacing: 20
            size_hint_y: 1

            # ── Linke Spalte: WLAN ────────────────────────────────────
            BoxLayout:
                orientation: 'vertical'
                size_hint_x: 0.38
                padding: [0, 6, 0, 0]

                Label:
                    text: '[b]WLAN[/b]'
                    markup: True
                    font_size: 14
                    color: 0.58, 0.58, 0.58, 1
                    size_hint_y: None
                    height: 22
                    halign: 'left'
                    text_size: self.width, None

                # SSID
                Label:
                    text: 'Netzwerkname (SSID)'
                    font_size: 11
                    color: 0.48, 0.48, 0.48, 1
                    size_hint_y: None
                    height: 16
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: wifi_ssid_input
                    text: root.wifi_ssid_text
                    hint_text: 'MeinWLAN'
                    font_size: 15
                    size_hint_y: None
                    height: 38
                    multiline: False
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [10, 8, 10, 0]
                    on_text: root.wifi_ssid_text = self.text

                Widget:
                    size_hint_y: None
                    height: 4

                # Passwort
                Label:
                    text: 'WLAN-Passwort'
                    font_size: 11
                    color: 0.48, 0.48, 0.48, 1
                    size_hint_y: None
                    height: 16
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: wifi_pass_input
                    text: root.wifi_pass_text
                    hint_text: 'Passwort'
                    font_size: 15
                    size_hint_y: None
                    height: 38
                    multiline: False
                    password: True
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [10, 8, 10, 0]
                    on_text: root.wifi_pass_text = self.text

                Widget:
                    size_hint_y: None
                    height: 8

                Button:
                    text: 'WLAN verbinden'
                    font_size: 14
                    size_hint_y: None
                    height: 40
                    background_normal: ''
                    background_color: 0.18, 0.26, 0.42, 1
                    on_press: root.connect_wifi()

                Widget:
                    size_hint_y: 1

                Button:
                    text: 'USB-Stick suchen'
                    font_size: 13
                    size_hint_y: None
                    height: 36
                    background_normal: ''
                    background_color: 0.15, 0.15, 0.15, 1
                    on_press: root.try_usb()

            # ── Trennlinie ────────────────────────────────────────────
            Widget:
                size_hint_x: None
                width: 1
                canvas:
                    Color:
                        rgba: 0.25, 0.25, 0.25, 1
                    Rectangle:
                        pos: self.pos
                        size: self.size

            # ── Rechte Spalte: Kassen-Einrichtung ─────────────────────
            BoxLayout:
                orientation: 'vertical'
                size_hint_x: 0.62
                padding: [0, 6, 0, 0]

                Label:
                    text: '[b]Kasseneinrichtung[/b]'
                    markup: True
                    font_size: 14
                    color: 0.58, 0.58, 0.58, 1
                    size_hint_y: None
                    height: 22
                    halign: 'left'
                    text_size: self.width, None

                # Server-URL
                Label:
                    text: 'Server-URL'
                    font_size: 11
                    color: 0.48, 0.48, 0.48, 1
                    size_hint_y: None
                    height: 16
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: server_url_input
                    text: root.server_url_text
                    font_size: 15
                    size_hint_y: None
                    height: 38
                    multiline: False
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [10, 8, 10, 0]
                    on_text: root.server_url_text = self.text

                Widget:
                    size_hint_y: None
                    height: 4

                # Tenant-ID
                Label:
                    text: 'Tenant-ID (Verein)'
                    font_size: 11
                    color: 0.48, 0.48, 0.48, 1
                    size_hint_y: None
                    height: 16
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: tenant_input
                    text: root.tenant_text
                    hint_text: 'meinverein'
                    font_size: 15
                    size_hint_y: None
                    height: 38
                    multiline: False
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [10, 8, 10, 0]
                    on_text: root.tenant_text = self.text

                Widget:
                    size_hint_y: None
                    height: 4

                # Einrichtungscode
                Label:
                    text: 'Einrichtungscode'
                    font_size: 11
                    color: 0.48, 0.48, 0.48, 1
                    size_hint_y: None
                    height: 16
                    halign: 'left'
                    text_size: self.width, None
                TextInput:
                    id: token_input
                    text: root.token_text
                    hint_text: 'XXXX-XXXX-XXXX'
                    font_size: 22
                    size_hint_y: None
                    height: 52
                    multiline: False
                    background_color: 0.12, 0.12, 0.12, 1
                    foreground_color: 0.92, 0.92, 0.92, 1
                    cursor_color: 1.0, 0.42, 0.208, 1
                    padding: [10, 12, 10, 0]
                    on_text: root.token_text = self.text

                Widget:
                    size_hint_y: 1

                Button:
                    text: 'Einrichten'
                    font_size: 18
                    bold: True
                    size_hint_y: None
                    height: 46
                    background_normal: ''
                    background_color: 1.0, 0.42, 0.208, 1
                    on_press: root.do_provision()

        # ── Statuszeile ────────────────────────────────────────────────
        Label:
            text: root.status_text
            font_size: 13
            color: root.status_color
            size_hint_y: None
            height: 22
            halign: 'center'
            text_size: self.width, None
""")


class SetupScreen(Screen):
    status_text = StringProperty("")
    status_color = ListProperty([0.7, 0.7, 0.7, 1])
    server_url_text = StringProperty("https://app.adminv2.clubfridge.com")
    tenant_text = StringProperty("")
    token_text = StringProperty("")
    wifi_ssid_text = StringProperty("")
    wifi_pass_text = StringProperty("")

    def on_enter(self) -> None:
        self._set_status("Bereit – bitte Daten aus dem Admin-UI eingeben.", color="normal")
        # Kurz nach Anzeige automatisch nach USB-Stick suchen (silent)
        Clock.schedule_once(lambda _dt: self._search_usb(silent=True), 0.8)
        # TAB-Navigation zwischen Eingabefeldern
        from kivy.core.window import Window
        Window.bind(on_key_down=self._on_key_down)

    def on_leave(self) -> None:
        from kivy.core.window import Window
        Window.unbind(on_key_down=self._on_key_down)

    def _on_key_down(self, window, key, scancode, codepoint, modifiers) -> bool:
        if key == 9:  # TAB
            fields = [
                self.ids.wifi_ssid_input,
                self.ids.wifi_pass_input,
                self.ids.server_url_input,
                self.ids.tenant_input,
                self.ids.token_input,
            ]
            # Finde aktuelles Feld und springe zum nächsten
            for i, field in enumerate(fields):
                if field.focus:
                    next_field = fields[(i + 1) % len(fields)]
                    field.focus = False
                    next_field.focus = True
                    return True
            # Kein Feld fokussiert → erstes Feld aktivieren
            fields[0].focus = True
            return True
        return False

    def connect_wifi(self) -> None:
        """WLAN-Verbindung über nmcli herstellen."""
        ssid = self.wifi_ssid_text.strip()
        password = self.wifi_pass_text.strip()

        if not ssid:
            self._set_status("Bitte WLAN-Name (SSID) eingeben.", color="error")
            return
        if not password:
            self._set_status("Bitte WLAN-Passwort eingeben.", color="error")
            return

        self._set_status(f"Verbinde mit {ssid}…", color="normal")
        threading.Thread(
            target=self._connect_wifi_bg,
            args=(ssid, password),
            daemon=True,
        ).start()

    def _connect_wifi_bg(self, ssid: str, password: str) -> None:
        """WLAN-Verbindung im Hintergrund-Thread."""
        import subprocess
        try:
            # NetworkManager Connection-Datei direkt schreiben (braucht keine PolicyKit-Rechte)
            nm_dir = "/etc/NetworkManager/system-connections"
            nm_file = f"{nm_dir}/{ssid}.nmconnection"
            nm_content = (
                f"[connection]\n"
                f"id={ssid}\n"
                f"type=wifi\n"
                f"autoconnect=true\n"
                f"\n"
                f"[wifi]\n"
                f"ssid={ssid}\n"
                f"mode=infrastructure\n"
                f"\n"
                f"[wifi-security]\n"
                f"key-mgmt=wpa-psk\n"
                f"psk={password}\n"
                f"\n"
                f"[ipv4]\n"
                f"method=auto\n"
                f"\n"
                f"[ipv6]\n"
                f"method=auto\n"
            )

            # Schreiben via tee (braucht keine elevated privileges im Pi-Image,
            # da der pi-User über sudoers NOPASSWD hat)
            write_result = subprocess.run(
                ["sudo", "tee", nm_file],
                input=nm_content, capture_output=True, text=True, timeout=5,
            )
            if write_result.returncode != 0:
                raise RuntimeError(f"Konnte {nm_file} nicht schreiben")

            subprocess.run(
                ["sudo", "chmod", "600", nm_file],
                capture_output=True, timeout=5,
            )

            # NetworkManager die neue Verbindung laden lassen
            subprocess.run(
                ["nmcli", "connection", "reload"],
                capture_output=True, timeout=10,
            )

            # Verbindung aktivieren
            result = subprocess.run(
                ["nmcli", "connection", "up", ssid],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                log.info("WLAN verbunden: %s", ssid)
                Clock.schedule_once(
                    lambda _dt: self._set_status(f"WLAN verbunden: {ssid}", color="ok")
                )
            else:
                err = result.stderr.strip() or result.stdout.strip() or "Unbekannter Fehler"
                log.warning("WLAN-Aktivierung: %s", err)
                Clock.schedule_once(
                    lambda _dt: self._set_status(
                        f"WLAN '{ssid}' gespeichert (wird beim nächsten Start genutzt).",
                        color="ok",
                    )
                )
        except subprocess.TimeoutExpired:
            Clock.schedule_once(
                lambda _dt: self._set_status("WLAN-Timeout – bitte SSID und Passwort prüfen.", color="error")
            )
        except Exception as e:
            err_msg = str(e)
            log.error("WLAN-Fehler: %s", err_msg)
            Clock.schedule_once(
                lambda _dt: self._set_status(f"WLAN-Fehler: {err_msg}", color="error")
            )

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
        """Schreibt .env und startet den Prozess neu oder zeigt DeviceIdentScreen."""
        try:
            env_path = write_env(api_url, tenant_slug, api_key)
            log.info("Konfiguration gespeichert: %s", env_path)

            # Prüfe ob Geräte-Erkennung sicher war
            detection = detect_input_devices()
            if not detection.confident and len(detection.all_kbd_devices) >= 2:
                log.info("Geräte-Erkennung unsicher – starte interaktive Identifikation")
                self._set_status("Konfiguration gespeichert – Geräte werden identifiziert…", color="ok")
                Clock.schedule_once(
                    lambda _dt: self._show_device_ident(detection.all_kbd_devices), 1.5
                )
            else:
                self._set_status("Konfiguration gespeichert – Neustart…", color="ok")
                Clock.schedule_once(lambda _dt: _restart_process(), 2.0)
        except Exception as e:
            log.error("Fehler beim Speichern der Konfiguration: %s", e)
            self._set_status(f"Fehler beim Speichern: {e}", color="error")

    def _show_device_ident(self, candidate_devices: list[str]) -> None:
        """Wechselt zum DeviceIdentScreen für interaktive Geräte-Zuordnung."""
        from app.ui.screens.device_ident import DeviceIdentScreen
        sm = self.manager
        if sm is None:
            return
        ident_screen = DeviceIdentScreen(candidate_devices=candidate_devices, name="device_ident")
        sm.add_widget(ident_screen)
        sm.current = "device_ident"

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
