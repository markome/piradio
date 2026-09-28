#!/usr/bin/env python3

import json
import socket
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont
import st7789


# ============================================================
# FILES / HARDWARE
# ============================================================

STATIONS_FILE = Path("/home/pi/radio/stations.json")
STATE_FILE = Path("/home/pi/radio/state.json")
MPV_SOCKET = "/tmp/mpvsocket"

BUTTONS = [5, 6, 16, 24]
LABELS = ["A", "B", "X", "Y"]


# ============================================================
# SETTINGS
# ============================================================

LCD_TIMEOUT = 2 * 60 * 60
WEATHER_UPDATE = 15 * 60
SCREEN_UPDATE = 1

SPI_SPEED = 40 * 1000 * 1000

# Wi-Fi fallback setup access point.
# These values must match /opt/piradio-wifi/fallback.py.
SETUP_AP_SSID = "PiRadio-Setup"
SETUP_AP_PASSWORD = "piradio123"
SETUP_AP_IP = "192.168.4.1"

# Playback watchdog:
#
# Every 10 seconds check whether playback-time is advancing.
# If playback has not advanced for 45 seconds, restart the
# currently selected station.
#
# A startup grace period prevents false restarts while a
# station is initially connecting/buffering.

WATCHDOG_CHECK_INTERVAL = 10
WATCHDOG_STALL_TIMEOUT = 45
WATCHDOG_STARTUP_GRACE = 20

# Maximum time to wait for a reply from mpv IPC.
MPV_IPC_TIMEOUT = 2.0


# ============================================================
# GLOBAL STATE
# ============================================================

index = 0
volume = 70

player = None
current_title = ""

weather_text = ""
last_weather_update = 0

last_activity = time.time()
lcd_on = True
dots = 0

display = None
WIDTH = 240
HEIGHT = 240

display_lock = threading.Lock()
action_lock = threading.Lock()


# Watchdog state

player_started_at = 0
last_watchdog_check = 0
last_playback_time = None
last_playback_progress = 0


# ============================================================
# LOAD STATIONS / FONTS
# ============================================================

stations = json.loads(
    STATIONS_FILE.read_text(encoding="utf-8")
)

font_title = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    21
)

font_med = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    15
)

font_small = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    12
)


# ============================================================
# DISPLAY
# ============================================================

def init_display():
    global display, WIDTH, HEIGHT, lcd_on

    display = st7789.ST7789(
        rotation=90,
        port=0,
        cs=1,
        dc=9,
        backlight=13,
        spi_speed_hz=SPI_SPEED
    )

    WIDTH = display.width
    HEIGHT = display.height
    lcd_on = True

    try:
        display.set_backlight(1)
    except Exception:
        pass


def shorten(text, max_len):
    if not text:
        return ""

    if len(text) <= max_len:
        return text

    return text[:max_len - 3] + "..."


def split_text(text, max_len=25):
    if not text:
        return "", ""

    text = text.strip()

    if len(text) <= max_len:
        return text, ""

    cut = text.rfind(" ", 0, max_len)

    if cut == -1:
        cut = max_len

    line1 = text[:cut].strip()
    rest = text[cut:].strip()

    if len(rest) > max_len:
        rest = rest[:max_len - 3] + "..."

    return line1, rest


# ============================================================
# NETWORK INFORMATION
# ============================================================

def get_wifi_info():
    try:
        ssid = subprocess.check_output(
            ["iwgetid", "-r"],
            text=True
        ).strip()

        output = subprocess.check_output(
            "iwconfig wlan0 | grep 'Link Quality'",
            shell=True,
            text=True
        )

        quality = "?"

        if "Link Quality=" in output:
            q = output.split("Link Quality=")[1].split()[0]
            current, maximum = q.split("/")

            quality = str(
                round(int(current) * 100 / int(maximum))
            )

        return ssid if ssid else "no wifi", quality

    except Exception:
        return "no wifi", "?"


