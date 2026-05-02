#!/bin/bash -e
# ──────────────────────────────────────────────────────────────────────────────
# Clubfridge Kasse – pi-gen Build-Stage
#
# Läuft AUSSERHALB des chroot. Befehle im chroot via on_chroot << EOF.
# Dateien ins Image via ${ROOTFS_DIR} Prefix.
#
# VARIANT wird aus der Datei VARIANT gelesen (vom build-image.sh geschrieben):
#   pi3 = Bookworm Lite (Pi 3 + Touch Display 1)
#   pi4 = Bookworm Lite (Pi 4 + Touch Display 1)
#   pi5 = Trixie Lite   (Pi 5 + Touch Display 2)
# ──────────────────────────────────────────────────────────────────────────────

INSTALL_DIR="/opt/clubfridge/kasse"
SERVICE_USER="pi"
VARIANT_FILE="$(dirname "$0")/VARIANT"
VARIANT="$(cat "$VARIANT_FILE" 2>/dev/null || echo "pi5")"

echo "══ Clubfridge Build-Stage: Variante=${VARIANT} ══"

# ── Kasse-Software klonen ────────────────────────────────────────────────────

on_chroot << CHEOF
mkdir -p "${INSTALL_DIR}"
git clone --depth=1 --branch main https://github.com/tb59427/clubfridge-kasse.git "${INSTALL_DIR}"
CHEOF

# ── Python venv + Abhängigkeiten ─────────────────────────────────────────────

on_chroot << CHEOF
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip --quiet
"${INSTALL_DIR}/.venv/bin/pip" install -e "${INSTALL_DIR}[pi]" --quiet
CHEOF

# ── Berechtigungen ───────────────────────────────────────────────────────────

on_chroot << CHEOF
chown -R 1000:1000 "${INSTALL_DIR}"
CHEOF

# ── systemd-Services ─────────────────────────────────────────────────────────

cp "${ROOTFS_DIR}${INSTALL_DIR}/deploy/clubfridge-kasse.service" \
   "${ROOTFS_DIR}/etc/systemd/system/clubfridge-kasse@.service"

cp "${ROOTFS_DIR}${INSTALL_DIR}/deploy/clubfridge-update@.service" \
   "${ROOTFS_DIR}/etc/systemd/system/clubfridge-update@.service"

cp "${ROOTFS_DIR}${INSTALL_DIR}/deploy/clubfridge-update@.timer" \
   "${ROOTFS_DIR}/etc/systemd/system/clubfridge-update@.timer"

chmod +x "${ROOTFS_DIR}${INSTALL_DIR}/deploy/clubfridge-update.sh"

on_chroot << CHEOF
systemctl enable "clubfridge-kasse@${SERVICE_USER}"
systemctl enable "clubfridge-update@${SERVICE_USER}.timer"

# First-Boot-Wizard aufräumen
systemctl disable userconfig.service 2>/dev/null || true
systemctl mask userconfig.service 2>/dev/null || true
CHEOF

# ── WiFi: Regulatory Domain DE + Radio aktivieren ────────────────────────────

mkdir -p "${ROOTFS_DIR}/etc/default"
echo 'REGDOMAIN=DE' > "${ROOTFS_DIR}/etc/default/crda"

# WiFi-Radio beim Boot aktivieren (nmcli im chroot hat keinen Effekt)
cat > "${ROOTFS_DIR}/etc/systemd/system/wifi-enable.service" << 'WIFIEOF'
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

on_chroot << CHEOF
systemctl enable wifi-enable.service
CHEOF

# ── Display-Konfiguration (Hardware-Ebene) ───────────────────────────────────
#
# KEINE Software-Rotation per xrandr/wlr-randr. Rotation läuft pro Variante
# unterschiedlich:
#
# Touch Display 1 (800x480, FT5406):
#   Pi 3 (legacy KMS-Pfad):
#     - fbcon=rotate:2 (rotiert Console)
#     - Kivy software rotation=180 (rotiert Kasse + Touch zusammen)
#   Pi 4 (modern KMS, fbcon=rotate ineffektiv):
#     - video=DSI-1:800x480@60,rotate=180 (DRM rotiert DSI-Plane)
#     - fbcon=rotate:2 (Console-Rotation für die Sekunden vor DRM-Init)
#     - Kivy software rotation=180 zusätzlich (SDL2 bekommt DRM-Rotation
#       in der Praxis nicht zuverlässig durchgereicht)
#     - INVERT_TOUCH=true (DRM rotiert Touch nicht mit)
#
# Touch Display 2 (720x1280, Goodix) — Pi 5:
#   - Display+Touch: dtoverlay=vc4-kms-dsi-ili9881-7inch,rotation=270
#   - Touch dreht automatisch mit
#   - display_auto_detect=0

BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"

