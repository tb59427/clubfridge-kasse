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

# --reset:        Konfiguration komplett löschen (.env weg, Setup-Wizard neu)
# --reconfigure:  Display-/Service-Konfiguration neu anwenden, aber Server-URL,
#                 Tenant und API-Key beibehalten — gut zum Reparieren einer
#                 fehlerhaften Installation, ohne die Kasse neu zu provisionieren.
RESET=false
RECONFIGURE=false
for arg in "$@"; do
    [[ "${arg}" == "--reset" ]] && RESET=true
    [[ "${arg}" == "--reconfigure" ]] && RECONFIGURE=true
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

# ── Logging ──────────────────────────────────────────────────────────────

LOGFILE="/var/log/clubfridge-install.log"
exec > >(tee -a "${LOGFILE}") 2>&1
echo "── Install gestartet: $(date -Iseconds) ──"

# ── Desktop-Erkennung (früh, wird überall im Script gebraucht) ──────────────

IS_DESKTOP=false
if command -v labwc >/dev/null 2>&1 || command -v openbox >/dev/null 2>&1 || systemctl is-active --quiet lightdm 2>/dev/null; then
    IS_DESKTOP=true
fi

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

IS_UPDATE=false
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Vorhandene Installation gefunden – wird aktualisiert"
    IS_UPDATE=true
    # safe.directory: install.sh läuft als root, Repo gehört SERVICE_USER
    git -c "safe.directory=${INSTALL_DIR}" -C "${INSTALL_DIR}" fetch --quiet origin "${REPO_BRANCH}"
    git -c "safe.directory=${INSTALL_DIR}" -C "${INSTALL_DIR}" reset --hard "origin/${REPO_BRANCH}" --quiet
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

# ── Update-Modus: bestehende Installation, kein --reset/--reconfigure ──────
# Code + Abhängigkeiten sind aktualisiert. Service-Datei, USB-/Display-/WiFi-
# Konfiguration bleiben unverändert (die gehören zum Erst-Install und können
# vom Anwender händisch angepasst worden sein). Mit --reconfigure läuft
# install.sh komplett durch (für reparaturbedürftige Installationen), die
# .env wird dabei gemerged statt gelöscht.
if [[ "${IS_UPDATE}" == "true" && "${RESET}" != "true" && "${RECONFIGURE}" != "true" ]]; then
    if systemctl is-active --quiet "${SERVICE_NAME}@${SERVICE_USER}"; then
        info "Kassen-Service wird mit der neuen Version neu gestartet…"
        systemctl restart "${SERVICE_NAME}@${SERVICE_USER}"
    fi
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "  Update abgeschlossen. Konfiguration und Cache bleiben erhalten."
    echo "  Komplett-Reinstall der Konfig: bash -s -- --reconfigure"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    exit 0
fi
if [[ "${RECONFIGURE}" == "true" ]]; then
    info "--reconfigure: Display-/Service-Konfig wird neu angewendet (Server-Daten bleiben)"
fi

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
# Service nur auf Headless aktivieren — Desktop nutzt Autostart
if [[ "${IS_DESKTOP}" != "true" ]]; then
    systemctl enable "${SERVICE_NAME}@${SERVICE_USER}"
    info "Service aktiviert: ${SERVICE_NAME}@${SERVICE_USER}"
else
    info "Service-Datei installiert (wird auf Desktop nicht automatisch gestartet)"
fi

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

# Desktop-Autostart-Datei (von älteren Installationen) entfernen — wir nutzen
# einheitlich den Service-Mode (siehe Display-Konfiguration unten).
rm -f "/home/${SERVICE_USER}/.config/autostart/clubfridge-kasse.desktop" 2>/dev/null || true

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

# ── Pi-Modell + Display erkennen ──────────────────────────────────────────

step "Pi-Modell und Display werden erkannt…"

