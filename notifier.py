"""
MoodTune Notifier – System Tray + Smart Mood Check-In Notifications

Runs as a background process in the Windows system tray.
Auto-launched by app.py when Flask starts – no manual startup needed.

Behaviour:
  • Polls premium_state.json every 5 seconds.
  • When premium is ACTIVATED  → shows an immediate notification.
  • While premium is ACTIVE     → shows notifications every 1-2 minutes.
  • When premium is DEACTIVATED → stops all notifications silently.
  • Clicking any notification opens MoodTune in the default browser.

Dependencies:
  - pystray + Pillow  → system tray icon
  - PowerShell WinRT  → native Windows 10/11 toast (built-in, no install)
"""

import atexit
import os
import random
import subprocess
import threading
import time
import webbrowser
import json as _json

from PIL import Image, ImageDraw, ImageFont
from pystray import Icon, Menu, MenuItem


# ── Configuration ────────────────────────────────────────────────────
MOODTUNE_URL       = "http://localhost:5000"
APP_NAME           = "MoodTune"

# How often (seconds) to poll for premium-status changes
POLL_INTERVAL      = 5

# Notification interval range (seconds) while premium is active
MIN_INTERVAL       = 1 * 60    # 1 minute
MAX_INTERVAL       = 2 * 60    # 2 minutes

# Shared state file (same directory as this script / app.py)
_BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
PREMIUM_STATE_FILE = os.path.join(_BASE_DIR, "premium_state.json")
PID_FILE           = os.path.join(_BASE_DIR, "notifier.pid")

# Pool of friendly check-in messages
CHECKIN_MESSAGES = [
    ("How are you feeling today?",               "Tap to let MoodTune find your perfect playlist."),
    ("Time for a mood check-in!",                "Tell us how you feel and discover matching music."),
    ("What's your vibe right now?",              "MoodTune is ready to match your mood with music."),
    ("Let MoodTune find your perfect playlist",  "Share your mood and we'll do the rest."),
    ("Hey! How's your day going?",               "Check in with MoodTune and get personalized music."),
    ("Feeling stressed? Happy? Calm?",           "Let MoodTune recommend the perfect soundtrack."),
    ("Music therapy time!",                      "Tell MoodTune your mood for instant playlist magic."),
    ("Your mood matters",                        "Take a moment to check in with MoodTune."),
]


# ── PID file helpers ─────────────────────────────────────────────────
def _write_pid() -> None:
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _remove_pid() -> None:
    try:
        os.remove(PID_FILE)
    except Exception:
        pass


# ── Premium state reader ─────────────────────────────────────────────
def _is_premium() -> bool:
    """
    Read premium status from premium_state.json (written by app.py).
    Falls back to the HTTP endpoint if the file doesn't exist yet.
    Returns False on any error so we never spam on an unknown state.
    """
    # Primary: shared JSON file (survives Flask restarts, no HTTP needed)
    try:
        with open(PREMIUM_STATE_FILE, "r", encoding="utf-8") as f:
            return bool(_json.load(f).get("premium", False))
    except FileNotFoundError:
        pass          # file doesn't exist yet – fall through to HTTP
    except Exception as e:
        print(f"[MoodTune Notifier] premium_state.json read error: {e}")

    # Fallback: ask the running Flask server
    try:
        import urllib.request
        with urllib.request.urlopen(f"{MOODTUNE_URL}/premium", timeout=2) as resp:
            data = _json.loads(resp.read())
            return bool(data.get("premium", False))
    except Exception:
        return False


# ── Windows Toast Notification (PowerShell WinRT) ────────────────────
def show_windows_notification(title: str, message: str,
                               on_click_url: str | None = None) -> bool:
    """
    Show a native Windows 10/11 toast notification via PowerShell WinRT.

    Uses PowerShell's built-in Windows.UI.Notifications API – works without
    a registered app_id (unlike winotify which silently drops such toasts).
    Clicking the notification opens the given URL in the default browser.
    """
    url = on_click_url or MOODTUNE_URL

    def _xml_escape(s: str) -> str:
        return (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&apos;")
        )

    safe_title   = _xml_escape(title)
    safe_message = _xml_escape(message)
    safe_url     = _xml_escape(url)

    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast activationType="protocol" launch="{safe_url}">
  <visual>
    <binding template="ToastGeneric">
      <text>{safe_title}</text>
      <text>{safe_message}</text>
    </binding>
  </visual>
  <actions>
    <action content="Open MoodTune" activationType="protocol" arguments="{safe_url}" />
  </actions>
</toast>
"@

