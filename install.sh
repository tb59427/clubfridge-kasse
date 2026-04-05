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

# --reset: Konfiguration löschen → Einrichtungs-Assistent beim nächsten Start
RESET=false
for arg in "$@"; do
    [[ "${arg}" == "--reset" ]] && RESET=true
done

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
    libffi-dev \
    libssl-dev \
    libmtdev1 \
    || error "System-Pakete konnten nicht installiert werden"

# OpenGL-Pakete: neuere Debian-Versionen (Bookworm+) nutzen libgl-dev/libgles-dev,
# ältere (Bullseye) nutzen libgl1-mesa-dev/libgles2-mesa-dev
if apt-cache show libgl-dev &>/dev/null; then
    apt-get install -y --no-install-recommends libgl-dev libgles-dev \
        || error "OpenGL-Pakete (libgl-dev) konnten nicht installiert werden"
else
    apt-get install -y --no-install-recommends libgl1-mesa-dev libgles2-mesa-dev \
        || error "OpenGL-Pakete (libgl1-mesa-dev) konnten nicht installiert werden"
fi

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

# ── Konfiguration zurücksetzen (--reset) ──────────────────────────────────────

ENV_FILE="${INSTALL_DIR}/.env"

if [[ "${RESET}" == "true" ]]; then
    step "Konfiguration wird zurückgesetzt…"
    rm -f "${ENV_FILE}"
    info "Konfiguration entfernt – Einrichtungs-Assistent erscheint nach dem Start."
elif grep -q "^API_KEY=." "${ENV_FILE}" 2>/dev/null; then
    info "Vorhandene Konfiguration bleibt erhalten."
    warn "Zum Neu-Einrichten (anderer Tenant/Kasse) --reset übergeben:"
    warn "  curl -fsSL https://install.clubfridge.de | sudo bash -s -- --reset"
fi

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
WantedBy=graphical.target
EOF
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}@${SERVICE_USER}"

info "Service aktiviert: ${SERVICE_NAME}@${SERVICE_USER}"

# ── Automatischer Update-Timer einrichten ─────────────────────────────────────

step "Automatischer Update-Timer wird eingerichtet…"

UPDATE_SERVICE="/etc/systemd/system/clubfridge-update@.service"
UPDATE_TIMER="/etc/systemd/system/clubfridge-update@.timer"

# Update-Script ausführbar machen
chmod +x "${INSTALL_DIR}/deploy/clubfridge-update.sh"

# Service und Timer aus Repo kopieren
cp "${INSTALL_DIR}/deploy/clubfridge-update@.service" "${UPDATE_SERVICE}"
cp "${INSTALL_DIR}/deploy/clubfridge-update@.timer"   "${UPDATE_TIMER}"

systemctl daemon-reload
systemctl enable "clubfridge-update@${SERVICE_USER}.timer"
systemctl start  "clubfridge-update@${SERVICE_USER}.timer"

info "Update-Timer aktiv (täglich 03:00 Uhr): clubfridge-update@${SERVICE_USER}.timer"

# ── Desktop-Autostart (optional, falls kein Display-Manager vorhanden) ────────

if [[ "${IS_DESKTOP}" == "true" ]]; then
    # Desktop: Kasse als Desktop-App starten (erbt Wayland/X11 Umgebung)
    # systemd-Service deaktivieren (würde ohne Display-Zugriff laufen)
    systemctl disable "${SERVICE_NAME}@${SERVICE_USER}" 2>/dev/null || true

    AUTOSTART_DIR="/home/${SERVICE_USER}/.config/autostart"
    AUTOSTART_FILE="${AUTOSTART_DIR}/clubfridge-kasse.desktop"
    step "Desktop-Autostart wird eingerichtet…"
    mkdir -p "${AUTOSTART_DIR}"
    cat > "${AUTOSTART_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=Clubfridge Kasse
Exec=${VENV}/bin/python ${INSTALL_DIR}/main.py
Path=${INSTALL_DIR}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Environment=KIVY_NO_ENV_CONFIG=1
EOF
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${AUTOSTART_DIR}"
    info "Desktop-Autostart eingerichtet (Kasse startet als Desktop-App)"
    info "Service deaktiviert (nicht nötig auf Desktop)"
fi

# ── Hardware-Erkennung (informativ) ──────────────────────────────────────────

