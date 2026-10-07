#!/usr/bin/env bash
# Restart TigerVNC on :1 without VNC password (localhost only).
# Site login on remote.aoboki.pp.ua remains the access control.
set -euo pipefail
USER_HOME="${HOME}"
DISPLAY_NUM=":1"
GEOMETRY="${VNC_GEOMETRY:-1280x720}"

mkdir -p "${USER_HOME}/.config/tigervnc" "${USER_HOME}/.vnc"

cat > "${USER_HOME}/.config/tigervnc/config" << CFG
session=xfce
geometry=${GEOMETRY}
localhost=yes
alwaysshared=yes
securitytypes=None
CFG

cat > "${USER_HOME}/.vnc/xstartup" << 'XST'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_TYPE=x11
xsetroot -solid grey
if command -v startxfce4 >/dev/null 2>&1; then
  exec dbus-launch --exit-with-session startxfce4
fi
if command -v openbox >/dev/null 2>&1; then
  exec openbox-session
fi
exec xterm -geometry 100x30+10+10 -ls
XST
chmod +x "${USER_HOME}/.vnc/xstartup"

tigervncserver -kill "${DISPLAY_NUM}" 2>/dev/null || true
tigervncserver "${DISPLAY_NUM}" -geometry "${GEOMETRY}" -depth 24 -localhost yes -SecurityTypes None

pkill -f 'websockify --web=/opt/novnc' 2>/dev/null || true
sleep 1
nohup websockify --web=/opt/novnc 6080 127.0.0.1:5901 >/tmp/websockify.log 2>&1 &
sleep 1
echo "VNC :1 SecurityTypes=None (no password)"
ss -tlnp 2>/dev/null | grep -E '5901|6080' || true
ps aux | grep -E 'Xtigervnc|xfce|xterm|websockify' | grep -v grep || true
echo "Open: https://remote.aoboki.pp.ua/vnc/vnc.html?autoconnect=1&path=vnc/websockify"
