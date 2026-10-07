#!/usr/bin/env bash
# Full XFCE desktop inside TigerVNC (no light-locker crash).
# Run as user aoboki (not only root for the VNC session itself).
set -euo pipefail

GEOMETRY="${VNC_GEOMETRY:-1920x1080}"
DISPLAY_NUM=":1"

echo "==> Packages (need sudo once)..."
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  xfce4 xfce4-terminal xfce4-panel xfce4-session \
  dbus-x11 xterm x11-xserver-utils \
  tigervnc-standalone-server tigervnc-common \
  --no-install-recommends || true

# Optional: remove locker that killed the session
sudo apt-get remove -y light-locker 2>/dev/null || true
sudo apt-get remove -y xfce4-screensaver 2>/dev/null || true

mkdir -p "${HOME}/.config/tigervnc" "${HOME}/.vnc" "${HOME}/.config/xfce4/xfconf/xfce-perchannel-xml"

# TigerVNC config — no password, localhost only
cat > "${HOME}/.config/tigervnc/config" << CFG
geometry=${GEOMETRY}
localhost=yes
alwaysshared=yes
securitytypes=None
CFG

# xstartup: real XFCE, keep session alive, no locker
cat > "${HOME}/.vnc/xstartup" << 'XST'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=XFCE
export DESKTOP_SESSION=xfce

# grey fallback while desktop starts
xsetroot -solid "#2e3440" 2>/dev/null || true

# Start D-Bus for this session
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
  eval $(dbus-launch --sh-syntax --exit-with-session)
  export DBUS_SESSION_BUS_ADDRESS
fi

# Prevent screen lockers from auto-starting
export XDG_CURRENT_DESKTOP=XFCE
mkdir -p "$HOME/.config/autostart"
for app in light-locker xfce4-screensaver xscreensaver gnome-screensaver; do
  cat > "$HOME/.config/autostart/${app}.desktop" << DESK
[Desktop Entry]
Type=Application
Name=${app}
Exec=/bin/true
Hidden=true
X-GNOME-Autostart-enabled=false
DESK
done

# Full XFCE session
if command -v startxfce4 >/dev/null 2>&1; then
  exec startxfce4
fi

# Fallback chain
if command -v xfce4-session >/dev/null 2>&1; then
  xfce4-panel &
  xfdesktop &
  xfwm4 &
  exec xfce4-session
fi

xterm -geometry 120x40+40+40 &
wait
XST
chmod +x "${HOME}/.vnc/xstartup"

echo "==> Restart VNC :1 ..."
tigervncserver -kill "${DISPLAY_NUM}" 2>/dev/null || true
sleep 1
tigervncserver "${DISPLAY_NUM}" \
  -geometry "${GEOMETRY}" \
  -depth 24 \
  -localhost yes \
  -SecurityTypes None \
  -xstartup "${HOME}/.vnc/xstartup"

sleep 3
echo "==> Processes:"
ps aux | grep -E 'Xtigervnc|xfce|xfwm|xfdesktop|xfce4-panel' | grep -v grep || true
echo
echo "==> Ports:"
ss -ltnp 2>/dev/null | grep -E '5901|6080' || sudo ss -ltnp | grep -E '5901|6080' || true
echo
echo "Open: https://vnc.aoboki.pp.ua/vnc.html?autoconnect=1"
echo "Or:   https://remote.aoboki.pp.ua/interface → Connect"