step "USB-HID-Eingabegeräte werden erkannt…"

BY_ID="/dev/input/by-id"
RFID_FOUND=""
BARCODE_FOUND=""

if [[ -d "${BY_ID}" ]]; then
    # Alle Haupt-Tastatur-Interfaces (event-kbd, keine Sub-Interfaces)
    while IFS= read -r -d '' dev; do
        name="$(basename "${dev}")"
        name_lower="${name,,}"  # zu Kleinbuchstaben

        # RFID-Leser anhand Name-Pattern erkennen
        if [[ -z "${RFID_FOUND}" ]] && echo "${name_lower}" | grep -qE 'rfid|nfc|reader|sycreader|acr|mifare|id_ic'; then
            RFID_FOUND="${dev}"
        # Barcode-Scanner: explizit benannte oder erster verbleibender Eintrag
        elif [[ -z "${BARCODE_FOUND}" ]]; then
            if echo "${name_lower}" | grep -qE 'barcode|scanner|honeywell|zebra|symbol|datalogic'; then
                BARCODE_FOUND="${dev}"
            elif [[ -z "${BARCODE_FOUND}" ]]; then
                BARCODE_FOUND="${dev}"
            fi
        fi
    done < <(find "${BY_ID}" -name "usb-*-event-kbd" -print0 | sort -z)

    if [[ -n "${RFID_FOUND}" ]]; then
        info "RFID-Leser erkannt  : ${RFID_FOUND}"
    else
        warn "Kein RFID-Leser erkannt – ggf. noch nicht angeschlossen."
        warn "RFID_DEVICE manuell in ${INSTALL_DIR}/.env setzen."
    fi

    if [[ -n "${BARCODE_FOUND}" ]]; then
        info "Barcode-Scanner erkannt: ${BARCODE_FOUND}"
    else
        warn "Kein Barcode-Scanner erkannt – ggf. noch nicht angeschlossen."
        warn "BARCODE_DEVICE manuell in ${INSTALL_DIR}/.env setzen."
    fi
else
    warn "/dev/input/by-id nicht vorhanden – Hardware-Erkennung nicht möglich."
    warn "Geräte bitte manuell in ${INSTALL_DIR}/.env eintragen."
fi

echo ""
warn "Die Gerätepfade werden automatisch beim Einrichtungs-Assistenten"
warn "erkannt und in die .env geschrieben. Falls die Geräte jetzt noch"
warn "nicht angeschlossen sind, bitte VOR dem ersten Start anstecken."

# ── Desktop-Erkennung: Display-Rotation anpassen ─────────────────────────

step "Display-Umgebung wird erkannt…"

IS_DESKTOP=false
if dpkg -l 2>/dev/null | grep -qE 'labwc|openbox|lxde|wayfire|lightdm'; then
    IS_DESKTOP=true
fi

if [[ "${IS_DESKTOP}" == "true" ]]; then
    info "Desktop-Umgebung erkannt (Wayland/X11)"
    info "Display-Rotation wird vom Desktop verwaltet → DISPLAY_ROTATION=0"
    # Desktop handhabt die Display-Orientierung → Kivy soll nicht drehen
    if ! grep -q "^DISPLAY_ROTATION=" "${ENV_FILE}" 2>/dev/null; then
        echo "DISPLAY_ROTATION=0" >> "${ENV_FILE}"
    fi
    # Kein Fullscreen auf Desktop (Compositor handhabt Fenstergröße)
    if ! grep -q "^FULLSCREEN=" "${ENV_FILE}" 2>/dev/null; then
        echo "FULLSCREEN=false" >> "${ENV_FILE}"
    fi
else
    info "Headless-Umgebung erkannt (kein Desktop)"
    info "Display-Rotation wird von Kivy verwaltet (Standard: 180° für Touch Display 1)"
    # Rotations-Dialog beim ersten Start (whiptail)
    if [[ -f "${INSTALL_DIR}/deploy/display-rotation-setup.sh" ]]; then
        chmod +x "${INSTALL_DIR}/deploy/display-rotation-setup.sh"
    fi

    # Auto-Login auf TTY1 einrichten (falls noch nicht vorhanden)
    AUTOLOGIN_DIR="/etc/systemd/system/getty@tty1.service.d"
    if [[ ! -f "${AUTOLOGIN_DIR}/autologin.conf" ]]; then
        mkdir -p "${AUTOLOGIN_DIR}"
        cat > "${AUTOLOGIN_DIR}/autologin.conf" <<ALEOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${SERVICE_USER} --noclear %I \$TERM
