#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Clubfridge Kasse – Installer für Raspberry Pi OS (Bullseye / Bookworm)
#
# Aufruf (als root / mit sudo):
#   curl -fsSL https://install.clubfridge.de | sudo bash
#
# Der Installer:
#   1. Installiert System-Abhängigkeiten (Python, SDL2, …)
#   2. Lädt die Kassen-Software von GitHub
#   3. Richtet eine virtuelle Python-Umgebung ein
#   4. Installiert einen systemd-Service (clubfridge-kasse@<user>)
#   5. Aktiviert den Service für den aktuellen Benutzer
#
# Nach dem Neustart oder "sudo systemctl start clubfridge-kasse@<user>"
# erscheint der Einrichtungs-Assistent auf dem Bildschirm.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Konfiguration ─────────────────────────────────────────────────────────────

REPO_URL="https://github.com/tb59427/clubfridge-kasse"
REPO_BRANCH="main"
INSTALL_DIR="/opt/clubfridge/kasse"
SERVICE_NAME="clubfridge-kasse"
# Benutzer unter dem die Kasse laufen soll (Standard: aktueller SUDO_USER)
SERVICE_USER="${SUDO_USER:-${USER:-pi}}"

# ── Farben ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
step()  { echo -e "\n${CYAN}${BOLD}──${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

# ── Banner ────────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}  ╔════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}  ║${NC}   ${CYAN}club${NC}${BOLD}fridge${NC} Kasse – Installer           ${BOLD}║${NC}"
echo -e "${BOLD}  ╚════════════════════════════════════════════╝${NC}"
echo ""
echo "  Ziel-Verzeichnis : ${INSTALL_DIR}"
echo "  Service-Benutzer  : ${SERVICE_USER}"
echo ""

# ── Root-Check ────────────────────────────────────────────────────────────────

[[ $EUID -eq 0 ]] || error "Bitte mit sudo ausführen: sudo bash install.sh"

# ── System-Pakete ────────────────────────────────────────────────────────────

step "System-Pakete werden installiert…"

apt-get update -qq

apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-mixer-dev \
    libsdl2-ttf-dev \
    libportmidi-dev \
    libswscale-dev \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    zlib1g-dev \
    libgstreamer1.0-dev \
    gstreamer1.0-plugins-base \
    libgl1-mesa-dev \
    libgles2-mesa-dev \
    libffi-dev \
    libssl-dev \
    xorg \
    xserver-xorg-video-fbdev \
    2>/dev/null

info "System-Pakete installiert"

# ── Python-Version prüfen ─────────────────────────────────────────────────────

step "Python-Version wird geprüft…"

PYTHON_BIN="$(command -v python3.12 || command -v python3.11 || command -v python3 || true)"
[[ -n "${PYTHON_BIN}" ]] || error "Python 3 nicht gefunden"

PYTHON_VER="$("${PYTHON_BIN}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
info "Python ${PYTHON_VER} gefunden: ${PYTHON_BIN}"

"${PYTHON_BIN}" -c \
    "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ erforderlich'" \
    || error "Python 3.11 oder neuer wird benötigt. Bitte 'sudo apt install python3.11' ausführen."

# ── App-Verzeichnis vorbereiten ───────────────────────────────────────────────

step "App-Verzeichnis wird vorbereitet…"

mkdir -p "${INSTALL_DIR}"

# ── Kassen-Software herunterladen / aktualisieren ─────────────────────────────

step "Kassen-Software wird heruntergeladen…"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Vorhandene Installation gefunden – wird aktualisiert"
    git -C "${INSTALL_DIR}" fetch --quiet origin "${REPO_BRANCH}"
    git -C "${INSTALL_DIR}" reset --hard "origin/${REPO_BRANCH}" --quiet
else
    info "Klone Repository von ${REPO_URL}…"
    git clone --depth=1 --branch "${REPO_BRANCH}" "${REPO_URL}.git" "${INSTALL_DIR}" --quiet
fi

info "Kassen-Software bereit"

# ── Virtuelle Python-Umgebung ─────────────────────────────────────────────────

step "Python-Umgebung wird eingerichtet…"

VENV="${INSTALL_DIR}/.venv"

if [[ ! -d "${VENV}" ]]; then
    "${PYTHON_BIN}" -m venv "${VENV}"
    info "Virtuelle Umgebung erstellt: ${VENV}"
fi

info "Abhängigkeiten werden installiert (kann einige Minuten dauern)…"
"${VENV}/bin/pip" install --upgrade pip --quiet
"${VENV}/bin/pip" install -e "${INSTALL_DIR}[pi]" --quiet

info "Python-Abhängigkeiten installiert"

# ── Berechtigungen setzen ─────────────────────────────────────────────────────

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

# ── systemd-Service installieren ─────────────────────────────────────────────

step "systemd-Service wird eingerichtet…"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}@.service"

# Service-Template aus dem Repo kopieren (falls vorhanden), sonst erzeugen
if [[ -f "${INSTALL_DIR}/deploy/clubfridge-kasse.service" ]]; then
    # Umbenennen zu Template-Format (@)
    cp "${INSTALL_DIR}/deploy/clubfridge-kasse.service" "${SERVICE_FILE}"
    # %i ist der Instance-Parameter (Benutzername)
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=${INSTALL_DIR}|g" "${SERVICE_FILE}"
    sed -i "s|ExecStart=.*|ExecStart=${VENV}/bin/python main.py|g" "${SERVICE_FILE}"
else
    # Service-Datei inline erzeugen
    cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Clubfridge Kasse
After=network-online.target graphical-session.target
Wants=network-online.target

[Service]
Type=simple
User=%i
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/%i/.Xauthority
Environment=KIVY_NO_ENV_CONFIG=1
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python main.py
Restart=always
RestartSec=5
StartLimitBurst=3
StartLimitIntervalSec=60
StandardOutput=journal
StandardError=journal
SyslogIdentifier=clubfridge-kasse

[Install]
WantedBy=graphical-session.target
EOF
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}@${SERVICE_USER}"

info "Service aktiviert: ${SERVICE_NAME}@${SERVICE_USER}"

# ── Desktop-Autostart (optional, falls kein Display-Manager vorhanden) ────────

AUTOSTART_DIR="/home/${SERVICE_USER}/.config/autostart"
AUTOSTART_FILE="${AUTOSTART_DIR}/clubfridge-kasse.desktop"

if [[ ! -f "${AUTOSTART_FILE}" ]]; then
    step "Desktop-Autostart wird eingerichtet…"
    mkdir -p "${AUTOSTART_DIR}"
    cat > "${AUTOSTART_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=Clubfridge Kasse
Exec=systemctl --user start ${SERVICE_NAME}@${SERVICE_USER}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${AUTOSTART_DIR}"
    info "Desktop-Autostart eingerichtet"
fi

# ── Abschluss ─────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}  Installation abgeschlossen!${NC}"
echo ""
echo "  Nächste Schritte:"
echo ""
echo "  1. Service starten:"
echo "     sudo systemctl start ${SERVICE_NAME}@${SERVICE_USER}"
echo ""
echo "  2. Der Einrichtungs-Assistent erscheint auf dem Bildschirm."
echo "     Gib Server-URL, Tenant-ID und Setup-Code aus dem Admin-UI ein."
echo "     Alternativ: config.json per USB-Stick einlesen."
echo ""
echo "  3. Nach der Einrichtung startet die Kasse automatisch."
echo ""
echo "  Logs verfolgen:"
echo "     sudo journalctl -fu ${SERVICE_NAME}@${SERVICE_USER}"
echo ""
