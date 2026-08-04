"""Admin-Config-Screens: Menue + Bildschirm-Rotation + Eingabegeraete + WLAN.

Aufruf: der ShoppingScreen zeigt bei is_admin ein Zahnrad-Icon oben rechts.
Tap darauf wechselt in "admin_menu". Die Sub-Screens ("admin_display",
"admin_devices", "admin_wifi") haben jeweils einen Zurueck-Button, der ins
Menu zurueckfuehrt; das Menu hat einen Zurueck-Button zum Shopping-Screen.

Alle Sub-Screens rufen ausschliesslich Funktionen aus app.admin_config auf —
kein direktes subprocess/env-Handling in den Screens.
"""

from __future__ import annotations

import logging
from typing import Callable

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput

from app.admin_config import (
    InputDevice,
    WifiNetwork,
    list_input_devices,
    read_env,
    reboot_system,
    set_rotation,
    wifi_connect,
    wifi_scan,
    write_env,
)

log = logging.getLogger(__name__)


BG = (0.067, 0.067, 0.067, 1)
CARD_BG = (0.11, 0.11, 0.11, 1)
ACCENT = (1.0, 0.42, 0.208, 1)
TEXT = (0.92, 0.92, 0.92, 1)
MUTED = (0.6, 0.6, 0.6, 1)


# ---------------------------------------------------------------------------
# Gemeinsame Helfer
# ---------------------------------------------------------------------------

def _bg_rect(widget) -> None:
    from kivy.graphics import Color, Rectangle
    with widget.canvas.before:
        Color(*BG)
        widget._bg = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda *_: setattr(widget._bg, "pos", widget.pos),
                size=lambda *_: setattr(widget._bg, "size", widget.size))


def _header(title: str, on_back: Callable) -> BoxLayout:
    box = BoxLayout(size_hint_y=None, height=56, padding=[10, 6], spacing=10)
    back = Button(
        text="< Zurueck", size_hint_x=None, width=140, font_size=18,
        background_color=(0.2, 0.2, 0.2, 1), color=TEXT,
    )
    back.bind(on_release=lambda *_: on_back())
    box.add_widget(back)
    box.add_widget(Label(
        text=f"[b]{title}[/b]", markup=True, font_size=22, color=ACCENT, halign="left",
    ))
    return box


def _info_popup(title: str, message: str, on_ok: Callable | None = None) -> None:
    layout = BoxLayout(orientation="vertical", padding=20, spacing=15)
    layout.add_widget(Label(text=message, halign="center", valign="middle",
                            text_size=(440, None), color=TEXT))
    btn = Button(text="OK", size_hint_y=None, height=54, font_size=18)
    layout.add_widget(btn)
    popup = Popup(title=title, content=layout, size_hint=(None, None),
                  size=(520, 300), auto_dismiss=False)

    def _dismiss(*_):
        popup.dismiss()
        if on_ok:
            on_ok()
    btn.bind(on_release=_dismiss)
    popup.open()


def _confirm_popup(title: str, message: str, on_yes: Callable) -> None:
    layout = BoxLayout(orientation="vertical", padding=20, spacing=15)
    layout.add_widget(Label(text=message, halign="center", valign="middle",
                            text_size=(440, None), color=TEXT))
    row = BoxLayout(size_hint_y=None, height=54, spacing=10)
    no = Button(text="Abbrechen", font_size=18, background_color=(0.25, 0.25, 0.25, 1))
    yes = Button(text="Ja, weiter", font_size=18, background_color=ACCENT)
    row.add_widget(no)
    row.add_widget(yes)
    layout.add_widget(row)
    popup = Popup(title=title, content=layout, size_hint=(None, None),
                  size=(560, 300), auto_dismiss=False)
    no.bind(on_release=lambda *_: popup.dismiss())
    yes.bind(on_release=lambda *_: (popup.dismiss(), on_yes()))
    popup.open()


