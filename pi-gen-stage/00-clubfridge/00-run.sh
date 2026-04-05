#!/bin/bash -e
# ──────────────────────────────────────────────────────────────────────────────
# Clubfridge Kasse – pi-gen Build-Stage
#
# Läuft AUSSERHALB des chroot. Befehle im chroot via on_chroot << EOF.
# Dateien ins Image via ${ROOTFS_DIR} Prefix.
#
# VARIANT wird aus der Datei VARIANT gelesen (vom build-image.sh geschrieben):
#   pi3 = Bookworm Lite (Pi 3/4 + Touch Display 1)
#   pi5 = Trixie Lite   (Pi 5   + Touch Display 2)
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
# KEINE Software-Rotation (kein Kivy-Rotation, kein xrandr, kein wlr-randr).
# Alles über config.txt + cmdline.txt auf Hardware-Ebene.
#
# Touch Display 1 (800x480, FT5406):
#   - display_auto_detect=1 (default, erkennt TD1 automatisch)
#   - Console-Rotation: fbcon=rotate:2 in cmdline.txt
#   - Touch-Rotation: Kivy rotation=180 (KEIN invx,invy Overlay!)
#
# Touch Display 2 (720x1280, Goodix):
#   - Display+Touch: dtoverlay=vc4-kms-dsi-ili9881-7inch,rotation=270
#   - Touch dreht automatisch mit
#   - display_auto_detect=0

BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"

if [ -f "${BOOT_CONFIG}" ]; then
    # I2C aktivieren (Touch Display 2 Goodix Controller)
    sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "${BOOT_CONFIG}"

    if [ "${VARIANT}" = "pi3" ]; then
        # ── Touch Display 1: display_auto_detect erkennt TD1 automatisch.
        # Touch-Rotation macht Kivy (rotation=180), NICHT das Kernel-Overlay
        # (invx,invy würde Touch doppelt invertieren).
        :
    else
        # display_auto_detect deaktivieren (TD2 braucht manuelles Overlay)
        sed -i 's/^display_auto_detect=1/display_auto_detect=0/' "${BOOT_CONFIG}"
        # ── Touch Display 2: Overlay mit Display+Touch-Rotation ──────
        echo "" >> "${BOOT_CONFIG}"
        echo "# Clubfridge: Touch Display 2 (270° für Landscape)" >> "${BOOT_CONFIG}"
        echo "dtoverlay=vc4-kms-dsi-ili9881-7inch,rotation=270" >> "${BOOT_CONFIG}"
    fi
fi

# ── cmdline.txt: Console-Rotation + WiFi Regulatory Domain ────────────────────

if [ -f "${CMDLINE}" ]; then
    # WiFi Regulatory Domain DE (Kernel-Parameter)
    if ! grep -q 'cfg80211' "${CMDLINE}"; then
        sed -i 's/$/ cfg80211.ieee80211_regdom=DE/' "${CMDLINE}"
    fi

    if [ "${VARIANT}" = "pi3" ]; then
        # Console-Rotation 180° (Touch Display 1 im Gehäuse kopfüber)
        if ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
            sed -i 's/$/ fbcon=rotate:2/' "${CMDLINE}"
        fi
        # auto_initramfs=0 damit Firmware die cmdline.txt respektiert
        if [ -f "${BOOT_CONFIG}" ]; then
            sed -i 's/auto_initramfs=1/auto_initramfs=0/' "${BOOT_CONFIG}"
        fi
    fi
    if [ "${VARIANT}" != "pi3" ]; then
        # Pi5/TD2: Console-Rotation via cmdline.txt (fbcon=rotate:1 = 90° CW)
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

# ── Display-Rotation Dialog (whiptail, beim ersten Start) ─────────────────

chmod +x "${ROOTFS_DIR}${INSTALL_DIR}/deploy/display-rotation-setup.sh"

if [ "${VARIANT}" = "pi3" ]; then
    # Pi3/TD1: Rotation-Dialog beim ersten Start (User wählt 0° oder 180°)
    # .bash_profile: Rotation-Dialog vor allem anderen (nur auf TTY1, nur beim ersten Start)
    cat > "${ROOTFS_DIR}/home/${SERVICE_USER}/.bash_profile" << 'BPEOF'
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

    # Kasse-Service wartet bis Rotation bestätigt ist
    mkdir -p "${ROOTFS_DIR}/etc/systemd/system/clubfridge-kasse@.service.d"
    cat > "${ROOTFS_DIR}/etc/systemd/system/clubfridge-kasse@.service.d/wait-rotation.conf" << 'WAITEOF'
[Service]
ExecStartPre=/bin/bash -c 'while [ ! -f /opt/clubfridge/kasse/.display_rotation_confirmed ]; do sleep 1; done'
WAITEOF
else
    # Pi5/TD2: Hardware-Rotation via dtoverlay, kein Dialog nötig
    cat > "${ROOTFS_DIR}/home/${SERVICE_USER}/.bash_profile" << 'BPEOF'
# Console-Echo deaktivieren und Shell blockieren damit Kivy exklusiv läuft
if [ "$(tty)" = "/dev/tty1" ]; then
    stty -echo 2>/dev/null
    exec sleep infinity
fi
BPEOF

    # .display_rotation_confirmed anlegen (kein Whiptail nötig)
    touch "${ROOTFS_DIR}${INSTALL_DIR}/.display_rotation_confirmed"

    # Display-Einstellungen vorkonfigurieren (KMSDRM: Kivy dreht Content)
    cat > "${ROOTFS_DIR}${INSTALL_DIR}/.env" << 'ENVEOF'
DISPLAY_ROTATION=270
FULLSCREEN=true
ENVEOF
    chown 1000:1000 "${ROOTFS_DIR}${INSTALL_DIR}/.env"
fi
chown 1000:1000 "${ROOTFS_DIR}/home/${SERVICE_USER}/.bash_profile"
