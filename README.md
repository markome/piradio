# PiRadio – clean SD card installation

This is the reproducible setup used for the working PiRadio units.

## Target hardware

- Raspberry Pi Zero W or Zero 2 W
- Pimoroni Pirate Audio HAT (3W Stereo Amp version used on piradioamp)
- speaker(s) appropriate for the HAT
- microSD card
- reliable Raspberry Pi power supply

The software assumes the Linux username is exactly `pi`.

---

## 1. Flash the SD card

Use Raspberry Pi Imager.

Recommended for maximum compatibility with Zero W and Zero 2 W:

- Raspberry Pi OS Lite (32-bit), current release
- hostname: choose a unique name, e.g. `piradio3` (do not type `.local`)
- username: `pi`
- set a password
- configure your normal Wi-Fi
- Wi-Fi country: Slovenia
- timezone: Europe/Ljubljana
- enable SSH
- password authentication or SSH key authentication

Boot the Pi and connect:

```bash
ssh pi@piradio3.local
```

---

## 2. Update the OS

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

SSH back in.

---

## 3. Configure Pirate Audio hardware

Edit:

```bash
sudo nano /boot/firmware/config.txt
```

Make sure these lines exist:

```ini
dtparam=spi=on
dtparam=audio=off
dtoverlay=hifiberry-dac
gpio=25=op,dh
```

Save and reboot:

```bash
sudo reboot
```

Verify:

```bash
ls -l /dev/spidev0.1
aplay -l
```

You should see an ALSA card named similar to `sndrpihifiberry`.

---

## 4. Install radio dependencies

```bash
sudo apt update
sudo apt install -y \
  git \
  python3-pip \
  python3-venv \
  python3-spidev \
  python3-pil \
  python3-numpy \
  python3-lgpio \
  mpv \
  alsa-utils \
  curl \
  wireless-tools \
  fonts-dejavu-core \
  libopenblas0-pthread \
  avahi-daemon
```

Avoid the old RPi.GPIO backend:

```bash
sudo apt remove -y python3-rpi.gpio || true
```

Create the Python environment:

```bash
mkdir -p ~/.virtualenvs
python3 -m venv --system-site-packages ~/.virtualenvs/pimoroni
~/.virtualenvs/pimoroni/bin/pip install --upgrade pip
~/.virtualenvs/pimoroni/bin/pip install st7789 rpi-lgpio
```

Give `pi` access to the required hardware:

```bash
sudo usermod -aG audio,spi,gpio pi
```

Reboot:

```bash
sudo reboot
```

Verify imports:

```bash
~/.virtualenvs/pimoroni/bin/python - <<'PY'
import RPi.GPIO as GPIO
from PIL import Image
import st7789
print("GPIO:", GPIO.__file__)
print("PIL OK")
print("ST7789 OK")
PY
```

---

## 5. Install the radio files

Create the directory:

```bash
mkdir -p /home/pi/radio
```

Put the supplied `radio.py` in:

```text
/home/pi/radio/radio.py
```

Copy the supplied `stations.json` from this kit to:

```text
/home/pi/radio/stations.json
```

It contains the same station list currently used on the working radios:

```json
[
  {
    "name": "Rock Antenne",
    "url": "https://stream.antenne.de/rockantenne"
  },
  {
    "name": "Antenne Bayern",
    "url": "https://stream.antenne.de/antenne"
  },
  {
    "name": "Radio Swiss Jazz",
    "url": "https://stream.srg-ssr.ch/m/rsj/mp3_128"
  },
  {
    "name": "Radio Bossa Nova Brazil",
    "url": "https://stream.streamgenial.stream/87eu2988rm0uv"
  },
  {
    "name": "RMC2",
    "url": "https://stream.rcs.revma.com/txdn8d324ucwv"
  },
  {
    "name": "VAL 202",
    "url": "http://mp3.rtvslo.si/val202"
  },
  {
    "name": "Radio CITY",
    "url": "https://stream1.radiocity.si/CityMp3128.mp3"
  },
  {
    "name": "Rock Antenne Heavy Metal",
    "url": "https://stream.rockantenne.de/heavy-metal/stream/aacp"
  }
]
```

