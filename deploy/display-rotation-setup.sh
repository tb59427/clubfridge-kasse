#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Display-Rotation Setup (läuft vor der Kasse, auf der Console)
#
# Fragt beim ersten Start den Benutzer nach der Display-Rotation.
# Speichert die Wahl in .display_rotation und .display_rotation_confirmed.
# Bei nachfolgenden Starts wird der Dialog übersprungen.
# ──────────────────────────────────────────────────────────────────────────────

KASSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROTATION_FILE="${KASSE_DIR}/.display_rotation"
CONFIRMED_FILE="${KASSE_DIR}/.display_rotation_confirmed"

# Bereits bestätigt → nichts tun
if [ -f "$CONFIRMED_FILE" ]; then
    exit 0
fi

# whiptail Dialog auf /dev/tty1 erzwingen
CHOICE=$(whiptail --title "Clubfridge – Display-Rotation" \
    --default-item "180" \
    --menu "Rotation fuer die Clubfridge-Kassen-Software.\n\nFuer das offizielle Raspberry Pi Touch Display\nim Standard-Gehaeuse: 180 Grad waehlen.\nFuer andere Displays ggf. anpassen." \
    16 60 4 \
    "0"   "Keine Drehung" \
    "90"  "90 Grad" \
    "180" "180 Grad (Standard Touch Display)" \
    "270" "270 Grad" \
    3>&1 1>&2 2>&3 </dev/tty1 >/dev/tty1)

if [ $? -eq 0 ] && [ -n "$CHOICE" ]; then
    echo "$CHOICE" > "$ROTATION_FILE"
    touch "$CONFIRMED_FILE"
else
    # Abbruch → Standard 180°
    echo "180" > "$ROTATION_FILE"
    touch "$CONFIRMED_FILE"
fi

echo "" > /dev/tty1
echo "  Clubfridge Kasse wird gestartet..." > /dev/tty1
echo "" > /dev/tty1

# Dateien dem pi-User zuordnen
chown pi:pi "$ROTATION_FILE" "$CONFIRMED_FILE" 2>/dev/null
