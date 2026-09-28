import subprocess
import logging

logger = logging.getLogger(__name__)


class WiFiConnector:

    def __init__(self, interface: str = "wlan0"):
        self.interface = interface

    def has_credentials(self) -> bool:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True,
            text=True,
        )

        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] in ("wifi", "802-11-wireless"):
                return True

        return False

    def _run(self, args):
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(
                "Command failed: %s\nstdout: %s\nstderr: %s",
                " ".join(args),
                result.stdout.strip(),
                result.stderr.strip(),
            )

        return result

    def connect(self, ssid: str, password: str, timeout: int = 30) -> bool:
        """
        Save/update WiFi credentials only.

        Do not try to connect while PiRadio-Setup AP is active.
        The fallback service will reboot after saving the profile.
        """

        result = self._run(
            ["nmcli", "-t", "-f", "NAME", "connection", "show"]
        )

        existing = ssid in result.stdout.splitlines()

        if not existing:
            result = self._run([
                "nmcli", "connection", "add",
                "type", "wifi",
                "ifname", self.interface,
                "con-name", ssid,
                "ssid", ssid,
            ])

            if result.returncode != 0:
                return False

        result = self._run([
            "nmcli", "connection", "modify", ssid,
            "802-11-wireless.ssid", ssid,
            "connection.interface-name", self.interface,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", "50",
        ])

        if result.returncode != 0:
            return False

        if password:
            result = self._run([
                "nmcli", "connection", "modify", ssid,
                "802-11-wireless-security.key-mgmt", "wpa-psk",
                "802-11-wireless-security.psk", password,
                "802-11-wireless-security.psk-flags", "0",
            ])

            if result.returncode != 0:
                return False

        logger.info(
            "WiFi credentials saved for '%s'; connection will occur after reboot",
            ssid,
        )

        return True

    def get_status(self) -> dict:
        result = subprocess.run(
            [
                "nmcli", "-t", "-f",
                "DEVICE,STATE,CONNECTION",
                "device", "status",
            ],
            capture_output=True,
            text=True,
        )

        for line in result.stdout.strip().splitlines():
            parts = line.split(":")

            if len(parts) >= 3 and parts[0] == self.interface:
                connected = parts[1] == "connected"
                ssid = parts[2] if connected else ""
                ip = self._get_ip() if connected else ""

                return {
                    "connected": connected,
                    "ssid": ssid,
                    "ip_address": ip,
                    "wpa_state": "COMPLETED" if connected else "DISCONNECTED",
                }

        return {
            "connected": False,
            "ssid": "",
            "ip_address": "",
            "wpa_state": "DISCONNECTED",
        }

    def _get_ip(self) -> str:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", self.interface],
            capture_output=True,
            text=True,
        )

        for line in result.stdout.splitlines():
            line = line.strip()

            if line.startswith("inet "):
                return line.split()[1].split("/")[0]

        return ""