# ---------------------------------------------------------------------------
# AdminMenuScreen — die drei Kacheln
# ---------------------------------------------------------------------------

class AdminMenuScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bg_rect(self)

        outer = BoxLayout(orientation="vertical", padding=[16, 10, 16, 16], spacing=12)
        outer.add_widget(_header("Konfiguration", self._back_to_shopping))

        tiles = BoxLayout(orientation="vertical", spacing=12, padding=[20, 20])
        tiles.add_widget(self._tile("Bildschirm", "Drehung / Auflösung", "admin_display"))
        tiles.add_widget(self._tile("Eingabegeraete", "RFID- und Barcode-Scanner", "admin_devices"))
        tiles.add_widget(self._tile("WLAN", "Netzwerk-Verbindung", "admin_wifi"))
        outer.add_widget(tiles)

        self.add_widget(outer)

    def _tile(self, title: str, subtitle: str, target: str) -> Button:
        btn = Button(
            text=f"[b]{title}[/b]\n[size=14][color=999999]{subtitle}[/color][/size]",
            markup=True, halign="center",
            font_size=24, size_hint_y=None, height=110,
            background_color=CARD_BG, color=TEXT,
        )
        btn.bind(on_release=lambda *_: self._go(target))
        return btn

    def _go(self, target: str) -> None:
        App.get_running_app().screen_manager.current = target

    def _back_to_shopping(self) -> None:
        App.get_running_app().screen_manager.current = "shopping"


# ---------------------------------------------------------------------------
# AdminDisplayScreen — Rotation
# ---------------------------------------------------------------------------

class AdminDisplayScreen(Screen):
    current_rotation = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bg_rect(self)
        self._outer = BoxLayout(orientation="vertical", padding=[16, 10, 16, 16], spacing=12)
        self._outer.add_widget(_header("Bildschirm", self._back))
        self._body = BoxLayout(orientation="vertical", padding=[20, 20], spacing=16)
        self._outer.add_widget(self._body)
        self.add_widget(self._outer)

    def on_pre_enter(self) -> None:
        env = read_env()
        try:
            self.current_rotation = int(env.get("DISPLAY_ROTATION", "0"))
        except ValueError:
            self.current_rotation = 0
        self._build_body()

    def _build_body(self) -> None:
        self._body.clear_widgets()
        self._body.add_widget(Label(
            text=f"Aktuelle Drehung: [b]{self.current_rotation}°[/b]",
            markup=True, font_size=22, color=TEXT, size_hint_y=None, height=40,
        ))
        self._body.add_widget(Label(
            text="Neue Drehung auswaehlen und uebernehmen. Der Pi startet danach neu.",
            font_size=15, color=MUTED, size_hint_y=None, height=30,
        ))
        row = BoxLayout(size_hint_y=None, height=80, spacing=10)
        for angle in (0, 180, 270):
            b = Button(
                text=f"{angle}°",
                font_size=28,
                background_color=(ACCENT if angle == self.current_rotation else (0.2, 0.2, 0.2, 1)),
                color=TEXT,
            )
            b.bind(on_release=lambda _btn, a=angle: self._apply(a))
            row.add_widget(b)
        self._body.add_widget(row)
        self._body.add_widget(Label(size_hint_y=1))

    def _apply(self, rotation: int) -> None:
        if rotation == self.current_rotation:
            _info_popup("Keine Aenderung", f"Drehung ist bereits {rotation}°.")
            return
        _confirm_popup(
            "Bildschirm drehen?",
            f"Drehung wird auf {rotation}° gesetzt.\nDer Pi startet danach automatisch neu.",
            on_yes=lambda: self._do_apply(rotation),
        )

    def _do_apply(self, rotation: int) -> None:
        try:
            # Bei 180° auf Pi4+DSI ist INVERT_TOUCH sonst noetig — hier
            # konservativ: wir setzen invert_touch=false bei nicht-180°,
            # bei 180° behalten wir den bestehenden Wert.
            env = read_env()
            invert = env.get("INVERT_TOUCH", "false").lower() == "true"
            if rotation != 180:
                invert = False
            set_rotation(rotation, invert_touch=invert)
        except Exception as e:  # noqa: BLE001
            log.error("Rotation-Aenderung fehlgeschlagen: %s", e, exc_info=True)
            _info_popup("Fehler", f"Konnte Rotation nicht setzen:\n{e}")
            return
        _info_popup(
            "Neustart …",
            f"Drehung auf {rotation}° gespeichert. Der Pi startet jetzt neu.",
            on_ok=reboot_system,
        )

    def _back(self) -> None:
        App.get_running_app().screen_manager.current = "admin_menu"


