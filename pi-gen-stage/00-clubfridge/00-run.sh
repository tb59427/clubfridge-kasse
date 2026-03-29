#!/bin/bash -e
# ──────────────────────────────────────────────────────────────────────────────
# Clubfridge Kasse – pi-gen Build-Stage
#
# Läuft AUSSERHALB des chroot. Befehle im chroot via on_chroot << EOF.
# Dateien ins Image via ${ROOTFS_DIR} Prefix.
#
# CLUBFRIDGE_VARIANT wird vom build-image.sh gesetzt:
#   pi3 = Bookworm (Pi 3/4 + TD1, X11)
#   pi5 = Trixie   (Pi 5   + TD2, Framebuffer)
# ──────────────────────────────────────────────────────────────────────────────

INSTALL_DIR="/opt/clubfridge/kasse"
SERVICE_USER="pi"
# Variante wird als Datei übergeben (env vars gehen nicht in Docker-Build)
VARIANT_FILE="$(dirname "$0")/VARIANT"
VARIANT="$(cat "$VARIANT_FILE" 2>/dev/null || echo "pi5")"

echo "══ Clubfridge Build-Stage: Variante=${VARIANT} ══"

# ── Kasse-Software klonen (ins rootfs) ───────────────────────────────────────

on_chroot << CHEOF
mkdir -p "${INSTALL_DIR}"
git clone --depth=1 --branch main https://github.com/tb59427/clubfridge-kasse.git "${INSTALL_DIR}"
CHEOF

# ── Python venv + Abhängigkeiten (im chroot) ────────────────────────────────

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

# ── WiFi: Radio aktivieren + Regulatory Domain DE ─────────────────────────

on_chroot << CHEOF
nmcli radio wifi on 2>/dev/null || true
CHEOF

mkdir -p "${ROOTFS_DIR}/etc/default"
echo 'REGDOMAIN=DE' > "${ROOTFS_DIR}/etc/default/crda"

# ── Display-Konfiguration ──────────────────────────────────────────────────

BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
if [ -f "${BOOT_CONFIG}" ]; then
    # I2C aktivieren (Touch Display 2 Goodix Controller)
    sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "${BOOT_CONFIG}"

    echo "" >> "${BOOT_CONFIG}"
    echo "# Clubfridge: HDMI Display 180° Rotation" >> "${BOOT_CONFIG}"
    echo "display_hdmi_rotate=2" >> "${BOOT_CONFIG}"
fi

# ── Varianten-spezifische Display-Rotation ─────────────────────────────────

if [ "${VARIANT}" = "pi3" ]; then
    # ── BOOKWORM (Pi 3/4): fbcon=rotate:2 in cmdline.txt ─────────────
    # auto_initramfs=0 nötig damit Firmware die cmdline.txt respektiert
    if [ -f "${BOOT_CONFIG}" ]; then
        sed -i 's/auto_initramfs=1/auto_initramfs=0/' "${BOOT_CONFIG}"
    fi
    CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"
    if [ -f "${CMDLINE}" ] && ! grep -q 'fbcon=rotate' "${CMDLINE}"; then
        sed -i 's/$/ fbcon=rotate:2/' "${CMDLINE}"
    fi
else
    # ── TRIXIE (Pi 5): Console-Rotation via systemd-Service ───────────
    # (cmdline.txt wird auf Trixie von cloud-init verwaltet)
    cat > "${ROOTFS_DIR}/usr/local/bin/fbcon-rotate.sh" << 'ROTSCRIPT'
#!/bin/bash
SIZE=$(cat /sys/class/graphics/fb0/virtual_size 2>/dev/null || echo 0,0)
W=${SIZE%%,*}
H=${SIZE##*,}
if [ "$H" -gt "$W" ] 2>/dev/null; then
  echo 1 > /sys/class/graphics/fbcon/rotate_all
else
  echo 2 > /sys/class/graphics/fbcon/rotate_all
fi
ROTSCRIPT
    chmod +x "${ROOTFS_DIR}/usr/local/bin/fbcon-rotate.sh"

    cat > "${ROOTFS_DIR}/etc/systemd/system/fbcon-rotate.service" << 'FBEOF'
[Unit]
Description=Rotate framebuffer console
DefaultDependencies=no
After=systemd-modules-load.service
Before=getty@tty1.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/fbcon-rotate.sh

[Install]
WantedBy=sysinit.target
FBEOF

    on_chroot << CHEOF
systemctl enable fbcon-rotate.service
CHEOF
fi

# ── Cloud-init user-data (User vorkonfigurieren, piwiz deaktivieren) ───────

install -v -m 755 files/user-data "${ROOTFS_DIR}/boot/firmware/user-data"

# ── Auto-Login auf TTY1 ─────────────────────────────────────────────────────

mkdir -p "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d/autologin.conf" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${SERVICE_USER} --noclear %I \$TERM
EOF

# ── X11 Setup (nur Bookworm/Pi3) ──────────────────────────────────────────

if [ "${VARIANT}" = "pi3" ]; then
    # .bash_profile: startet X11 beim Login auf TTY1
    cat > "${ROOTFS_DIR}/home/${SERVICE_USER}/.bash_profile" << 'PROFILE'
# Auto-Start X11 auf TTY1 (nur wenn kein Display läuft)
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
PROFILE
    chown 1000:1000 "${ROOTFS_DIR}/home/${SERVICE_USER}/.bash_profile"

    # .xinitrc: kein xterm, nur X11 am Leben halten (Kasse startet via systemd)
    cat > "${ROOTFS_DIR}/home/${SERVICE_USER}/.xinitrc" << 'XEOF'
#!/bin/sh
exec sleep infinity
XEOF
    chmod +x "${ROOTFS_DIR}/home/${SERVICE_USER}/.xinitrc"
    chown 1000:1000 "${ROOTFS_DIR}/home/${SERVICE_USER}/.xinitrc"

fi
