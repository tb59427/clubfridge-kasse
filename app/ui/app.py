"""
KasseApp – Kivy-App-Klasse.

Initialisiert alle Komponenten (SyncManager, Hardware) und
verdrahtet die Callbacks zwischen Hardware und UI-Screens.

Beim ersten Start (keine .env oder api_key leer) wird stattdessen
der SetupScreen angezeigt.
"""
import logging

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import PopMatrix, PushMatrix, Scale
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import NoTransition, ScreenManager

from app.config import settings
from app.provision import is_configured

log = logging.getLogger(__name__)

# Design-Auflösung (UI ist für 800x480 gebaut)
DESIGN_W, DESIGN_H = 800, 480


class ScaledContainer(FloatLayout):
    """Container der die UI auf 800x480 rendert und auf die native Auflösung hochskaliert.

    Touch-Events werden automatisch zurückskaliert, damit sie korrekt ankommen.
    """

    def __init__(self, scale_factor: float, **kwargs):
        super().__init__(**kwargs)
        self._scale = scale_factor
        with self.canvas.before:
            PushMatrix()
            Scale(scale_factor, scale_factor, 1)
        with self.canvas.after:
            PopMatrix()

    def _transform_touch(self, touch):
        """Touch-Koordinaten von nativer Auflösung in Design-Auflösung umrechnen."""
        touch.push()
        touch.apply_transform_2d(lambda x, y: (x / self._scale, y / self._scale))

    def _restore_touch(self, touch):
        touch.pop()

    def on_touch_down(self, touch):
        self._transform_touch(touch)
        ret = super().on_touch_down(touch)
        self._restore_touch(touch)
        return ret

    def on_touch_move(self, touch):
        self._transform_touch(touch)
        ret = super().on_touch_move(touch)
        self._restore_touch(touch)
        return ret

    def on_touch_up(self, touch):
        self._transform_touch(touch)
        ret = super().on_touch_up(touch)
        self._restore_touch(touch)
        return ret



def _wrap_scaled(sm: ScreenManager) -> ScaledContainer | ScreenManager:
    """Skaliert den ScreenManager hoch wenn das Display größer als 800x480 ist.

    Auf dem Touch Display 1 (800x480) wird nichts skaliert.
    Auf dem Touch Display 2 (1280x720 → 720x1280 nativ, nach Rotation) wird
    die gesamte UI proportional hochskaliert, damit sie gleich aussieht.
    """
    native_w, native_h = Window.size
    if native_w <= DESIGN_W and native_h <= DESIGN_H:
        return sm  # 800x480 oder kleiner — keine Skalierung nötig

    # Nur auf dem Pi skalieren (Framebuffer ohne X11, oder X11 im Fullscreen).
    # Auf Mac/PC im Fenstermodus (Entwicklung) nicht skalieren.
    import sys
    if sys.platform != "linux":
        return sm

    # Skalierung so wählen, dass das Display komplett ausgefüllt wird.
    # Design-Breite an das native Seitenverhältnis anpassen.
    scale = native_h / DESIGN_H
    adjusted_w = int(native_w / scale)
    log.info("Display-Skalierung: %dx%d → %.2fx (Design: %dx%d)",
             native_w, native_h, scale, adjusted_w, DESIGN_H)

    sm.size_hint = (None, None)
    sm.size = (adjusted_w, DESIGN_H)

    container = ScaledContainer(scale_factor=scale)
    container.add_widget(sm)
    return container