PI_MODEL_RAW=""
[[ -r /proc/device-tree/model ]] && PI_MODEL_RAW="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
PI_MODEL="unknown"
case "${PI_MODEL_RAW}" in
    *"Pi 3"*) PI_MODEL="pi3" ;;
    *"Pi 4"*) PI_MODEL="pi4" ;;
    *"Pi 5"*) PI_MODEL="pi5" ;;
esac
info "Pi-Modell: ${PI_MODEL_RAW:-unbekannt} (Variante: ${PI_MODEL})"

DSI_MODE=$(cat /sys/class/drm/card*-DSI*/modes 2>/dev/null | head -1)
DISPLAY_TYPE="other"
case "${DSI_MODE}" in
    "720x1280") DISPLAY_TYPE="td2"; info "Touch Display 2 erkannt (720x1280, DSI)" ;;
    "800x480")  DISPLAY_TYPE="td1"; info "Touch Display 1 erkannt (800x480, DSI)" ;;
    "")         info "Kein DSI-Display erkannt (HDMI oder anderes Display)" ;;
    *)          info "DSI-Display erkannt: ${DSI_MODE}" ;;
esac

# ── Display-Konfiguration (vereinheitlicht: immer Service-Mode) ──────────
#
# Egal ob Desktop oder Lite installiert wurde — die Kasse läuft im Service-
# Mode mit modell-spezifischer Hardware-Rotation. Pi-OS-Desktop wird
# (falls vorhanden) deaktiviert, damit die Kasse das Display exklusiv via
# KMSDRM bekommt. Kompatibel zum Golden-Image-Verhalten.

step "Display-Umgebung wird konfiguriert…"

BOOT_CONFIG="/boot/firmware/config.txt"
CMDLINE="/boot/firmware/cmdline.txt"

# Desktop-Manager deaktivieren falls vorhanden
if [[ "${IS_DESKTOP}" == "true" ]]; then
    systemctl disable lightdm 2>/dev/null || true
    systemctl set-default multi-user.target 2>/dev/null || true
    info "Desktop-Modus deaktiviert (multi-user.target, kein Display-Manager)"
fi

# Service-Override: SDL2 nutzt KMSDRM (kein X11/Wayland verfügbar)
OVERRIDE_DIR="/etc/systemd/system/${SERVICE_NAME}@.service.d"
mkdir -p "${OVERRIDE_DIR}"
cat > "${OVERRIDE_DIR}/kmsdrm.conf" <<'KMSEOF'
[Service]
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=KIVY_NO_ENV_CONFIG=1
KMSEOF

# .display_rotation_confirmed anlegen (kein Whiptail-Dialog mehr nötig)
touch "${INSTALL_DIR}/.display_rotation_confirmed"
chown "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/.display_rotation_confirmed"

# .env: existing-merge — bestehende DISPLAY_ROTATION/FULLSCREEN/INVERT_TOUCH
# nicht blind überschreiben, sondern modellspezifisch setzen.
touch "${ENV_FILE}"

set_env_var() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "${ENV_FILE}"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
    else
        echo "${key}=${value}" >> "${ENV_FILE}"
    fi
}

# Konfig pro Pi-Modell + Display
if [[ "${DISPLAY_TYPE}" == "td2" ]]; then
    # TD2 (Pi 4 oder Pi 5): Hardware-Rotation via dtoverlay (Display + Touch zusammen)
    if [[ -f "${BOOT_CONFIG}" ]] && ! grep -q "vc4-kms-dsi-ili9881-7inch" "${BOOT_CONFIG}"; then
        sed -i 's/^display_auto_detect=1/display_auto_detect=0/' "${BOOT_CONFIG}"
        printf "\n# Clubfridge: Touch Display 2\ndtoverlay=vc4-kms-dsi-ili9881-7inch,rotation=270\n" >> "${BOOT_CONFIG}"
    fi
    if [[ -f "${CMDLINE}" ]] && ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
        sed -i 's/$/ fbcon=rotate:1/' "${CMDLINE}"
    fi
    set_env_var "DISPLAY_ROTATION" "270"
    set_env_var "FULLSCREEN" "true"
    info "Display-Konfig: ${PI_MODEL} + TD2 — dtoverlay rotation=270, Kivy 270°"

