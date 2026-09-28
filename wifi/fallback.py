#!/usr/bin/env python3

import subprocess
import time
import logging

from pi_wifi_setup import SetupMode

WIFI_INTERFACE = "wlan0"
AP_SSID = "PiRadio-Setup"
AP_PASSWORD = "piradio123"

FAIL_TIMEOUT = 120
CHECK_INTERVAL = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)


def wifi_connected():
    try:
        result = subprocess.run(
            [
                "nmcli",
                "-g", "GENERAL.STATE",
                "device", "show",
                WIFI_INTERFACE,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        return result.stdout.strip().startswith("100")

    except Exception as e:
        logging.warning("WiFi status check failed: %s", e)
        return False


def start_setup():
    logging.warning("Starting PiRadio WiFi setup hotspot")

    setup = SetupMode(
        ap_ssid=AP_SSID,
        ap_password=AP_PASSWORD,
        wifi_interface=WIFI_INTERFACE,
        auto_on_no_credentials=False,
    )

    setup.run_blocking()

    logging.info("WiFi credentials saved; rebooting")
    subprocess.run(["systemctl", "reboot"])


def main():
    logging.info("PiRadio WiFi fallback started")

    offline_since = None

    while True:

        if wifi_connected():

            if offline_since is not None:
                logging.info("WiFi connection restored")

            offline_since = None

        else:

            if offline_since is None:
                offline_since = time.monotonic()
                logging.warning(
                    "WiFi disconnected; starting %d second timer",
                    FAIL_TIMEOUT,
                )

            elapsed = time.monotonic() - offline_since

            if elapsed >= FAIL_TIMEOUT:

                logging.warning(
                    "WiFi unavailable for %d seconds",
                    FAIL_TIMEOUT,
                )

                try:
                    start_setup()

                except Exception:
                    logging.exception("WiFi setup failed")
                    time.sleep(30)

                offline_since = None

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