if [ -f "${BOOT_CONFIG}" ]; then
    # I2C aktivieren (Touch Display 2 Goodix Controller)
    sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "${BOOT_CONFIG}"

    if [ "${VARIANT}" = "pi5" ]; then
        # display_auto_detect deaktivieren (TD2 braucht manuelles Overlay)
        sed -i 's/^display_auto_detect=1/display_auto_detect=0/' "${BOOT_CONFIG}"
        # ── Touch Display 2: Overlay mit Display+Touch-Rotation ──────
        echo "" >> "${BOOT_CONFIG}"
        echo "# Clubfridge: Touch Display 2 (270° für Landscape)" >> "${BOOT_CONFIG}"
        echo "dtoverlay=vc4-kms-dsi-ili9881-7inch,rotation=270" >> "${BOOT_CONFIG}"
    fi
    # pi3 + pi4: display_auto_detect=1 reicht (TD1 wird automatisch erkannt)
fi

# ── cmdline.txt: Display-Rotation + Console-Rotation + WiFi Regulatory Domain

if [ -f "${CMDLINE}" ]; then
    # WiFi Regulatory Domain DE (Kernel-Parameter)
    if ! grep -q 'cfg80211' "${CMDLINE}"; then
        sed -i 's/$/ cfg80211.ieee80211_regdom=DE/' "${CMDLINE}"
    fi

    if [ "${VARIANT}" = "pi3" ]; then
        # Pi 3 + TD1: nur fbcon=rotate:2; Kivy macht den Rest in Software.
        if ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
            sed -i 's/$/ fbcon=rotate:2/' "${CMDLINE}"
        fi
    elif [ "${VARIANT}" = "pi4" ]; then
        # Pi 4 + TD1: DRM rotiert die Plane, fbcon zusätzlich die Console.
        if ! grep -q 'video=DSI-1' "${CMDLINE}"; then
            sed -i 's/$/ video=DSI-1:800x480@60,rotate=180/' "${CMDLINE}"
        fi
        if ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
            sed -i 's/$/ fbcon=rotate:2/' "${CMDLINE}"
        fi
        # auto_initramfs=0 damit die Firmware die cmdline.txt direkt respektiert
        if [ -f "${BOOT_CONFIG}" ]; then
            sed -i 's/auto_initramfs=1/auto_initramfs=0/' "${BOOT_CONFIG}"
        fi
    else
        # Pi 5 / TD2: Console-Rotation via cmdline.txt (fbcon=rotate:1 = 90° CW)
        if ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
            sed -i 's/$/ fbcon=rotate:1/' "${CMDLINE}"
        fi
    fi
fi

# ── Cloud-init user-data (User vorkonfigurieren, piwiz deaktivieren) ─────────

install -v -m 755 files/user-data "${ROOTFS_DIR}/boot/firmware/user-data"

# ── Auto-Login auf TTY1 ─────────────────────────────────────────────────────

mkdir -p "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d/autologin.conf" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${SERVICE_USER} --noclear %I \$TERM
EOF

# ── Bash-Profile: Console blockieren, damit Kivy exklusiv läuft ─────────────

cat > "${ROOTFS_DIR}/home/${SERVICE_USER}/.bash_profile" << 'BPEOF'
# Console-Echo deaktivieren und Shell blockieren damit Kivy exklusiv läuft
if [ "$(tty)" = "/dev/tty1" ]; then
    stty -echo 2>/dev/null
    exec sleep infinity
fi
BPEOF
chown 1000:1000 "${ROOTFS_DIR}/home/${SERVICE_USER}/.bash_profile"

# ── .env + .display_rotation_confirmed vorkonfigurieren ─────────────────────
# Rotation läuft jetzt auf Hardware-/DRM-Ebene (siehe oben), kein Dialog nötig.

touch "${ROOTFS_DIR}${INSTALL_DIR}/.display_rotation_confirmed"
chown 1000:1000 "${ROOTFS_DIR}${INSTALL_DIR}/.display_rotation_confirmed"

if [ "${VARIANT}" = "pi3" ]; then
    # Pi 3 + TD1: Kivy rotation=180 dreht Display + Touch zusammen
    cat > "${ROOTFS_DIR}${INSTALL_DIR}/.env" << 'ENVEOF'
DISPLAY_ROTATION=180
FULLSCREEN=true
ENVEOF
elif [ "${VARIANT}" = "pi4" ]; then
    # Pi 4 + TD1: DRM dreht Plane, Kivy rotation=180 zusätzlich (SDL2-Pfad);
    # Touch wird durch INVERT_TOUCH separat gespiegelt
    cat > "${ROOTFS_DIR}${INSTALL_DIR}/.env" << 'ENVEOF'
DISPLAY_ROTATION=180
FULLSCREEN=true
INVERT_TOUCH=true
ENVEOF
else
    # Pi 5 + TD2: dtoverlay rotiert Display+Touch zusammen
    cat > "${ROOTFS_DIR}${INSTALL_DIR}/.env" << 'ENVEOF'
DISPLAY_ROTATION=270
FULLSCREEN=true
ENVEOF
fi
chown 1000:1000 "${ROOTFS_DIR}${INSTALL_DIR}/.env"
