#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Clubfridge Kasse – Golden Image bauen via pi-gen (Docker)
#
# Voraussetzung: Docker Desktop muss laufen.
#
# Aufruf:
#   cd kasse/pi-gen-stage
#   ./build-image.sh pi3      # Bookworm – Pi 3/4 + Touch Display 1
#   ./build-image.sh pi5      # Trixie   – Pi 5   + Touch Display 2
#   ./build-image.sh all      # Beide Images nacheinander
#
# Output: ~/clubfridge-image-pi3.zip  bzw.  ~/clubfridge-image-pi5.zip
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIGEN_DIR="${HOME}/.clubfridge-pi-gen"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "Aufruf: $0 <pi3|pi5|all>"
    echo "  pi3  – Bookworm (Pi 3/4 + Touch Display 1)"
    echo "  pi5  – Trixie   (Pi 5   + Touch Display 2)"
    echo "  all  – Beide Images nacheinander"
    exit 1
fi

build_image() {
    local VARIANT="$1"  # pi3 oder pi5

    if [[ "$VARIANT" == "pi3" ]]; then
        PIGEN_TAG="2025-11-24-raspios-bookworm-arm64"
        RELEASE="bookworm"
        IMG_SUFFIX="pi3"
    elif [[ "$VARIANT" == "pi5" ]]; then
        PIGEN_TAG="arm64"  # master branch = Trixie
        RELEASE="trixie"
        IMG_SUFFIX="pi5"
    else
        echo "Unbekannte Variante: $VARIANT"
        exit 1
    fi

    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "  Baue ${VARIANT}-Image (${RELEASE})…"
    echo "════════════════════════════════════════════════════════════════"

    # ── pi-gen klonen/aktualisieren ────────────────────────────────────
    if [[ ! -d "${PIGEN_DIR}" ]]; then
        echo "pi-gen wird geklont (${PIGEN_TAG})…"
        git clone --depth=1 --branch "${PIGEN_TAG}" https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
    else
        CURRENT_TAG=$(git -C "${PIGEN_DIR}" describe --tags --exact-match 2>/dev/null || \
                      git -C "${PIGEN_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "none")
        if [[ "${CURRENT_TAG}" != "${PIGEN_TAG}" ]]; then
            echo "pi-gen wechseln auf ${PIGEN_TAG}…"
            rm -rf "${PIGEN_DIR}"
            git clone --depth=1 --branch "${PIGEN_TAG}" https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
        else
            echo "pi-gen vorhanden (${PIGEN_TAG})"
        fi
    fi

    # ── Docker aufräumen ───────────────────────────────────────────────
    docker rm -v pigen_work 2>/dev/null || true
    rm -rf "${PIGEN_DIR}/work" "${PIGEN_DIR}/deploy"

    # ── Konfiguration ──────────────────────────────────────────────────
    cat > "${PIGEN_DIR}/config" <<EOF
IMG_NAME=clubfridge-kasse-${IMG_SUFFIX}
RELEASE=${RELEASE}
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

    # ── Custom Stage einrichten ────────────────────────────────────────
    rm -rf "${PIGEN_DIR}/stage-clubfridge" "${PIGEN_DIR}/stage3"
    mkdir -p "${PIGEN_DIR}/stage3"
    cp -r "${SCRIPT_DIR}/00-clubfridge" "${PIGEN_DIR}/stage3/"
    cp "${SCRIPT_DIR}/prerun.sh" "${PIGEN_DIR}/stage3/prerun.sh"
    chmod +x "${PIGEN_DIR}/stage3/prerun.sh"
    touch "${PIGEN_DIR}/stage3/EXPORT_IMAGE"
    touch "${PIGEN_DIR}/stage4/SKIP" "${PIGEN_DIR}/stage4/SKIP_IMAGES"
    touch "${PIGEN_DIR}/stage5/SKIP" "${PIGEN_DIR}/stage5/SKIP_IMAGES"

    # ── Varianten-spezifische Anpassungen ──────────────────────────────
    if [[ "$VARIANT" == "pi3" ]]; then
        # Bookworm/Pi3: fbcon=rotate:2 in cmdline.txt (Landscape 180°)
        # wird im 00-run.sh per sed eingefügt wenn cmdline.txt vorhanden
        export CLUBFRIDGE_VARIANT="pi3"
    else
        export CLUBFRIDGE_VARIANT="pi5"
    fi

    # ── Bauen ──────────────────────────────────────────────────────────
    echo ""
    echo "  Image-Build wird gestartet (kann 20-40 Minuten dauern)…"
    echo ""

    cd "${PIGEN_DIR}"
    export DOCKER=docker
    ./build-docker.sh

    # ── Output kopieren ────────────────────────────────────────────────
    local OUTPUT_ZIP="${HOME}/clubfridge-image-${IMG_SUFFIX}.zip"
    local BUILT_ZIP=$(ls "${PIGEN_DIR}/deploy/"*.zip 2>/dev/null | head -1)
    if [[ -n "$BUILT_ZIP" ]]; then
        cp "$BUILT_ZIP" "$OUTPUT_ZIP"
        echo ""
        echo "════════════════════════════════════════════════════════════════"
        echo "  ${VARIANT}-Image fertig: ${OUTPUT_ZIP}"
        ls -lh "$OUTPUT_ZIP"
        echo "════════════════════════════════════════════════════════════════"
    else
        echo "  FEHLER: Kein Image gefunden in ${PIGEN_DIR}/deploy/"
    fi
}

# ── Hauptprogramm ──────────────────────────────────────────────────────────

if [[ "$TARGET" == "all" ]]; then
    build_image "pi3"
    build_image "pi5"
elif [[ "$TARGET" == "pi3" || "$TARGET" == "pi5" ]]; then
    build_image "$TARGET"
else
    echo "Unbekanntes Ziel: $TARGET (pi3, pi5 oder all)"
    exit 1
fi