$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("MoodTune")
$notifier.Show($toast)
"""

    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"[MoodTune Notifier] Toast error: {result.stderr.strip()[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[MoodTune Notifier] Notification error: {e}")
        return False


# ── Tray Icon Generation ─────────────────────────────────────────────
def create_tray_icon_image() -> Image.Image:
    """Create a gradient circle with a music note – used as the tray icon."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for i in range(size // 2, 0, -1):
        ratio = i / (size // 2)
        r = int(124 * ratio + 232 * (1 - ratio))
        g = int(92  * ratio + 67  * (1 - ratio))
        b = int(252 * ratio + 147 * (1 - ratio))
        bbox = [size // 2 - i, size // 2 - i, size // 2 + i, size // 2 + i]
        draw.ellipse(bbox, fill=(r, g, b, 255))

    try:
        font = ImageFont.truetype("segoeui.ttf", 32)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except (OSError, IOError):
            font = ImageFont.load_default()

    note = "♪"
    tb   = draw.textbbox((0, 0), note, font=font)
    draw.text(
        ((size - (tb[2] - tb[0])) // 2, (size - (tb[3] - tb[1])) // 2 - 2),
        note, fill=(255, 255, 255, 255), font=font,
    )
    return img


# ── Notification Logic ───────────────────────────────────────────────
class MoodTuneNotifier:
    """
    Background notifier that drives the system tray icon and smart
    mood check-in toasts.

    The notification loop polls premium_state.json every POLL_INTERVAL
    seconds so it reacts instantly when the user toggles Premium in the
    web app – no server restart or manual action required.
    """

    def __init__(self):
        self.running = True
        self.paused  = False
        self.icon    = None

    # ── Public actions ────────────────────────────────────────────────

    def open_moodtune(self):
        """Open MoodTune in the default web browser."""
        webbrowser.open(MOODTUNE_URL)

    def send_notification(self):
        """Pick a random message and fire a toast (no premium gate here –
        callers that need gating check _is_premium() themselves)."""
        title, message = random.choice(CHECKIN_MESSAGES)
        ok = show_windows_notification(title, message, on_click_url=MOODTUNE_URL)
        if ok:
            print(f"[MoodTune Notifier] [OK] Sent: '{title}'")

    def check_in_now(self):
        """Tray menu 'Check In Now': gate on premium then open browser."""
        if _is_premium():
            self.send_notification()
        else:
            print("[MoodTune Notifier] Check In Now skipped — Premium not active.")
        self.open_moodtune()

    def toggle_pause(self):
        self.paused = not self.paused
        print(f"[MoodTune Notifier] Notifications {'paused' if self.paused else 'resumed'}")

    def get_pause_text(self, _item):
        return "Resume Notifications" if self.paused else "Pause Notifications"

    def quit_app(self):
        self.running = False
        if self.icon:
            self.icon.stop()

    # ── Core notification loop ────────────────────────────────────────

    def _notification_loop(self):
        """
        Polls premium status every POLL_INTERVAL seconds.

        State machine:
          • premium OFF → ON  : send an immediate notification, reset timer.
          • premium ON  → OFF : log the change, stop sending.
          • premium ON, timer elapsed: send regular interval notification.
        """
        last_premium     = _is_premium()
        next_notify_at   = time.time() + random.randint(MIN_INTERVAL, MAX_INTERVAL)

        # If premium is already active at startup → immediate welcome notification
        if last_premium:
            print("[MoodTune Notifier] Premium active at startup – sending initial notification.")
            time.sleep(3)   # let the tray icon finish loading first
            if self.running and not self.paused:
                self.send_notification()
            next_notify_at = time.time() + random.randint(MIN_INTERVAL, MAX_INTERVAL)
        else:
            print("[MoodTune Notifier] Waiting for Premium activation…")

        while self.running:
            time.sleep(POLL_INTERVAL)

            if not self.running:
                break

            now_premium = _is_premium()

            if now_premium and not last_premium:
                # ── Premium just turned ON ───────────────────────────
                print("[MoodTune Notifier] *** Premium activated! Sending immediate notification.")
                if not self.paused:
                    self.send_notification()
                next_notify_at = time.time() + random.randint(MIN_INTERVAL, MAX_INTERVAL)

            elif not now_premium and last_premium:
                # ── Premium just turned OFF ──────────────────────────
                print("[MoodTune Notifier] Premium deactivated. Notifications paused.")

            elif now_premium and not self.paused and time.time() >= next_notify_at:
                # ── Regular interval notification ────────────────────
                self.send_notification()
                next_notify_at = time.time() + random.randint(MIN_INTERVAL, MAX_INTERVAL)

            last_premium = now_premium

    # ── Run ───────────────────────────────────────────────────────────

    def run(self):
        """Start the system tray icon and notification loop."""
        print(f"[MoodTune Notifier] Starting (PID {os.getpid()})…")
        print(f"[MoodTune Notifier] Polling every {POLL_INTERVAL}s | "
              f"Notifying every {MIN_INTERVAL//60}–{MAX_INTERVAL//60} min (Premium only)")
        print(f"[MoodTune Notifier] MoodTune URL : {MOODTUNE_URL}")
        print(f"[MoodTune Notifier] Premium state: {PREMIUM_STATE_FILE}")

        icon_image = create_tray_icon_image()

        menu = Menu(
            MenuItem("Open MoodTune",           lambda: self.open_moodtune()),
            MenuItem("Check In Now",             lambda: self.check_in_now()),
            Menu.SEPARATOR,
            MenuItem(self.get_pause_text,        lambda: self.toggle_pause()),
            Menu.SEPARATOR,
            MenuItem("Quit MoodTune Notifier",   lambda: self.quit_app()),
        )

        self.icon = Icon(
            name="MoodTune",
            icon=icon_image,
            title="MoodTune – Smart Mood Notifier",
            menu=menu,
        )

        threading.Thread(
            target=self._notification_loop, daemon=True, name="notifier-loop"
        ).start()

        self.icon.run()   # blocks until quit_app() is called

        self.running = False
        print("[MoodTune Notifier] Stopped.")


# ── Entry Point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    # Register PID file so app.py can detect we're running
    _write_pid()
    atexit.register(_remove_pid)

    notifier = MoodTuneNotifier()
    try:
        notifier.run()
    except KeyboardInterrupt:
        notifier.quit_app()
