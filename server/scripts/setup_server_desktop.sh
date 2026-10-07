#!/usr/bin/env bash
# Install lightweight desktop + TigerVNC + noVNC on the Linux host
# so https://remote.aoboki.pp.ua/interface can show the server desktop.
#
# Run on the SERVER as root (or sudo):
#   bash setup_server_desktop.sh
#
set -euo pipefail

VNC_USER="${SUDO_USER:-${USER}}"
VNC_DISPLAY=":1"
VNC_PORT=5901
WEBSOCKIFY_PORT=6080
NOVNC_DIR="/opt/novnc"
VNC_PASS="${VNC_PASSWORD:-ChangeMeNow}"

echo "==> Installing packages (Debian/Ubuntu)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  xfce4 xfce4-goodies \
  tigervnc-standalone-server tigervnc-common \
  python3-websockify git \
  dbus-x11

echo "==> noVNC into ${NOVNC_DIR}"
if [[ ! -d "${NOVNC_DIR}/.git" ]]; then
  git clone --depth 1 https://github.com/novnc/noVNC.git "${NOVNC_DIR}"
  git clone --depth 1 https://github.com/novnc/websockify.git "${NOVNC_DIR}/utils/websockify" || true
fi

echo "==> VNC password for user ${VNC_USER}"
mkdir -p "/home/${VNC_USER}/.vnc"
chown -R "${VNC_USER}:${VNC_USER}" "/home/${VNC_USER}/.vnc"
su - "${VNC_USER}" -c "printf '%s\n%s\n' '${VNC_PASS}' '${VNC_PASS}' | vncpasswd -f > ~/.vnc/passwd"
chmod 600 "/home/${VNC_USER}/.vnc/passwd"
chown "${VNC_USER}:${VNC_USER}" "/home/${VNC_USER}/.vnc/passwd"

# xstartup for XFCE
cat > "/home/${VNC_USER}/.vnc/xstartup" << 'XSTART'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XDG_SESSION_TYPE=x11
export XKL_XMODMAP_DISABLE=1
exec startxfce4
XSTART
chmod +x "/home/${VNC_USER}/.vnc/xstartup"
chown "${VNC_USER}:${VNC_USER}" "/home/${VNC_USER}/.vnc/xstartup"

echo "==> systemd: vncserver@${VNC_DISPLAY}"
cat > /etc/systemd/system/vncserver@.service << EOFSVC
[Unit]
Description=TigerVNC server on display %i
After=network.target

[Service]
Type=forking
User=${VNC_USER}
PAMName=login
PIDFile=/home/${VNC_USER}/.vnc/%H%i.pid
ExecStartPre=-/usr/bin/vncserver -kill %i
ExecStart=/usr/bin/vncserver %i -geometry 1920x1080 -depth 24 -localhost yes
ExecStop=/usr/bin/vncserver -kill %i
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOFSVC

echo "==> systemd: novnc websockify on :${WEBSOCKIFY_PORT}"
cat > /etc/systemd/system/novnc.service << EOFNOV
[Unit]
Description=noVNC websockify
After=network.target vncserver@${VNC_DISPLAY}.service
Requires=vncserver@${VNC_DISPLAY}.service

[Service]
ExecStart=/usr/bin/websockify --web=${NOVNC_DIR} ${WEBSOCKIFY_PORT} 127.0.0.1:${VNC_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOFNOV

systemctl daemon-reload
systemctl enable --now "vncserver@${VNC_DISPLAY}.service"
systemctl enable --now novnc.service

echo
echo "OK. Local check:"
echo "  curl -I http://127.0.0.1:${WEBSOCKIFY_PORT}/vnc.html"
echo
echo "Nginx — add to remote.aoboki.pp.ua server block:"
cat << 'NGX'

  location /vnc/ {
      proxy_pass http://127.0.0.1:6080/;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_set_header Host $host;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
  }

NGX
echo "VNC password: ${VNC_PASS}  (change via VNC_PASSWORD=... bash setup_server_desktop.sh)"
echo "Then open: https://remote.aoboki.pp.ua/interface"