ALEOF
        info "Auto-Login auf TTY1 eingerichtet"
    fi

    # .bash_profile: Rotations-Dialog + Console-Echo deaktivieren
    BASH_PROFILE="/home/${SERVICE_USER}/.bash_profile"
    cat > "${BASH_PROFILE}" <<'BPEOF'
# Display-Rotation beim ersten Start (nur auf TTY1)
if [ "$(tty)" = "/dev/tty1" ] && [ ! -f /opt/clubfridge/kasse/.display_rotation_confirmed ]; then
    /opt/clubfridge/kasse/deploy/display-rotation-setup.sh
fi
# Console-Echo deaktivieren und Shell blockieren damit Kivy exklusiv läuft
if [ "$(tty)" = "/dev/tty1" ]; then
    stty -echo 2>/dev/null
    exec sleep infinity
fi
BPEOF
    chown "${SERVICE_USER}:${SERVICE_USER}" "${BASH_PROFILE}"
    info ".bash_profile mit Rotations-Dialog eingerichtet"

    # Kasse-Service wartet auf Rotations-Bestätigung
    OVERRIDE_DIR="/etc/systemd/system/${SERVICE_NAME}@.service.d"
    mkdir -p "${OVERRIDE_DIR}"
    cat > "${OVERRIDE_DIR}/wait-rotation.conf" <<'WREOF'
[Service]
ExecStartPre=/bin/bash -c 'while [ ! -f /opt/clubfridge/kasse/.display_rotation_confirmed ]; do sleep 1; done'
WREOF
    systemctl daemon-reload
    info "Service wartet auf Display-Rotations-Bestätigung"
fi

# ── WiFi: Radio aktivieren + Regulatory Domain DE ────────────────────────

step "WiFi-Konfiguration…"

mkdir -p /etc/default
echo 'REGDOMAIN=DE' > /etc/default/crda

# wifi-enable Service (Radio on + Regulatory Domain beim Boot)
if [[ ! -f /etc/systemd/system/wifi-enable.service ]]; then
    cat > /etc/systemd/system/wifi-enable.service <<'WIFIEOF'
[Unit]
Description=Enable WiFi radio and set regulatory domain
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/bin/nmcli radio wifi on
ExecStart=/usr/sbin/iw reg set DE
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
WIFIEOF
    systemctl daemon-reload
    systemctl enable wifi-enable.service
    info "WiFi-Enable Service eingerichtet"
else
    info "WiFi-Enable Service bereits vorhanden"
fi

# ── Abschluss ─────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}  Installation abgeschlossen!${NC}"
echo ""
echo "  Nächste Schritte:"
echo ""
echo "  1. RFID-Leser und Barcode-Scanner per USB anschließen (falls noch nicht geschehen)"
echo ""
if [[ "${IS_DESKTOP}" == "true" ]]; then
echo "  2. System neu starten (oder ab-/anmelden):"
echo "     sudo reboot"
echo ""
echo "  3. Die Kasse startet automatisch nach dem Login."
echo "     Der Einrichtungs-Assistent erscheint auf dem Bildschirm."
echo "     Gib Server-URL, Tenant-ID und Setup-Code aus dem Admin-UI ein."
else
echo "  2. Service starten:"
echo "     sudo systemctl start ${SERVICE_NAME}@${SERVICE_USER}"
echo ""
echo "  3. Der Einrichtungs-Assistent erscheint auf dem Bildschirm."
echo "     Gib Server-URL, Tenant-ID und Setup-Code aus dem Admin-UI ein."
echo "     Alternativ: config.json per USB-Stick einlesen."
fi
echo ""
echo "  Nach der Einrichtung startet die Kasse automatisch."
echo "  Gerätepfade werden automatisch erkannt und in .env gespeichert."
echo ""
echo "  Neu einrichten (anderer Tenant oder neue Kasse):"
echo "     curl -fsSL https://install.clubfridge.de | sudo bash -s -- --reset"
echo ""
echo "  Logs verfolgen:"
echo "     sudo journalctl -fu ${SERVICE_NAME}@${SERVICE_USER}"
echo ""
