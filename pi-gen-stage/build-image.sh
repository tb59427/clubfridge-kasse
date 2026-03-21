#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Clubfridge Kasse – Golden Image bauen via pi-gen (Docker)
#
# Voraussetzung: Docker Desktop muss laufen.
#
# Aufruf:
#   cd kasse/pi-gen-stage
#   ./build-image.sh
#
# Output: deploy/image_<datum>-clubfridge-kasse-lite.img.xz
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# pi-gen auf lokalem Dateisystem (nicht NAS/SMB) — Docker braucht native FS-Operationen
PIGEN_DIR="${HOME}/.clubfridge-pi-gen"

# ── pi-gen klonen (falls nicht vorhanden) ────────────────────────────────────

if [[ ! -d "${PIGEN_DIR}" ]]; then
    echo "pi-gen wird geklont (arm64 Branch)…"
    git clone --depth=1 --branch arm64 https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
else
    echo "pi-gen vorhanden – wird aktualisiert…"
    git -C "${PIGEN_DIR}" pull --ff-only 2>/dev/null || true
fi

# ── Konfiguration ────────────────────────────────────────────────────────────

cat > "${PIGEN_DIR}/config" <<EOF
IMG_NAME=clubfridge-kasse
RELEASE=trixie
TARGET_HOSTNAME=clubfridge
FIRST_USER_NAME=pi
FIRST_USER_PASS=clubfridge
DISABLE_FIRST_BOOT_USER_RENAME=1
LOCALE_DEFAULT=de_DE.UTF-8
KEYBOARD_KEYMAP=de
KEYBOARD_LAYOUT="German"
TIMEZONE_DEFAULT=Europe/Berlin
ENABLE_SSH=1
EOF

# ── Stage 3 durch unsere Custom Stage ersetzen, 4-5 überspringen ────────────

# Alte Custom-Stage-Reste aufräumen
rm -rf "${PIGEN_DIR}/stage-clubfridge"

# Original stage3 durch unsere Clubfridge-Stage ersetzen
rm -rf "${PIGEN_DIR}/stage3"
mkdir -p "${PIGEN_DIR}/stage3"
cp -r "${SCRIPT_DIR}/00-clubfridge" "${PIGEN_DIR}/stage3/"
cp "${SCRIPT_DIR}/prerun.sh" "${PIGEN_DIR}/stage3/prerun.sh"
chmod +x "${PIGEN_DIR}/stage3/prerun.sh"
touch "${PIGEN_DIR}/stage3/EXPORT_IMAGE"

# Stage 4+5 überspringen
touch "${PIGEN_DIR}/stage4/SKIP" "${PIGEN_DIR}/stage4/SKIP_IMAGES"
touch "${PIGEN_DIR}/stage5/SKIP" "${PIGEN_DIR}/stage5/SKIP_IMAGES"

# ── Image bauen ──────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Image-Build wird gestartet (kann 30-60 Minuten dauern)…"
echo "════════════════════════════════════════════════════════════════"
echo ""

cd "${PIGEN_DIR}"
# Docker Desktop auf macOS braucht kein sudo
export DOCKER=docker
./build-docker.sh

# ── Output ───────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Build abgeschlossen!"
echo ""
echo "  Image: ${PIGEN_DIR}/deploy/"
ls -lh "${PIGEN_DIR}/deploy/"*.img* 2>/dev/null || echo "  (Keine Images gefunden – Build-Log prüfen)"
echo "════════════════════════════════════════════════════════════════"