def get_ip_address():
    try:
        ips = subprocess.check_output(
            ["hostname", "-I"],
            text=True
        ).strip().split()

        for ip in ips:
            if "." in ip:
                return ip

        return ips[0] if ips else "no ip"

    except Exception:
        return "no ip"


def wifi_setup_active():
    """Return True while the PiRadio setup access point is active."""
    try:
        result = subprocess.run(
            [
                "ip",
                "-4",
                "addr",
                "show",
                "dev",
                "uap0"
            ],
            capture_output=True,
            text=True,
            timeout=2
        )

        return (
            result.returncode == 0
            and SETUP_AP_IP in result.stdout
        )

    except Exception:
        return False


# ============================================================
# WEATHER
# ============================================================

def get_weather():
    try:
        out = subprocess.check_output(
            [
                "curl",
                "-s",
                "--max-time",
                "5",
                "wttr.in/Ljubljana?format=%C,%20%t"
            ],
            text=True
        ).strip()

        return out if out else "weather ?"

    except Exception:
        return "weather ?"


def update_weather_if_needed():
    global weather_text
    global last_weather_update

    now = time.time()

    if (
        now - last_weather_update > WEATHER_UPDATE
        or not weather_text
    ):
        weather_text = get_weather()
        last_weather_update = now


# ============================================================
# LCD POWER
# ============================================================

def set_lcd_power(on):
    global lcd_on

    lcd_on = on

    try:
        display.set_backlight(1 if on else 0)
    except Exception:
        pass


def wake_lcd():
    global last_activity

    last_activity = time.time()

    if not lcd_on:
        set_lcd_power(True)
        draw_screen()


# ============================================================
# SCREEN DRAWING
# ============================================================

def show_message(line1, line2=""):
    with display_lock:
        set_lcd_power(True)

        img = Image.new(
            "RGB",
            (WIDTH, HEIGHT),
            (0, 0, 0)
        )

        draw = ImageDraw.Draw(img)

        draw.text(
            (20, 80),
            line1,
            font=font_title,
            fill=(255, 255, 255)
        )

        draw.text(
            (20, 120),
            line2,
            font=font_med,
            fill=(180, 220, 255)
        )

        display.display(img)