# ---------------------------------------------------------------------------
# AdminDevicesScreen — RFID + Barcode
# ---------------------------------------------------------------------------

class AdminDevicesScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bg_rect(self)
        self._outer = BoxLayout(orientation="vertical", padding=[16, 10, 16, 16], spacing=12)
        self._outer.add_widget(_header("Eingabegeraete", self._back))
        self._body = BoxLayout(orientation="vertical", padding=[10, 10], spacing=16)
        self._outer.add_widget(self._body)
        self.add_widget(self._outer)

    def on_pre_enter(self) -> None:
        from kivy.uix.gridlayout import GridLayout
        from kivy.uix.scrollview import ScrollView

        env = read_env()
        current_rfid = env.get("RFID_DEVICE", "")
        current_barcode = env.get("BARCODE_DEVICE", "")
        devices = list_input_devices()
        self._body.clear_widgets()

        if not devices:
            self._body.add_widget(Label(
                text="Keine USB-HID-Eingabegeraete gefunden.\n"
                     "Bitte RFID- und Barcode-Scanner anschliessen und Screen erneut oeffnen.",
                font_size=18, color=MUTED, halign="center", valign="middle",
                text_size=(640, None),
            ))
            return

        # Status-Box oben: aktuell zugeordnet
        def _short(path: str) -> str:
            if not path:
                return "(nicht gesetzt)"
            n = path.rsplit("/", 1)[-1]
            if n.startswith("usb-"):
                n = n[4:]
            if n.endswith("-event-kbd"):
                n = n[: -len("-event-kbd")]
            return n.replace("_", " ")

        status = BoxLayout(orientation="vertical", size_hint_y=None, height=76,
                            padding=[12, 8], spacing=4)
        status.add_widget(Label(
            text=f"[b][color=ff9955]RFID[/color][/b]     {_short(current_rfid)}",
            markup=True, font_size=16, color=TEXT, halign="left", valign="middle",
            text_size=(700, 30), size_hint_y=None, height=30,
        ))
        status.add_widget(Label(
            text=f"[b][color=ff9955]Barcode[/color][/b]  {_short(current_barcode)}",
            markup=True, font_size=16, color=TEXT, halign="left", valign="middle",
            text_size=(700, 30), size_hint_y=None, height=30,
        ))
        self._body.add_widget(status)

        # Trennzeile / Ueberschrift
        self._body.add_widget(Label(
            text="Angeschlossene Geraete — Zuweisung antippen:",
            font_size=14, color=MUTED, halign="left", valign="middle",
            text_size=(700, 24), size_hint_y=None, height=24,
        ))

        # Devices in einem ScrollView (auf 480px Display passen sonst nicht viele Zeilen)
        scroll = ScrollView(do_scroll_x=False)
        grid = GridLayout(cols=1, size_hint_y=None, spacing=6, padding=[0, 4])
        grid.bind(minimum_height=grid.setter("height"))

        for dev in devices:
            is_rfid = dev.by_id_path == current_rfid
            is_barcode = dev.by_id_path == current_barcode
            # Row-Hintergrund fuer besseren visuellen Anker
            row = BoxLayout(size_hint_y=None, height=60, spacing=6, padding=[8, 4])
            from kivy.graphics import Color, Rectangle as R
            with row.canvas.before:
                Color(0.14, 0.14, 0.14, 1)
                bg = R(pos=row.pos, size=row.size)
            row.bind(pos=lambda inst, val, r=bg: setattr(r, "pos", inst.pos),
                     size=lambda inst, val, r=bg: setattr(r, "size", inst.size))

            # Name — linksbuendig, faellt bei Bedarf um
            name_lbl = Label(
                text=dev.display_name,
                halign="left", valign="middle",
                font_size=15, color=TEXT,
                shorten=True, shorten_from="right",
            )
            name_lbl.bind(size=lambda inst, val: setattr(inst, "text_size", val))
            row.add_widget(name_lbl)

            # Buttons rechts, gleiche Breite
            b_r = Button(
                text=("RFID ✓" if is_rfid else "→ RFID"),
                size_hint_x=None, width=120, font_size=14,
                background_color=(ACCENT if is_rfid else (0.22, 0.22, 0.22, 1)),
                color=TEXT,
            )
            b_b = Button(
                text=("Barcode ✓" if is_barcode else "→ Barcode"),
                size_hint_x=None, width=130, font_size=14,
                background_color=(ACCENT if is_barcode else (0.22, 0.22, 0.22, 1)),
                color=TEXT,
            )
            b_r.bind(on_release=lambda _btn, d=dev: self._assign("RFID_DEVICE", d))
            b_b.bind(on_release=lambda _btn, d=dev: self._assign("BARCODE_DEVICE", d))
            row.add_widget(b_r)
            row.add_widget(b_b)
            grid.add_widget(row)

        scroll.add_widget(grid)
        self._body.add_widget(scroll)

    def _assign(self, env_key: str, dev: InputDevice) -> None:
        try:
            write_env({env_key: dev.by_id_path})
        except Exception as e:  # noqa: BLE001
            _info_popup("Fehler", f"Konnte .env nicht schreiben:\n{e}")
            return
        _info_popup(
            "Neustart noetig",
            f"{env_key} auf\n{dev.display_name}\ngesetzt. Der Kasse-Service wird neu gestartet.",
            on_ok=reboot_system,
        )

    def _back(self) -> None:
        App.get_running_app().screen_manager.current = "admin_menu"


