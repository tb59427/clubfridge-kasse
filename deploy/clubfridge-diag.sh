#!/usr/bin/env bash
# ------------------------------------------------------------------
# Clubfridge Kasse – Diagnose-Skript ohne sudo
# ------------------------------------------------------------------
# Wird auf der Pi-Kasse als Service-User (z.B. "pi") ausgeführt.
# Sammelt die wichtigsten Status-Infos und legt sie in /tmp/cf-diag.txt ab.
#
# Aufruf:
#   1. Auf einer freien TTY anmelden (z.B. Ctrl+Alt+F2 an der Kasse)
#      oder per SSH einloggen.
#   2. Skript ausführen:
#         bash clubfridge-diag.sh
#   3. Die Datei /tmp/cf-diag.txt an info@clubfridge.com senden.
#
# Das Skript benutzt KEIN sudo — damit kein Passwort nötig ist.
# Manche Detailinfos (z.B. wer /dev/dri/card1 belegt) brauchen sudo
# und werden hier weggelassen; das System-Journal vom Kasse-Service
# ist mit der Default-Mitgliedschaft des Pi-Users in der "adm"-Gruppe
# auch ohne sudo lesbar.
# ------------------------------------------------------------------

OUT="/tmp/cf-diag.txt"
SERVICE="clubfridge-kasse@$(whoami).service"

{
    echo "=== Clubfridge-Diagnose ($(date -Iseconds)) ==="
    echo
    echo "=== User & TTY ==="
    echo "User : $(whoami)"
    echo "TTY  : $(tty 2>/dev/null || echo 'unbekannt')"
    echo "Host : $(hostname)"
    echo
    echo "=== Pi-Modell + OS ==="
    cat /proc/device-tree/model 2>/dev/null; echo
    grep -E '^(PRETTY_NAME|VERSION_CODENAME)=' /etc/os-release 2>/dev/null
    echo
    echo "=== Kasse-Version ==="
    grep '^version' /opt/clubfridge/kasse/pyproject.toml 2>/dev/null
    echo
    echo "=== Kasse-Service (${SERVICE}) ==="
    echo "is-active : $(systemctl is-active "${SERVICE}" 2>&1)"
    echo "is-enabled: $(systemctl is-enabled "${SERVICE}" 2>&1)"
    systemctl status "${SERVICE}" --no-pager 2>&1 | head -25
    echo
    echo "=== Default-Target (sollte multi-user.target sein) ==="
    systemctl get-default
    echo
    echo "=== Compositoren / Display-Manager (sollten alle leer sein) ==="
    for proc in labwc wayfire Xorg Xwayland lightdm gdm sddm; do
        out=$(pgrep -al "$proc" 2>/dev/null)
        [[ -n "$out" ]] && echo "$out"
    done
    echo
    echo "=== lightdm-Service (sollte masked + inactive sein) ==="
    echo "is-enabled: $(systemctl is-enabled lightdm.service 2>&1)"
    echo "is-active : $(systemctl is-active  lightdm.service 2>&1)"
    echo
    echo "=== DRM-Karten ==="
    ls -la /dev/dri/ 2>&1
    echo
    echo "=== TTY1 Autologin-Override ==="
    if [[ -r /etc/systemd/system/getty@tty1.service.d/autologin.conf ]]; then
        cat /etc/systemd/system/getty@tty1.service.d/autologin.conf
    else
        echo "FEHLT — Autologin nicht eingerichtet"
    fi
    echo
    echo "=== .env vorhanden? ==="
    if [[ -r /opt/clubfridge/kasse/.env ]]; then
        echo "ja:"
        ls -la /opt/clubfridge/kasse/.env
        # nur API_URL und TENANT_SLUG (keine Geheimnisse) ausgeben
        grep -E '^(API_URL|TENANT_SLUG|HAS_RELAY|DISPLAY_ROTATION|FULLSCREEN|INVERT_TOUCH)=' /opt/clubfridge/kasse/.env
    else
        echo "FEHLT oder nicht lesbar — Kasse vermutlich nicht provisioniert"
    fi
    echo
    echo "=== Service-Drop-ins (kmsdrm etc.) ==="
    ls -la /etc/systemd/system/clubfridge-kasse@.service.d/ 2>/dev/null
    cat /etc/systemd/system/clubfridge-kasse@.service.d/*.conf 2>/dev/null
    echo
    echo "=== Boot-Cmdline (Display-Rotation, fbcon) ==="
    cat /proc/cmdline 2>/dev/null
    echo
    echo "=== Kasse-Journal seit Boot (letzte 150 Zeilen) ==="
    journalctl -u "${SERVICE}" -b --no-pager 2>&1 | tail -150
    echo
    echo "=== Install-Log (letzte 60 Zeilen) ==="
    tail -60 /var/log/clubfridge-install.log 2>&1
    echo
    echo "=== Ende der Diagnose ==="
} > "${OUT}" 2>&1

echo
echo "Diagnose geschrieben nach: ${OUT}"
echo
echo "Bitte die Datei an info@clubfridge.com schicken,"
echo "z.B. per scp oder einfach den Inhalt kopieren:"
echo "    cat ${OUT}"
echo