def draw_screen():
    setup_active = wifi_setup_active()

    # Keep the display awake while Wi-Fi setup mode is active.
    if not lcd_on and not setup_active:
        return

    if setup_active and not lcd_on:
        set_lcd_power(True)

    with display_lock:

        # ----------------------------------------------------
        # Wi-Fi setup screen
        # ----------------------------------------------------

        if setup_active:
            img = Image.new(
                "RGB",
                (WIDTH, HEIGHT),
                (0, 0, 0)
            )

            draw = ImageDraw.Draw(img)

            draw.text(
                (10, 12),
                "Wi-Fi SETUP",
                font=font_title,
                fill=(255, 255, 255)
            )

            draw.line(
                (10, 45, 230, 45),
                fill=(70, 70, 70)
            )

            draw.text(
                (10, 58),
                "Connect phone to:",
                font=font_small,
                fill=(180, 180, 180)
            )

            draw.text(
                (10, 78),
                SETUP_AP_SSID,
                font=font_med,
                fill=(180, 220, 255)
            )

            draw.text(
                (10, 111),
                "Password:",
                font=font_small,
                fill=(180, 180, 180)
            )

            draw.text(
                (10, 131),
                SETUP_AP_PASSWORD,
                font=font_title,
                fill=(255, 220, 160)
            )

            draw.text(
                (10, 174),
                "Open in browser:",
                font=font_small,
                fill=(180, 180, 180)
            )

            draw.text(
                (10, 194),
                f"http://{SETUP_AP_IP}",
                font=font_med,
                fill=(180, 220, 255)
            )

            draw.text(
                (10, 222),
                "Configure Wi-Fi, then Pi reboots",
                font=font_small,
                fill=(120, 120, 120)
            )

            display.display(img)
            return

        # ----------------------------------------------------
        # Normal radio screen
        # ----------------------------------------------------

        update_weather_if_needed()

        station = stations[index]

        wifi, quality = get_wifi_info()
        ip = get_ip_address()

        title1, title2 = split_text(
            current_title,
            25
        )

        now = datetime.now().strftime("%H:%M")
        dot_text = "." * dots

        img = Image.new(
            "RGB",
            (WIDTH, HEIGHT),
            (0, 0, 0)
        )

        draw = ImageDraw.Draw(img)

        draw.text(
            (10, 4),
            f"{now}  {shorten(weather_text, 22)}",
            font=font_small,
            fill=(220, 220, 180)
        )

        draw.text(
            (10, 20),
            f"WiFi: {shorten(wifi, 11)} {quality}%",
            font=font_small,
            fill=(120, 180, 120)
        )

        draw.text(
            (10, 36),
            f"IP: {ip}",
            font=font_small,
            fill=(120, 180, 255)
        )

        draw.line(
            (10, 54, 230, 54),
            fill=(70, 70, 70)
        )

        draw.text(
            (10, 66),
            shorten(station["name"], 18),
            font=font_title,
            fill=(255, 255, 255)
        )

        draw.text(
            (10, 97),
            f"Vol: {volume}%   {index + 1}/{len(stations)}",
            font=font_med,
            fill=(180, 220, 255)
        )

        draw.text(
            (10, 124),
            f"Now playing{dot_text}",
            font=font_small,
            fill=(160, 160, 160)
        )

        draw.text(
            (10, 145),
            title1,
            font=font_med,
            fill=(255, 220, 160)
        )

        draw.text(
            (10, 168),
            title2,
            font=font_med,
            fill=(255, 220, 160)
        )

        draw.text(
            (10, 218),
            "A/B station, X/Y VOL, A+B PWR",
            font=font_small,
            fill=(120, 120, 120)
        )

        display.display(img)


# ============================================================
# SAVE / LOAD STATE
# ============================================================

def load_state():
    global index
    global volume

    try:
        state = json.loads(
            STATE_FILE.read_text()
        )

        index = int(
            state.get("index", 0)
        ) % len(stations)

        volume = int(
            state.get("volume", 70)
        )

    except Exception:
        index = 0
        volume = 70


def save_state():
    STATE_FILE.write_text(
        json.dumps(
            {
                "index": index,
                "volume": volume
            }
        )
    )


# ============================================================
# MPV IPC
# ============================================================

def mpv_command(command):
    """
    Send one command to the mpv IPC socket.

    The timeout is important: if mpv itself becomes unresponsive,
    this function must not freeze radio.py forever.
    """

    try:
        with socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM
        ) as s:

            s.settimeout(MPV_IPC_TIMEOUT)

            s.connect(MPV_SOCKET)

            message = json.dumps(command) + "\n"

            s.sendall(
                message.encode("utf-8")
            )

            data = b""

            while b"\n" not in data:
                chunk = s.recv(4096)

                if not chunk:
                    break

                data += chunk

                if len(data) > 65536:
                    break

            if not data:
                return None

            first_line = data.split(
                b"\n",
                1
            )[0]

            return json.loads(
                first_line.decode(
                    "utf-8",
                    errors="ignore"
                )
            )

    except Exception:
        return None


def get_mpv_property(name):
    response = mpv_command(
        {
            "command": [
                "get_property",
                name
            ]
        }
    )

    if not response:
        return None

    if response.get("error") != "success":
        return None

    return response.get("data")


def get_current_title():
    metadata = get_mpv_property("metadata")

    if not metadata:
        return ""

    for key in [
        "icy-title",
        "title",
        "TITLE"
    ]:
        if key in metadata and metadata[key]:
            return str(metadata[key])

    return ""


# ============================================================
# WATCHDOG
# ============================================================

def reset_playback_watchdog():
    global player_started_at
    global last_watchdog_check
    global last_playback_time
    global last_playback_progress

    now = time.time()

    player_started_at = now
    last_watchdog_check = 0
    last_playback_time = None
    last_playback_progress = now