class KasseApp(App):
    title = "Clubfridge Kasse"

    def build(self):
        # ── Hintergrund-Farbe ──────────────────────────────────────────
        Window.clearcolor = (0.067, 0.067, 0.067, 1)

        # ── Tastatur-Shortcuts (Entwicklungsmodus) ─────────────────────
        Window.bind(on_key_down=self._on_key_down)

        # ── Display-Rotation: beim allerersten Start ─────────────────
        from app.display_rotation import has_saved_rotation
        if not is_configured() and not has_saved_rotation():
            import sys
            if sys.platform == "linux":
                log.info("Keine Rotation gespeichert – Display-Drehen-Dialog wird angezeigt")
                from app.ui.screens.rotation import RotationScreen
                sm = ScreenManager()
                sm.add_widget(RotationScreen(name="rotation"))
                return _wrap_scaled(sm)

        # ── Setup-Modus: Kasse noch nicht konfiguriert ─────────────────
        if not is_configured():
            log.info("Keine Konfiguration gefunden – Einrichtungs-Assistent wird gestartet")
            from app.ui.screens.setup import SetupScreen
            sm = ScreenManager()
            sm.add_widget(SetupScreen(name="setup"))
            return _wrap_scaled(sm)

        # ── Normal-Modus ───────────────────────────────────────────────
        from app.hardware.barcode import BarcodeScanner
        from app.hardware.lock import create_lock
        from app.hardware.rfid import RFIDReader
        from app.local_db import get_cached_lock_config
        from app.sync import SyncManager
        from app.ui.screens.idle import IdleScreen
        from app.ui.screens.shopping import ShoppingScreen

        from app.sse_listener import SSEListener

        self.sync_manager = SyncManager()
        self.sse_listener = SSEListener()

        # Lock-Treiber: Server-Config > .env-Fallback > NoopLock
        cached = get_cached_lock_config()
        if cached:
            self.lock = create_lock(
                lock_type=cached["lock_type"],
                host=cached.get("lock_host"),
                gpio_pin=cached.get("lock_gpio_pin"),
                open_duration_ms=cached.get("lock_open_duration_ms", 3000),
            )
        elif settings.has_relay:
            self.lock = create_lock(
                "gpio",
                gpio_pin=settings.relay_gpio_pin,
                open_duration_ms=settings.relay_open_duration_ms,
            )
        else:
            self.lock = create_lock(None)

        self.rfid_reader = RFIDReader(
            device_path=settings.rfid_device,
            on_scan=self._on_rfid_scan,
        )

        self.barcode_scanner = BarcodeScanner(
            device_path=settings.barcode_device,
            on_scan=self._on_barcode_scan,
        )

        sm = ScreenManager(transition=NoTransition())
        sm.add_widget(IdleScreen(name="idle"))
        sm.add_widget(ShoppingScreen(name="shopping"))
        return _wrap_scaled(sm)

    @property
    def screen_manager(self) -> ScreenManager:
        """Gibt den ScreenManager zurück (auch wenn in einen Scale-Container gewrappt)."""
        root = self.root
        if isinstance(root, ScreenManager):
            return root
        # Gewrappt in ScaledContainer → erstes Kind ist der ScreenManager
        for child in root.children:
            if isinstance(child, ScreenManager):
                return child
        return root  # Fallback

    def on_start(self) -> None:
        if not hasattr(self, "sync_manager"):
            # Setup-Modus: keine Hardware/Sync starten
            return
        self.sync_manager.start()
        self.rfid_reader.start()
        self.barcode_scanner.start()
        self.sse_listener.start()
        log.info("KasseApp gestartet (Tenant: %s)", settings.tenant_slug)

    def on_stop(self) -> None:
        if not hasattr(self, "sync_manager"):
            return
        self.sync_manager.stop()
        self.rfid_reader.stop()
        self.barcode_scanner.stop()
        self.sse_listener.stop()
        self.lock.cleanup()
        log.info("KasseApp beendet")

    # ------------------------------------------------------------------
    # Hardware-Callbacks → aktiven Screen weiterleiten
    # ------------------------------------------------------------------

    def _on_rfid_scan(self, token: str) -> None:
        current = self.screen_manager.current
        if current == "idle":
            self.screen_manager.get_screen("idle").on_rfid_scan(token)
        # Im Shopping-Screen RFID ignorieren (Mitglied bereits erkannt)

    def _on_barcode_scan(self, barcode: str) -> None:
        current = self.screen_manager.current
        if current == "shopping":
            self.screen_manager.get_screen("shopping").on_barcode_scan(barcode)
        # Im Idle-Screen Barcodes ignorieren

    # ------------------------------------------------------------------
    # Tastatur-Delegation an aktiven Screen (Entwicklungsmodus)
    # ------------------------------------------------------------------

    def _on_key_down(self, window, key, scancode, codepoint, modifiers) -> bool:
        current_screen = self.screen_manager.get_screen(self.screen_manager.current)
        if hasattr(current_screen, "on_key_down"):
            return current_screen.on_key_down(window, key, scancode, codepoint, modifiers)
        return False