elif [[ "${DISPLAY_TYPE}" == "td1" && "${PI_MODEL}" == "pi3" ]]; then
    # Pi 3 + TD1: nur fbcon=rotate:2 + Kivy software rotation=180
    if [[ -f "${CMDLINE}" ]] && ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
        sed -i 's/$/ fbcon=rotate:2/' "${CMDLINE}"
    fi
    set_env_var "DISPLAY_ROTATION" "180"
    set_env_var "FULLSCREEN" "true"
    info "Display-Konfig: Pi 3 + TD1 — fbcon=rotate:2, Kivy 180°"

elif [[ "${DISPLAY_TYPE}" == "td1" && "${PI_MODEL}" == "pi4" ]]; then
    # Pi 4 + TD1: DRM rotiert, fbcon zusätzlich für Console
    if [[ -f "${CMDLINE}" ]]; then
        if ! grep -q 'video=DSI-1' "${CMDLINE}"; then
            sed -i 's/$/ video=DSI-1:800x480@60,rotate=180/' "${CMDLINE}"
        fi
        if ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
            sed -i 's/$/ fbcon=rotate:2/' "${CMDLINE}"
        fi
    fi
    if [[ -f "${BOOT_CONFIG}" ]]; then
        sed -i 's/auto_initramfs=1/auto_initramfs=0/' "${BOOT_CONFIG}"
    fi
    set_env_var "DISPLAY_ROTATION" "180"
    set_env_var "FULLSCREEN" "true"
    set_env_var "INVERT_TOUCH" "true"
    info "Display-Konfig: Pi 4 + TD1 — video=DSI-1:rotate=180, fbcon=rotate:2, Kivy 180°, Touch invertiert"

else
    # HDMI oder anderes Display: keine Rotation, Kivy fullscreen
    set_env_var "DISPLAY_ROTATION" "0"
    set_env_var "FULLSCREEN" "true"
    info "Display-Konfig: HDMI/Generic — keine Rotation"
fi
chown "${SERVICE_USER}:${SERVICE_USER}" "${ENV_FILE}"

# Service aktivieren
systemctl enable "${SERVICE_NAME}@${SERVICE_USER}" 2>/dev/null || true
systemctl daemon-reload
info "Service aktiviert: ${SERVICE_NAME}@${SERVICE_USER} (KMSDRM)"

# Auto-Login auf TTY1 (für headless / nach Desktop-Disable)
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

# Whiptail-Dialog ist obsolet — Rotation ist modellspezifisch fest gesetzt.
# Veralteten wait-rotation.conf-Override entfernen falls vorhanden.
rm -f "/etc/systemd/system/${SERVICE_NAME}@.service.d/wait-rotation.conf"
systemctl daemon-reload 2>/dev/null || true

# .bash_profile: Console-Echo aus + Shell blockieren, damit Kivy exklusiv läuft
BASH_PROFILE="/home/${SERVICE_USER}/.bash_profile"
cat > "${BASH_PROFILE}" <<'BPEOF'
# Console-Echo deaktivieren und Shell blockieren damit Kivy exklusiv läuft
if [ "$(tty)" = "/dev/tty1" ]; then
    stty -echo 2>/dev/null
    exec sleep infinity
fi
BPEOF
chown "${SERVICE_USER}:${SERVICE_USER}" "${BASH_PROFILE}"
info ".bash_profile eingerichtet (Console-Sperre auf TTY1)"

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
echo "  Konfiguration reparieren (Display, Service – Tenant/API-Key bleiben):"
echo "     curl -fsSL https://install.clubfridge.de | sudo bash -s -- --reconfigure"
echo ""
echo "  Neu einrichten (anderer Tenant oder neue Kasse, .env wird gelöscht):"
echo "     curl -fsSL https://install.clubfridge.de | sudo bash -s -- --reset"
echo ""
echo "  Logs verfolgen:"
echo "     sudo journalctl -fu ${SERVICE_NAME}@${SERVICE_USER}"
echo ""