Initial state can be created with:

```bash
echo '{"index": 0, "volume": 70}' > /home/pi/radio/state.json
```

Set ownership and executable permission:

```bash
sudo chown -R pi:pi /home/pi/radio
chmod +x /home/pi/radio/radio.py
```

Syntax check:

```bash
~/.virtualenvs/pimoroni/bin/python -m py_compile /home/pi/radio/radio.py
```

Manual test:

```bash
cd /home/pi/radio
~/.virtualenvs/pimoroni/bin/python radio.py
```

The display should work and the selected internet radio station should play.
Use Ctrl+C to stop the manual test.

---

## 6. Install the radio systemd service

Copy `piradio.service` from this kit to:

```text
/etc/systemd/system/piradio.service
```

Or create it with:

```ini
[Unit]
Description=Pi Radio
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/radio
Environment="PATH=/home/pi/.virtualenvs/pimoroni/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/pi/.virtualenvs/pimoroni/bin/python /home/pi/radio/radio.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now piradio.service
```

Check:

```bash
systemctl status piradio.service --no-pager
journalctl -u piradio.service -n 50 --no-pager
```

---

## 7. Install Wi-Fi fallback prerequisites

Check NetworkManager:

```bash
systemctl is-active NetworkManager
nmcli device status
```

If necessary:

```bash
sudo systemctl enable --now NetworkManager
```

Install the fallback dependencies:

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq python3-venv iptables
```

Disable their standalone services because `pi-wifi-setup` starts the binaries itself:

```bash
sudo systemctl disable --now dnsmasq
sudo systemctl disable --now hostapd || true
```

A message saying `hostapd` is masked is harmless.

---

## 8. Install pi-wifi-setup

```bash
sudo mkdir -p /opt/piradio-wifi
sudo python3 -m venv /opt/piradio-wifi/venv
sudo /opt/piradio-wifi/venv/bin/pip install --upgrade pip
sudo /opt/piradio-wifi/venv/bin/pip install pi-wifi-setup==1.0.0
```

Verify:

```bash
sudo /opt/piradio-wifi/venv/bin/python -c \
"from pi_wifi_setup import SetupMode; print('pi-wifi-setup OK')"
```

---

## 9. Patch pi-wifi-setup

Find the installed package directory:

```bash
WIFI_PKG_DIR=$(
  sudo /opt/piradio-wifi/venv/bin/python -c \
  'import pi_wifi_setup, pathlib; print(pathlib.Path(pi_wifi_setup.__file__).parent)'
)
echo "$WIFI_PKG_DIR"
```

Back up the original files:

```bash
sudo cp "$WIFI_PKG_DIR/wifi_connector.py" "$WIFI_PKG_DIR/wifi_connector.py.bak"
sudo cp "$WIFI_PKG_DIR/web_server.py" "$WIFI_PKG_DIR/web_server.py.bak"
```

Copy the supplied `wifi_connector.py` from this kit over:

```text
$WIFI_PKG_DIR/wifi_connector.py
```

For example, if the kit is in `~/piradio-install-kit`:

```bash
sudo cp ~/piradio-install-kit/wifi_connector.py "$WIFI_PKG_DIR/wifi_connector.py"
```

Prevent the portal from stripping leading/trailing spaces from real Wi-Fi passwords:

```bash
sudo sed -i \
's/password = request\.form\.get("password", "")\.strip()/password = request.form.get("password", "")/' \
"$WIFI_PKG_DIR/web_server.py"
```

Disable password-manager autofill in the portal:

```bash
sudo sed -i \
's/autocomplete="current-password"/autocomplete="off"/' \
"$WIFI_PKG_DIR/templates/index.html"
```

Syntax check:

```bash
sudo /opt/piradio-wifi/venv/bin/python -m py_compile \
"$WIFI_PKG_DIR/wifi_connector.py" \
"$WIFI_PKG_DIR/web_server.py"
```

---

## 10. Install the fallback controller

Copy the supplied `fallback.py` to:

```text
/opt/piradio-wifi/fallback.py
```

For example:

```bash
sudo cp ~/piradio-install-kit/fallback.py /opt/piradio-wifi/fallback.py
sudo chmod +x /opt/piradio-wifi/fallback.py
```

Syntax check:

```bash
sudo /opt/piradio-wifi/venv/bin/python -m py_compile \
/opt/piradio-wifi/fallback.py
```

Short foreground test while normal Wi-Fi is still connected:

```bash
sudo timeout 10 \
/opt/piradio-wifi/venv/bin/python \
/opt/piradio-wifi/fallback.py
```

Expected:

```text
INFO: PiRadio WiFi fallback started
```

---

## 11. Install the fallback systemd service

Copy `piradio-wifi-fallback.service` from the kit to:

```text
/etc/systemd/system/piradio-wifi-fallback.service
```

Or create:

```ini
[Unit]
Description=PiRadio automatic WiFi setup fallback
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=/opt/piradio-wifi/venv/bin/python /opt/piradio-wifi/fallback.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now piradio-wifi-fallback.service
```

Verify:

```bash
systemctl status piradio-wifi-fallback.service --no-pager
journalctl -u piradio-wifi-fallback.service -n 20 --no-pager
nmcli device status
```

---

## 12. Reboot test

```bash
sudo reboot
```

After reconnecting:

```bash
nmcli device status
systemctl status piradio.service --no-pager
systemctl status piradio-wifi-fallback.service --no-pager
journalctl -u piradio-wifi-fallback.service -b --no-pager
```

Normal Wi-Fi should connect and the fallback service should remain idle.

---

## 13. Deliberate Wi-Fi fallback test

For faster testing, temporarily change 120 seconds to 20 seconds:

```bash
sudo sed -i \
's/FAIL_TIMEOUT = 120/FAIL_TIMEOUT = 20/' \
/opt/piradio-wifi/fallback.py

