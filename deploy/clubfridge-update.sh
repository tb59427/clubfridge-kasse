#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Clubfridge Kasse – Automatisches Software-Update
#
# Wird von clubfridge-update@<user>.service aufgerufen (als root).
# Argument $1: Benutzername des Kassen-Service (z. B. "pi")
#
# Ablauf:
#   1. git fetch – prüft ob neue Commits vorhanden sind
#   2. Wenn ja: git reset --hard, pip install, Service neustarten
#   3. Wenn nein: Abbruch ohne Neustart (kein unnötiger Downtime)
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

INSTALL_DIR="/opt/clubfridge/kasse"
VENV="${INSTALL_DIR}/.venv"
SERVICE_USER="${1:-pi}"
SERVICE_NAME="clubfridge-kasse"
BRANCH="main"

log()  { echo "[clubfridge-update] $*"; }
info() { echo "[clubfridge-update] ✓ $*"; }
warn() { echo "[clubfridge-update] ! $*" >&2; }

PI5_FIX_APPLIED=false

# ------------------------------------------------------------------------------
# Pi 5 GPIO-Fix: rpi-lgpio statt RPi.GPIO (als Funktion, wird ggf. 2x aufgerufen)
# pip install -e .[pi] installiert RPi.GPIO, das auf Pi 5 nicht funktioniert.
# Strategie: python3-lgpio als vorkompiliertes apt-Paket + Symlink ins venv.
# ------------------------------------------------------------------------------
ensure_pi5_gpio() {
    grep -qa "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null || return 0

    # Prüfen ob RPi.GPIO tatsächlich funktioniert (rpi-lgpio liefert ein funktionierendes RPi.GPIO)
    if "${VENV}/bin/python3" -c "import RPi.GPIO; RPi.GPIO.setmode(RPi.GPIO.BCM)" &>/dev/null; then
        return 0
    fi

    log "Pi 5 erkannt: RPi.GPIO funktioniert nicht – installiere rpi-lgpio …"

    # 1. Vorkompiliertes lgpio aus apt holen
    apt-get install -y python3-lgpio -qq 2>/dev/null || true

    # 2. System-lgpio ins venv symlinken (venv hat kein --system-site-packages)
    #    lgpio besteht aus lgpio.py + _lgpio.cpython-3XX-aarch64-linux-gnu.so
    #    Beide Dateien müssen verlinkt werden!
    SYS_SITE=$(python3 -c "import sysconfig; print(sysconfig.get_path('platlib'))" 2>/dev/null) || true
    if [[ -n "$SYS_SITE" ]] && ls "${SYS_SITE}/"*lgpio* &>/dev/null; then
        VENV_SITE=$("${VENV}/bin/python3" -c "import sysconfig; print(sysconfig.get_path('platlib'))")
        for f in "${SYS_SITE}/"*lgpio*; do
            ln -sf "$f" "${VENV_SITE}/"
            log "lgpio verlinkt: $(basename "$f")"
        done
    else
        warn "python3-lgpio nicht verfügbar – GPIO bleibt deaktiviert"
        return 0
    fi

    # 3. RPi.GPIO entfernen, rpi-lgpio ohne lgpio-Dependency installieren
    "${VENV}/bin/pip" uninstall -y RPi.GPIO 2>/dev/null || true
    "${VENV}/bin/pip" install rpi-lgpio --no-deps --quiet
    log "rpi-lgpio für Pi 5 installiert (ersetzt RPi.GPIO)"

    # 4. Verifikation
    if "${VENV}/bin/python3" -c "import RPi.GPIO; RPi.GPIO.setmode(RPi.GPIO.BCM)" &>/dev/null; then
        info "Pi 5 GPIO-Fix verifiziert: RPi.GPIO funktioniert jetzt"
        PI5_FIX_APPLIED=true
    else
        warn "Pi 5 GPIO-Fix fehlgeschlagen – RPi.GPIO funktioniert immer noch nicht"
        # Debug-Info ausgeben
        "${VENV}/bin/python3" -c "import RPi.GPIO; print('RPi.GPIO:', RPi.GPIO.__file__)" 2>&1 || true
        "${VENV}/bin/python3" -c "import lgpio; print('lgpio:', lgpio.__file__)" 2>&1 || true
        ls -la "${VENV_SITE}/"*lgpio* 2>&1 || true
    fi
}

log "Update-Check gestartet ($(date '+%Y-%m-%d %H:%M:%S'))"

# Pi-5-Fix bei jedem Check (einmalige Migration bestehender Geräte)
ensure_pi5_gpio

# Netzwerk kurz abwarten (bei frühem Timer-Start)
if ! git -C "${INSTALL_DIR}" fetch --quiet origin "${BRANCH}" 2>/dev/null; then
    warn "git fetch fehlgeschlagen – kein Netzwerk? Update wird übersprungen."
    exit 0
fi

BEFORE=$(git -C "${INSTALL_DIR}" rev-parse HEAD)
AFTER=$(git -C "${INSTALL_DIR}" rev-parse "origin/${BRANCH}")

if [[ "${BEFORE}" == "${AFTER}" ]]; then
    if [[ "$PI5_FIX_APPLIED" == "true" ]]; then
        log "Pi 5 GPIO-Fix angewendet – Service wird neugestartet"
        systemctl restart "${SERVICE_NAME}@${SERVICE_USER}"
    fi
    info "Kasse ist aktuell (${BEFORE:0:8}). Kein Update nötig."
    exit 0
fi

log "Update verfügbar: ${BEFORE:0:8} → ${AFTER:0:8}"

# Code aktualisieren
git -C "${INSTALL_DIR}" reset --hard "origin/${BRANCH}" --quiet
log "Code aktualisiert"

# Python-Abhängigkeiten aktualisieren (nur wenn sich pyproject.toml geändert hat)
"${VENV}/bin/pip" install -e "${INSTALL_DIR}[pi]" --quiet
log "Abhängigkeiten aktualisiert"

# Pi-5-Fix erneut: pip install -e .[pi] hat RPi.GPIO gerade wieder installiert
ensure_pi5_gpio

# Berechtigungen sicherstellen
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

# Kassen-Service neustarten
systemctl restart "${SERVICE_NAME}@${SERVICE_USER}"

info "Update abgeschlossen. Version: ${AFTER:0:8}. Service neugestartet."
