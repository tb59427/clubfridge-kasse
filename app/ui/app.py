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
from kivy.uix.screenmanager import FadeTransition, ScreenManager

from app.config import settings
from app.provision import is_configured

log = logging.getLogger(__name__)


class KasseApp(App):
    title = "Clubfridge Kasse"

    def build(self) -> ScreenManager:
        # ── Hintergrund-Farbe ──────────────────────────────────────────
        Window.clearcolor = (0.067, 0.067, 0.067, 1)

        # ── Tastatur-Shortcuts (Entwicklungsmodus) ─────────────────────
        Window.bind(on_key_down=self._on_key_down)

        # ── Setup-Modus: Kasse noch nicht konfiguriert ─────────────────
        if not is_configured():
            log.info("Keine Konfiguration gefunden – Einrichtungs-Assistent wird gestartet")
            from app.ui.screens.setup import SetupScreen
            sm = ScreenManager()
            sm.add_widget(SetupScreen(name="setup"))
            return sm

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

        sm = ScreenManager(transition=FadeTransition(duration=0.15))
        sm.add_widget(IdleScreen(name="idle"))
        sm.add_widget(ShoppingScreen(name="shopping"))
        return sm

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
        current = self.root.current
        if current == "idle":
            self.root.get_screen("idle").on_rfid_scan(token)
        # Im Shopping-Screen RFID ignorieren (Mitglied bereits erkannt)

    def _on_barcode_scan(self, barcode: str) -> None:
        current = self.root.current
        if current == "shopping":
            self.root.get_screen("shopping").on_barcode_scan(barcode)
        # Im Idle-Screen Barcodes ignorieren

    # ------------------------------------------------------------------
    # Tastatur-Delegation an aktiven Screen (Entwicklungsmodus)
    # ------------------------------------------------------------------

    def _on_key_down(self, window, key, scancode, codepoint, modifiers) -> bool:
        current_screen = self.root.get_screen(self.root.current)
        if hasattr(current_screen, "on_key_down"):
            return current_screen.on_key_down(window, key, scancode, codepoint, modifiers)
        return False