sudo systemctl restart piradio-wifi-fallback.service
```

Find the active Wi-Fi connection profile:

```bash
nmcli connection show --active
```

Suppose its name is `zlatororog6`. Disable its autoconnect and disconnect it:

```bash
sudo nmcli connection modify zlatororog6 connection.autoconnect no
sudo nmcli connection down zlatororog6
```

SSH will disconnect.

After about 20–30 seconds:

- the radio display should switch to the Wi-Fi setup screen
- the phone should see Wi-Fi `PiRadio-Setup`
- password: `piradio123`
- setup page: `http://192.168.4.1`

Connect the phone, open the setup page, choose the desired Wi-Fi, enter its password and submit.

The Pi saves the profile, reboots, and reconnects.

SSH back in and restore the production timeout:

```bash
sudo sed -i \
's/FAIL_TIMEOUT = 20/FAIL_TIMEOUT = 120/' \
/opt/piradio-wifi/fallback.py

sudo systemctl restart piradio-wifi-fallback.service
```

Verify:

```bash
grep FAIL_TIMEOUT /opt/piradio-wifi/fallback.py
nmcli device status
```

Expected:

```text
FAIL_TIMEOUT = 120
```

---

## 14. Final operational checks

```bash
systemctl is-enabled piradio.service
systemctl is-active piradio.service

systemctl is-enabled piradio-wifi-fallback.service
systemctl is-active piradio-wifi-fallback.service

nmcli device status
aplay -l
ls -l /dev/spidev0.1
```

Both systemd services should be enabled and active.

---

## Important maintenance note

`pi-wifi-setup==1.0.0` is deliberately patched inside its virtual environment.

Do not casually run:

```bash
sudo /opt/piradio-wifi/venv/bin/pip install --upgrade pi-wifi-setup
```

because an upgrade can overwrite the custom `wifi_connector.py`, `web_server.py`, and template changes.

The AP values must also stay consistent between `radio.py` and `fallback.py`:

```text
SSID:     PiRadio-Setup
Password: piradio123
IP:       192.168.4.1
```
