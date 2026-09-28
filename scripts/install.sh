#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RADIO_DIR=/home/pi/radio
RADIO_VENV=/home/pi/.virtualenvs/pimoroni
WIFI_DIR=/opt/piradio-wifi
CONFIG_FILE=/boot/firmware/config.txt
INSTALL_WIFI=0

usage() {
  echo "Usage: sudo bash scripts/install.sh [--with-wifi-fallback]"
  echo "Requires Raspberry Pi OS Bookworm, the user pi, and an existing Wi-Fi connection."
}

if [[ ${1:-} == --with-wifi-fallback && $# == 1 ]]; then
  INSTALL_WIFI=1
elif (( $# != 0 )); then
  usage >&2
  exit 2
fi

(( EUID == 0 )) || { echo 'Run with sudo.' >&2; exit 1; }
id pi >/dev/null 2>&1 || { echo 'Create the pi user first.' >&2; exit 1; }
[[ -f "$CONFIG_FILE" ]] || { echo "Missing $CONFIG_FILE" >&2; exit 1; }
[[ -r /etc/os-release ]] || exit 1
# shellcheck disable=SC1091
source /etc/os-release
[[ ${VERSION_CODENAME:-} == bookworm ]] || {
  echo 'This installer has only been prepared for Raspberry Pi OS Bookworm.' >&2
  exit 1
}
command -v apt-get >/dev/null || exit 1

echo 'Installing radio packages...'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3-venv python3-pip python3-spidev python3-pil python3-numpy \
  python3-rpi.gpio mpv alsa-utils curl wireless-tools fonts-dejavu-core \
  libopenblas0-pthread avahi-daemon

install -d -o pi -g pi /home/pi/.virtualenvs "$RADIO_DIR"
if [[ ! -x "$RADIO_VENV/bin/python" ]]; then
  runuser -u pi -- python3 -m venv --system-site-packages "$RADIO_VENV"
fi
runuser -u pi -- "$RADIO_VENV/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
runuser -u pi -- "$RADIO_VENV/bin/python" -c 'import RPi.GPIO, st7789; from PIL import Image'
install -o pi -g pi -m 0644 "$ROOT_DIR/radio.py" "$RADIO_DIR/radio.py"
if [[ -f "$RADIO_DIR/stations.json" ]]; then
  echo 'Keeping the existing stations.json.'
else
  install -o pi -g pi -m 0644 "$ROOT_DIR/stations.json" "$RADIO_DIR/stations.json"
fi
if [[ ! -e "$RADIO_DIR/state.json" ]]; then
  printf '%s\n' '{"index": 0, "volume": 70}' > "$RADIO_DIR/state.json"
  chown pi:pi "$RADIO_DIR/state.json"
fi
runuser -u pi -- "$RADIO_VENV/bin/python" -m py_compile "$RADIO_DIR/radio.py"
usermod -aG audio,spi,gpio pi

# Back up and only append missing settings. Existing conflicting settings
# require manual review so the installer does not silently change hardware.
for setting in 'dtparam=spi=on' 'dtparam=audio=off' 'dtoverlay=hifiberry-dac' 'gpio=25=op,dh'; do
  if ! grep -Eq "^[[:space:]]*${setting//./\.}[[:space:]]*$" "$CONFIG_FILE"; then
    if [[ ! -e "$CONFIG_FILE.piradio-backup" ]]; then
      cp -p "$CONFIG_FILE" "$CONFIG_FILE.piradio-backup"
    fi
    printf '\n%s\n' "$setting" >> "$CONFIG_FILE"
    echo "Added $setting to $CONFIG_FILE"
  fi
done

install -m 0644 "$ROOT_DIR/systemd/piradio.service" /etc/systemd/system/piradio.service

if (( INSTALL_WIFI )); then
  echo 'Installing optional Wi-Fi fallback...'
  systemctl is-active --quiet NetworkManager || {
    echo 'NetworkManager must be active for Wi-Fi fallback.' >&2
    exit 1
  }
  DEBIAN_FRONTEND=noninteractive apt-get install -y hostapd dnsmasq iptables
  install -d "$WIFI_DIR"
  if [[ ! -x "$WIFI_DIR/venv/bin/python" ]]; then
    python3 -m venv "$WIFI_DIR/venv"
  fi
  "$WIFI_DIR/venv/bin/python" -m pip install -r "$ROOT_DIR/requirements-wifi.txt"
  WIFI_PACKAGE_DIR=$("$WIFI_DIR/venv/bin/python" -c 'import pathlib, pi_wifi_setup; print(pathlib.Path(pi_wifi_setup.__file__).parent)')
  [[ -f "$WIFI_PACKAGE_DIR/wifi_connector.py" && -f "$WIFI_PACKAGE_DIR/web_server.py" && -f "$WIFI_PACKAGE_DIR/templates/index.html" ]] || {
    echo 'Unexpected pi-wifi-setup layout; Wi-Fi service was not enabled.' >&2
    exit 1
  }
  grep -Fq 'password = request.form.get("password", "").strip()' "$WIFI_PACKAGE_DIR/web_server.py" || {
    grep -Fq 'password = request.form.get("password", "")' "$WIFI_PACKAGE_DIR/web_server.py" || {
      echo 'Unexpected password handler; Wi-Fi service was not enabled.' >&2
      exit 1
    }
  }
  for file in wifi_connector.py web_server.py templates/index.html; do
    [[ -e "$WIFI_PACKAGE_DIR/$file.piradio-backup" ]] || cp -p "$WIFI_PACKAGE_DIR/$file" "$WIFI_PACKAGE_DIR/$file.piradio-backup"
  done
  install -m 0644 "$ROOT_DIR/wifi/wifi_connector.py" "$WIFI_PACKAGE_DIR/wifi_connector.py"
  sed -i 's/password = request\.form\.get("password", "")\.strip()/password = request.form.get("password", "")/' "$WIFI_PACKAGE_DIR/web_server.py"
  sed -i 's/autocomplete="current-password"/autocomplete="off"/' "$WIFI_PACKAGE_DIR/templates/index.html"
  "$WIFI_DIR/venv/bin/python" -m py_compile "$WIFI_PACKAGE_DIR/wifi_connector.py" "$WIFI_PACKAGE_DIR/web_server.py"
  install -m 0644 "$ROOT_DIR/wifi/fallback.py" "$WIFI_DIR/fallback.py"
  "$WIFI_DIR/venv/bin/python" -m py_compile "$WIFI_DIR/fallback.py"
  install -m 0644 "$ROOT_DIR/systemd/piradio-wifi-fallback.service" /etc/systemd/system/piradio-wifi-fallback.service
  systemctl disable --now dnsmasq hostapd 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable piradio.service
if (( INSTALL_WIFI )); then
  systemctl enable piradio-wifi-fallback.service
fi
echo 'Installation complete. Reboot to activate the audio and SPI configuration.'
echo 'After reboot, check: systemctl status piradio.service --no-pager'
if (( INSTALL_WIFI )); then
  echo 'Also check: systemctl status piradio-wifi-fallback.service --no-pager'
  echo 'Test the portal and reconnection before relying on Wi-Fi fallback.'
fi
