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

log "Update-Check gestartet ($(date '+%Y-%m-%d %H:%M:%S'))"

# Auf Pi 5: rpi-lgpio statt RPi.GPIO installieren (RP1-Chip braucht lgpio-Backend)
# Läuft bei JEDEM Check (nicht nur bei Updates), damit bestehende Pi-5-Geräte
# einmalig automatisch migriert werden.
if grep -qa "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null; then
    if ! "${VENV}/bin/pip" show rpi-lgpio &>/dev/null; then
        # Build-Dependencies für lgpio (C-Extension: SWIG + lgpio-Lib)
        apt-get install -y swig liblgpio-dev --no-install-recommends -qq 2>/dev/null || true
        "${VENV}/bin/pip" uninstall -y RPi.GPIO 2>/dev/null || true
        "${VENV}/bin/pip" install rpi-lgpio --quiet
        log "rpi-lgpio für Pi 5 installiert (ersetzt RPi.GPIO)"
        # Service neustarten damit der neue GPIO-Treiber sofort aktiv wird
        systemctl restart "${SERVICE_NAME}@${SERVICE_USER}"
        info "Service neugestartet (GPIO-Treiber-Wechsel)"
    fi
fi

# Netzwerk kurz abwarten (bei frühem Timer-Start)
if ! git -C "${INSTALL_DIR}" fetch --quiet origin "${BRANCH}" 2>/dev/null; then
    warn "git fetch fehlgeschlagen – kein Netzwerk? Update wird übersprungen."
    exit 0
fi

BEFORE=$(git -C "${INSTALL_DIR}" rev-parse HEAD)
AFTER=$(git -C "${INSTALL_DIR}" rev-parse "origin/${BRANCH}")

if [[ "${BEFORE}" == "${AFTER}" ]]; then
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

# Berechtigungen sicherstellen
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

# Kassen-Service neustarten
systemctl restart "${SERVICE_NAME}@${SERVICE_USER}"

info "Update abgeschlossen. Version: ${AFTER:0:8}. Service neugestartet."
