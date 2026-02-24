from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Cloud Server
    server_url: str = "http://localhost:8000"
    tenant_slug: str = "demo"
    api_key: str = ""  # Format: {register_id}.{secret}

    # Hardware – evdev-Gerätepfade (Linux/Pi)
    rfid_device: str = "/dev/input/event0"
    barcode_device: str = "/dev/input/event1"

    # Feature-Flags (vom Server via /config befüllt, lokal gecacht)
    show_member_balance: bool = False

    # Magnetschloss-Relais (GPIO, optional)
    has_relay: bool = False
    relay_gpio_pin: int = 18
    relay_open_duration_ms: int = 3000

    # Lokale SQLite-Datenbank
    local_db_path: str = "kasse_local.db"

    # Sync-Einstellungen
    sync_interval_seconds: int = 60
    cache_refresh_interval_seconds: int = 300

    # Display
    fullscreen: bool = False
    window_width: int = 800
    window_height: int = 480


settings = Settings()