def check_playback_watchdog():
    """
    Detect two failure modes:

    1. mpv process has exited.
    2. mpv is still running, but playback-time no longer advances.

    In either case the CURRENT station is restarted.
    """

    global last_watchdog_check
    global last_playback_time
    global last_playback_progress

    now = time.time()

    # Do not query mpv every second.
    if now - last_watchdog_check < WATCHDOG_CHECK_INTERVAL:
        return

    last_watchdog_check = now

    # --------------------------------------------------------
    # Failure mode 1: mpv has exited
    # --------------------------------------------------------

    if player is None:
        print(
            "WATCHDOG: mpv is not running - reconnecting",
            flush=True
        )

        play_radio(
            show_switch_message=False
        )

        return

    if player.poll() is not None:
        print(
            "WATCHDOG: mpv exited - reconnecting",
            flush=True
        )

        play_radio(
            show_switch_message=False
        )

        return

    # --------------------------------------------------------
    # Give a newly started station time to connect/buffer
    # --------------------------------------------------------

    if now - player_started_at < WATCHDOG_STARTUP_GRACE:
        return

    # --------------------------------------------------------
    # Failure mode 2: mpv exists but audio playback is frozen
    # --------------------------------------------------------

    playback_time = get_mpv_property(
        "playback-time"
    )

    if isinstance(
        playback_time,
        (int, float)
    ):
        playback_time = float(
            playback_time
        )

        # First valid measurement becomes our baseline.
        if last_playback_time is None:
            last_playback_time = playback_time
            last_playback_progress = now
            return

        difference = abs(
            playback_time - last_playback_time
        )

        # Playback time has moved.
        #
        # abs() is deliberate: some radio streams can reset
        # timestamps, and that should still count as activity.
        if difference >= 0.5:
            last_playback_time = playback_time
            last_playback_progress = now
            return

    # If playback_time is unchanged OR IPC failed, do not
    # immediately restart. Wait for the stall timeout.

    stalled_for = now - last_playback_progress

    if stalled_for >= WATCHDOG_STALL_TIMEOUT:

        station = stations[index]

        print(
            f"WATCHDOG: playback stalled for "
            f"{int(stalled_for)} s - restarting "
            f"{station['name']}",
            flush=True
        )

        play_radio(
            show_switch_message=False
        )


# ============================================================
# MPV PLAYER
# ============================================================

def stop_radio():
    global player

    if player:
        try:
            player.terminate()

            player.wait(
                timeout=2
            )

        except subprocess.TimeoutExpired:
            try:
                player.kill()
                player.wait(timeout=1)
            except Exception:
                pass

        except Exception:
            pass

        player = None


def play_radio(show_switch_message=True):
    global player
    global current_title

    with action_lock:

        stop_radio()

        current_title = ""

        try:
            Path(MPV_SOCKET).unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

        station = stations[index]

        # Automatic watchdog recovery should not wake the LCD
        # if it has timed out.
        if show_switch_message and lcd_on:
            show_message(
                "Switching...",
                shorten(
                    station["name"],
                    18
                )
            )

        player = subprocess.Popen(
            [
                "mpv",

                "--no-video",
                "--quiet",

                "--ao=alsa",

                "--audio-device="
                "alsa/sysdefault:CARD=sndrpihifiberry",

                # Let FFmpeg reconnect automatically after
                # ordinary HTTP stream interruptions.
                "--demuxer-lavf-o="
                "reconnect=1,"
                "reconnect_streamed=1,"
                "reconnect_delay_max=5",

                f"--input-ipc-server={MPV_SOCKET}",

                f"--volume={volume}",

                station["url"]
            ]
        )

        reset_playback_watchdog()

        print(
            f"Playing: {station['name']}  "
            f"Volume: {volume}",
            flush=True
        )

        time.sleep(0.5)

        draw_screen()


# ============================================================
# RADIO CONTROLS
# ============================================================

