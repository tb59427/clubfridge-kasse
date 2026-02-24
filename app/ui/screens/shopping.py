"""
ShoppingScreen – Kaufvorgang.

Ablauf:
1. Mitglied wird per RFID identifiziert → start_session(member)
2. Produkte werden per Barcode-Scanner hinzugefügt
3. „Kaufen" → Buchung lokal speichern + Sync-Versuch → zurück zum IdleScreen
4. „Abbrechen" → Cart verwerfen → zurück zum IdleScreen

Entwicklungsmodus:
  B        → Erstes Produkt aus dem Cache hinzufügen
  Backspace → Letztes Produkt entfernen
  Enter    → Kaufen bestätigen
  Escape   → Abbrechen
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal

try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("clubfridge-kasse")
except Exception:
    _VERSION = "0.1.0"

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from app.local_db import CachedMember, CachedProduct, find_product_by_barcode

log = logging.getLogger(__name__)

Builder.load_string("""
#:kivy 2.3

<CartItemRow>:
    orientation: 'horizontal'
    size_hint_y: None
    height: 56
    padding: [12, 6, 12, 6]
    spacing: 8

    canvas.before:
        Color:
            rgba: 0.11, 0.11, 0.11, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [8]

    Label:
        text: root.product_name
        font_size: 22
        color: 0.95, 0.95, 0.95, 1
        halign: 'left'
        text_size: self.width, None
        size_hint_x: 0.5

    Label:
        text: str(root.quantity) + ' ×'
        font_size: 22
        color: 0.6, 0.6, 0.6, 1
        size_hint_x: 0.15
        halign: 'center'
        text_size: self.width, None

    Label:
        text: '{:.2f} €'.format(root.unit_price)
        font_size: 22
        color: 0.6, 0.6, 0.6, 1
        size_hint_x: 0.17
        halign: 'right'
        text_size: self.width, None

    Label:
        text: '{:.2f} €'.format(root.quantity * root.unit_price)
        font_size: 22
        bold: True
        color: 0.95, 0.95, 0.95, 1
        size_hint_x: 0.18
        halign: 'right'
        text_size: self.width, None


<ShoppingScreen>:
    canvas.before:
        Color:
            rgba: 0.067, 0.067, 0.067, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        padding: [24, 16, 24, 16]
        spacing: 12

        # ── Header ────────────────────────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 90

            BoxLayout:
                orientation: 'vertical'

                Label:
                    text: 'Hallo, ' + root.member_name + '!'
                    font_size: 32
                    bold: True
                    color: 1.0, 0.42, 0.208, 1
                    halign: 'left'
                    text_size: self.width, None
                    size_hint_y: None
                    height: 52

                Label:
                    text: root.balance_text
                    font_size: 18
                    color: 0.65, 0.65, 0.65, 1
                    halign: 'left'
                    text_size: self.width, None
                    size_hint_y: None
                    height: 28

            Label:
                id: status_label
                text: root.status_text
                color: root.status_color
                font_size: 18
                size_hint_x: None
                width: 150
                halign: 'right'
                valign: 'top'
                text_size: self.width, None

        # ── Artikel-Liste ──────────────────────────────────────────────
        ScrollView:
            id: scroll
            do_scroll_x: False

            BoxLayout:
                id: items_box
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: 6

        # ── Leer-Hinweis ───────────────────────────────────────────────
        Label:
            id: empty_label
            text: 'Barcode scannen, um Produkt hinzuzufügen …'
            font_size: 32
            color: 0.5, 0.5, 0.5, 1
            halign: 'center'
            size_hint_y: None
            height: 160 if root.cart_empty else 0
            opacity: 1 if root.cart_empty else 0

        # ── Fehlermeldung ──────────────────────────────────────────────
        Label:
            id: error_label
            text: root.error_text
            font_size: 22
            color: 1.0, 0.35, 0.2, 1
            halign: 'center'
            text_size: self.width, None
            size_hint_y: None
            height: 32 if root.error_text else 0
            opacity: 1 if root.error_text else 0

        # ── Gesamtbetrag ───────────────────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 50
            padding: [12, 0, 12, 0]

            Label:
                text: 'Gesamt'
                font_size: 32
                color: 0.7, 0.7, 0.7, 1
                halign: 'left'
                text_size: self.width, None

            Label:
                text: '{:.2f} €'.format(root.total_price)
                font_size: 32
                bold: True
                color: 1.0, 0.42, 0.208, 1
                halign: 'right'
                text_size: self.width, None

        # ── Buttons ────────────────────────────────────────────────────
        BoxLayout:
            size_hint_y: None
            height: 80
            spacing: 16

            Button:
                text: 'Abbrechen'
                font_size: 36
                background_color: 0.85, 0.22, 0.22, 1
                on_release: root.cancel()

            Button:
                text: 'Kaufen'
                font_size: 36
                bold: True
                color: 1, 1, 1, 1
                background_normal: ''
                background_down: ''
                background_color: (0.06, 0.50, 0.18, 1) if self.state == 'down' else (0.08, 0.65, 0.24, 1) if not self.disabled else (0.18, 0.30, 0.20, 0.55)
                disabled: root.cart_empty
                on_release: root.confirm_purchase()

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


