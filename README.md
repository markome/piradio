# PiRadio

Internet radio for a Raspberry Pi Zero 2 W and Pimoroni Pirate Audio 3W Stereo Amp. It uses a ST7789 display, hardware buttons, and `mpv`. The optional Wi-Fi fallback uses a separate Python environment and a captive portal.

## Supported installation

The installer is prepared for **Raspberry Pi OS Bookworm**, with username `pi`, an active internet connection, and the Pirate Audio HAT fitted. The program and service files use `/home/pi/radio` and `/home/pi/.virtualenvs/pimoroni` explicitly. Use Raspberry Pi Imager to set the username to `pi`, enable SSH, and configure Wi-Fi before running it.

On the Raspberry Pi:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

SSH in again, then:

```bash
git clone https://github.com/markome/piradio.git ~/piradio
cd ~/piradio
sudo bash scripts/install.sh
sudo reboot
```

The installer installs Debian and Python dependencies, configures SPI and the DAC in `/boot/firmware/config.txt` (with a `.piradio-backup` on the first edit), places the radio code in `/home/pi/radio`, and enables `piradio.service`. It preserves an existing `stations.json` and `state.json`, so your saved stations and volume survive reruns. Review the boot configuration if it already contains audio overlay settings.

After reboot:

```bash
systemctl status piradio.service --no-pager
journalctl -u piradio.service -n 50 --no-pager
aplay -l
ls -l /dev/spidev0.1
```

To change stations, edit `/home/pi/radio/stations.json` on the Pi. The repository copy is installed only when no station file exists.

## Optional Wi-Fi setup portal

This option depends on NetworkManager, `pi-wifi-setup==1.0.0`, and a local patch to that package. The portal has displayed successfully on the original Pi, but reconnecting after submitting credentials has not yet been confirmed end to end. Keep SSH or physical access available while testing it.

```bash
cd ~/piradio
sudo bash scripts/install.sh --with-wifi-fallback
sudo reboot
```

The installer keeps the radio and portal in separate virtual environments. It backs up upstream package files before patching them, and enables `piradio-wifi-fallback.service`. After two minutes without Wi-Fi, the portal should advertise `PiRadio-Setup` with password `piradio123` at `http://192.168.4.1`. Those values are also hard-coded in `radio.py` and `wifi/fallback.py`; change both files together if needed. The AP password is public in this repository and must not be treated as private.

```bash
systemctl status piradio-wifi-fallback.service --no-pager
journalctl -u piradio-wifi-fallback.service -b --no-pager
nmcli device status
```

Confirm that a newly submitted Wi-Fi password actually leads to a connection before relying on the fallback. Do not upgrade `pi-wifi-setup` in its virtual environment without reapplying and checking the patch. The installer's layout checks will stop before enabling the service if the upstream files differ.

## Updating

```bash
cd ~/piradio
git pull
sudo bash scripts/install.sh                  # or add --with-wifi-fallback
sudo reboot
```

If you edit stations locally, keep the edit in `/home/pi/radio/stations.json` rather than the Git checkout.

## Files

- `radio.py`, `stations.json`: radio application and default station list
- `wifi/`: optional fallback controller and patched NetworkManager connector
- `systemd/`: services, with paths matching the installer
- `requirements.txt`, `requirements-wifi.txt`: Python dependencies for separate environments
- `scripts/install.sh`: Bookworm installation script

## Development

PiRadio was developed and maintained by Marko Meža with substantial assistance from OpenAI ChatGPT.

ChatGPT was used extensively during development for code generation, debugging, refactoring, documentation, installation scripts, and implementation guidance. The project was reviewed, tested, integrated, and maintained by the repository author.

## License

MIT; see [LICENSE](LICENSE).