def change_station(delta):
    global index

    index = (
        index + delta
    ) % len(stations)

    save_state()

    play_radio(
        show_switch_message=True
    )


def change_volume(delta):
    global volume

    volume = max(
        0,
        min(
            100,
            volume + delta
        )
    )

    save_state()

    mpv_command(
        {
            "command": [
                "set_property",
                "volume",
                volume
            ]
        }
    )

    draw_screen()

    print(
        f"Volume: {volume}",
        flush=True
    )


# ============================================================
# BUTTONS
# ============================================================

def buttons_pressed(pins):
    return all(
        GPIO.input(pin) == GPIO.LOW
        for pin in pins
    )


def check_special_buttons():

    # A + B = shutdown
    if buttons_pressed([5, 6]):

        show_message(
            "Hold A+B",
            "Shutdown in 3 s"
        )

        start = time.time()

        while time.time() - start < 3:

            if not buttons_pressed([5, 6]):
                draw_screen()
                return False

            time.sleep(0.1)

        show_message(
            "Shutdown...",
            "Wait, then unplug"
        )

        time.sleep(1)

        stop_radio()

        subprocess.Popen(
            [
                "sudo",
                "shutdown",
                "-h",
                "now"
            ]
        )

        return True

    # X + Y = reboot
    if buttons_pressed([16, 24]):

        show_message(
            "Hold X+Y",
            "Reboot in 3 s"
        )

        start = time.time()

        while time.time() - start < 3:

            if not buttons_pressed([16, 24]):
                draw_screen()
                return False

            time.sleep(0.1)

        show_message(
            "Rebooting...",
            "Please wait"
        )

        time.sleep(1)

        stop_radio()

        subprocess.Popen(
            [
                "sudo",
                "reboot"
            ]
        )

        return True

    return False


def handle_button(pin):

    was_off = not lcd_on

    wake_lcd()

    # First button press after display timeout only wakes LCD.
    if was_off:
        return

    # Check combinations before interpreting individual buttons.
    if buttons_pressed([5, 6]):
        check_special_buttons()
        return

    if buttons_pressed([16, 24]):
        check_special_buttons()
        return

    label = LABELS[
        BUTTONS.index(pin)
    ]

    if label == "A":
        change_station(-1)

    elif label == "B":
        change_station(1)

    elif label == "X":
        change_volume(5)

    elif label == "Y":
        change_volume(-5)


# ============================================================
# MAIN
# ============================================================

def main():
    global current_title
    global dots

    load_state()

    init_display()

    update_weather_if_needed()

    GPIO.setmode(
        GPIO.BCM
    )

    GPIO.setup(
        BUTTONS,
        GPIO.IN,
        pull_up_down=GPIO.PUD_UP
    )

    for pin in BUTTONS:
        GPIO.add_event_detect(
            pin,
            GPIO.FALLING,
            handle_button,
            bouncetime=300
        )

    play_radio(
        show_switch_message=True
    )

    try:

        while True:

            # ------------------------------------------------
            # Automatic stream recovery
            # ------------------------------------------------

            check_playback_watchdog()

            # ------------------------------------------------
            # LCD timeout
            # ------------------------------------------------

            if (
                lcd_on
                and not wifi_setup_active()
                and
                time.time() - last_activity > LCD_TIMEOUT
            ):
                set_lcd_power(False)

            # ------------------------------------------------
            # Current song / ICY metadata
            # ------------------------------------------------

            new_title = get_current_title()

            if new_title != current_title:
                current_title = new_title

            # ------------------------------------------------
            # Screen animation
            # ------------------------------------------------

            dots = (
                dots + 1
            ) % 4

            draw_screen()

            time.sleep(
                SCREEN_UPDATE
            )

    except KeyboardInterrupt:

        print(
            "Stopping...",
            flush=True
        )

    finally:

        stop_radio()

        GPIO.cleanup()

        current_title = "Stopped"

        set_lcd_power(True)

        draw_screen()


if __name__ == "__main__":
    main()