# ---------------------------------------------------------------------------
# AdminWifiScreen — nmcli
# ---------------------------------------------------------------------------

class AdminWifiScreen(Screen):
    networks: ListProperty = ListProperty([])
    scanning = BooleanProperty(False)
    current_ssid = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        _bg_rect(self)
        self._outer = BoxLayout(orientation="vertical", padding=[16, 10, 16, 16], spacing=12)
        self._outer.add_widget(_header("WLAN", self._back))
        self._body = BoxLayout(orientation="vertical", padding=[10, 10], spacing=10)
        self._outer.add_widget(self._body)
        self.add_widget(self._outer)

    def on_pre_enter(self) -> None:
        self._show_loading()
        Clock.schedule_once(lambda _dt: self._do_scan(), 0.1)

    def _show_loading(self) -> None:
        self._body.clear_widgets()
        self._body.add_widget(Label(
            text="WLAN wird gescannt …",
            font_size=20, color=TEXT,
        ))

    def _do_scan(self) -> None:
        nets = wifi_scan()
        self.networks = nets
        self.current_ssid = next((n.ssid for n in nets if n.in_use), "")
        self._render()

    def _render(self) -> None:
        self._body.clear_widgets()
        header = BoxLayout(size_hint_y=None, height=44, spacing=8)
        header.add_widget(Label(
            text=(f"Verbunden: [b]{self.current_ssid}[/b]" if self.current_ssid
                  else "[color=cccccc]Nicht verbunden[/color]"),
            markup=True, font_size=16, color=TEXT, halign="left",
            text_size=(None, None),
        ))
        rescan = Button(text="Erneut scannen", size_hint_x=None, width=180,
                        background_color=(0.25, 0.25, 0.25, 1))
        rescan.bind(on_release=lambda *_: (self._show_loading(),
                                            Clock.schedule_once(lambda _dt: self._do_scan(), 0.1)))
        header.add_widget(rescan)
        self._body.add_widget(header)

        if not self.networks:
            self._body.add_widget(Label(
                text="Keine WLANs gefunden.\nnmcli evtl. nicht installiert oder\nWLAN-Adapter deaktiviert.",
                font_size=16, color=MUTED, halign="center",
            ))
            return

        for net in self.networks:
            row = BoxLayout(size_hint_y=None, height=54, spacing=8)
            marker = "[color=ff9955]*[/color] " if net.in_use else "  "
            row.add_widget(Label(
                text=f"{marker}{net.ssid}  [color=888888]({net.security}, {net.signal}%)[/color]",
                markup=True, halign="left", valign="middle", font_size=15, color=TEXT,
                text_size=(None, None),
            ))
            b = Button(text=("Verbunden" if net.in_use else "Verbinden"),
                       size_hint_x=None, width=140, font_size=15,
                       background_color=(ACCENT if net.in_use else (0.2, 0.2, 0.2, 1)),
                       disabled=net.in_use)
            b.bind(on_release=lambda _btn, n=net: self._prompt_password(n))
            row.add_widget(b)
            self._body.add_widget(row)

    def _prompt_password(self, net: WifiNetwork) -> None:
        if net.security in ("", "OPEN", "--"):
            _confirm_popup(
                "Offenes WLAN?",
                f"'{net.ssid}' ist unverschluesselt. Trotzdem verbinden?",
                on_yes=lambda: self._do_connect(net.ssid, None),
            )
            return
        layout = BoxLayout(orientation="vertical", padding=20, spacing=12)
        layout.add_widget(Label(
            text=f"Passwort fuer [b]{net.ssid}[/b]", markup=True,
            font_size=18, color=TEXT, size_hint_y=None, height=32,
        ))
        pw = TextInput(password=True, multiline=False, font_size=18,
                       size_hint_y=None, height=46)
        layout.add_widget(pw)
        show = Button(text="Passwort zeigen", size_hint_y=None, height=36,
                      background_color=(0.2, 0.2, 0.2, 1), font_size=13)
        layout.add_widget(show)
        row = BoxLayout(size_hint_y=None, height=54, spacing=10)
        cancel = Button(text="Abbrechen", background_color=(0.25, 0.25, 0.25, 1))
        connect = Button(text="Verbinden", background_color=ACCENT)
        row.add_widget(cancel)
        row.add_widget(connect)
        layout.add_widget(row)

        popup = Popup(title="", separator_height=0, content=layout,
                      size_hint=(None, None), size=(560, 340), auto_dismiss=False)

        def _toggle(*_):
            pw.password = not pw.password
            show.text = "Passwort verbergen" if not pw.password else "Passwort zeigen"
        show.bind(on_release=_toggle)
        cancel.bind(on_release=lambda *_: popup.dismiss())
        connect.bind(on_release=lambda *_: (popup.dismiss(),
                                            self._do_connect(net.ssid, pw.text)))
        popup.open()

    def _do_connect(self, ssid: str, password: str | None) -> None:
        self._body.clear_widgets()
        self._body.add_widget(Label(text=f"Verbinde mit {ssid} …",
                                     font_size=20, color=TEXT))

        def _run(_dt):
            ok, msg = wifi_connect(ssid, password)
            title = "Verbunden" if ok else "Verbindung fehlgeschlagen"
            _info_popup(title, msg, on_ok=lambda: (self._show_loading(),
                                                    Clock.schedule_once(lambda _d: self._do_scan(), 0.5)))
        Clock.schedule_once(_run, 0.2)

    def _back(self) -> None:
        App.get_running_app().screen_manager.current = "admin_menu"