@dataclass
class CartItem:
    product_id: str
    product_name: str
    quantity: int
    unit_price: Decimal

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class CartItemRow(BoxLayout):
    """Widget-Zeile für einen Cart-Eintrag."""
    product_name = StringProperty()
    quantity = NumericProperty()
    unit_price = NumericProperty()


class ShoppingScreen(Screen):
    member_name = StringProperty("")
    balance_text = StringProperty("")
    total_price = NumericProperty(0.0)
    cart_empty = BooleanProperty(True)
    error_text = StringProperty("")

    status_text = StringProperty("• OFFLINE")
    status_color = [1.0, 0.42, 0.208, 1]
    version_text = StringProperty(f"v{_VERSION}  ·  © 2026 Torsten Beyer")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._member: CachedMember | None = None
        self._cart: list[CartItem] = []

    # ------------------------------------------------------------------
    # Session starten / beenden
    # ------------------------------------------------------------------

    def start_session(self, member: CachedMember) -> None:
        self._member = member
        self._cart = []
        self.member_name = member.name
        self.balance_text = ""
        self.total_price = 0.0
        self.cart_empty = True
        self._rebuild_cart_ui()
        log.info("Shopping-Session gestartet: %s", member.name)

    def set_balance(self, balance) -> None:
        """Wird aus dem Hintergrund-Thread via Clock.schedule_once aufgerufen."""
        self.balance_text = f"Offener Saldo: {balance:.2f} €"

    def _end_session(self) -> None:
        self._member = None
        self._cart = []
        app = App.get_running_app()
        app.root.current = "idle"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_enter(self) -> None:
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
    # Barcode-Callback
    # ------------------------------------------------------------------

    def on_barcode_scan(self, barcode: str) -> None:
        product = find_product_by_barcode(barcode)
        if product is None:
            log.warning("Unbekannter Barcode: %s", barcode)
            self._show_error(f"Unbekannter Barcode: {barcode}")
            return

        # Bereits im Cart? → Menge erhöhen
        for item in self._cart:
            if item.product_id == product.id:
                item.quantity += 1
                self._refresh_totals()
                self._rebuild_cart_ui()
                return

        self._cart.append(CartItem(
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            unit_price=Decimal(str(product.price)),
        ))
        self._refresh_totals()
        self._rebuild_cart_ui()
        log.info("Produkt hinzugefügt: %s", product.name)

    # ------------------------------------------------------------------
    # Kaufen / Abbrechen
    # ------------------------------------------------------------------

    def confirm_purchase(self) -> None:
        if not self._cart or self._member is None:
            return

        items = [
            {
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
            }
            for item in self._cart
        ]
        total = Decimal(str(self.total_price))

        App.get_running_app().sync_manager.submit_booking(
            member_id=self._member.id,
            items=items,
            total_price=total,
        )
        log.info("Buchung abgeschlossen: %s × %d Positionen = %s €",
                 self._member.name, len(items), total)
        self._end_session()

    def cancel(self) -> None:
        log.info("Kaufvorgang abgebrochen: %s", self._member.name if self._member else "?")
        self._end_session()

    # ------------------------------------------------------------------
    # UI-Hilfsmethoden
    # ------------------------------------------------------------------

    def _refresh_totals(self) -> None:
        self.total_price = float(sum(i.line_total for i in self._cart))
        self.cart_empty = len(self._cart) == 0

    def _rebuild_cart_ui(self) -> None:
        box = self.ids.items_box
        box.clear_widgets()
        for item in self._cart:
            row = CartItemRow(
                product_name=item.product_name,
                quantity=item.quantity,
                unit_price=float(item.unit_price),
            )
            box.add_widget(row)
        # Scrolle nach unten
        Clock.schedule_once(lambda _dt: self._scroll_down(), 0.05)

    def _scroll_down(self) -> None:
        self.ids.scroll.scroll_y = 0

    def _show_error(self, msg: str) -> None:
        self.error_text = msg
        Clock.schedule_once(lambda *_: setattr(self, "error_text", ""), 3)

    # ------------------------------------------------------------------
    # Tastatur-Shortcuts für Entwicklungsmodus
    # ------------------------------------------------------------------

    def on_key_down(self, _window, key, _scancode, _codepoint, _modifiers) -> bool:
        if key == ord("b") or key == ord("B"):
            from app.local_db import get_session, CachedProduct
            with get_session() as db:
                p = db.query(CachedProduct).first()
            if p and p.barcode:
                self.on_barcode_scan(p.barcode)
            return True

        if key == 8:  # Backspace → letztes Produkt entfernen
            if self._cart:
                removed = self._cart.pop()
                self._refresh_totals()
                self._rebuild_cart_ui()
                log.debug("Produkt entfernt: %s", removed.product_name)
            return True

        if key == 13:  # Enter → Kaufen
            self.confirm_purchase()
            return True

        if key == 27:  # Escape → Abbrechen
            self.cancel()
            return True

        return False
