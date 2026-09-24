"""
Small overlay showing remaining screen time.
Displays the remaining time information content from a text file.
"""

import ctypes
import math
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

# The installer passes the child's file, <shared>/<child>/remaining_time.txt;
# started by hand without one, the widget looks next to itself.
DEFAULT_REMAINING_TIME_FILE = Path(__file__).parent / "remaining_time.txt"
REMAINING_TIME_FILE_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REMAINING_TIME_FILE

# The monitor rewrites the file every 60 s, except through the ~190 s shutdown it
# starts when the time is up; past that it has died and the number means nothing.
STALE_AFTER_SECONDS = 300

# Display settings -- used by nothing but this widget.
POLL_INTERVAL_MS = 5000
# "Topmost" is a band, not a guarantee: among topmost windows the one raised
# last is on top, and a fullscreen game makes itself topmost when it starts.
# So the widget puts itself back on top this often. It cannot help against a
# game that takes the screen exclusively, where no other window is drawn at all.
RERAISE_INTERVAL_MS = 1000
SIDE_MARGIN_PX = 20
# Below the caption buttons of a maximised window. Clicks fall through the box
# anyway, but sitting on top of them hides which one is which.
TOP_MARGIN_PX = 38
# Which top corner to sit in, "right" or "left". Right is the real spot; left is
# for trying a copy out next to the one already running.
CORNER = "right"
OPACITY = 0.6
FONT_FAMILY = "Segoe UI"
FONT_SIZE = 14
WARNING_SECONDS = 15 * 60  # orange below this
CRITICAL_SECONDS = 5 * 60  # red below this
COLOR_NORMAL = "#2ecc71"
COLOR_WARNING = "#f39c12"
COLOR_CRITICAL = "#e74c3c"

# Ctrl+Alt+H hides the widget, the same combination brings it back. The keyboard
# state is read directly rather than claiming the combination from Windows, so
# it works whatever app has focus and cannot clash with another program's
# shortcut. The keys still reach that app as well.
HOTKEY_POLL_MS = 100
_VK_CONTROL = 0x11
_VK_ALT = 0x12
_VK_H = 0x48
HOTKEY_KEYS = (_VK_CONTROL, _VK_ALT, _VK_H)
_KEY_IS_DOWN = 0x8000

# Tk can make the window borderless, topmost, translucent and taskbar-free by
# itself. These are the two things it has no attribute for: clicks falling
# through to whatever is underneath (so the box never blocks the close button of
# a maximised window) and never taking focus from the app in use.
_GWL_EXSTYLE = -20
# Clicks only fall through a layered window. Tk layers the window as a side
# effect of an opacity below 1.0, but that is not relied on here.
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000
_LWA_ALPHA = 0x00000002
_GA_ROOT = 2  # winfo_id() names an inner window; this walks up to the real one
_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010

_user32 = ctypes.windll.user32
# Spelled out because the defaults would truncate window handles to 32 bits on
# 64-bit Windows.
_user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
_user32.SetLayeredWindowAttributes.argtypes = (
    wintypes.HWND,
    wintypes.COLORREF,
    ctypes.c_ubyte,
    wintypes.DWORD,
)
_user32.SetWindowPos.argtypes = (
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = ctypes.c_short


def format_remaining(seconds):
    """Hours and minutes, short enough to sit in the corner ("2h 58 min"),
    rounded up so anything under a minute still reads as "1 min", not "0 min"."""
    seconds = max(0, seconds)
    total_minutes = math.ceil(seconds / 60)
    hours, minutes = divmod(total_minutes, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    # Skip minutes only for an exact number of hours (e.g. "2h").
    if minutes or not hours:
        parts.append(f"{minutes} min")
    return " ".join(parts)


def color_for(seconds):
    if seconds <= CRITICAL_SECONDS:
        return COLOR_CRITICAL
    if seconds <= WARNING_SECONDS:
        return COLOR_WARNING
    return COLOR_NORMAL


def hotkey_is_down():
    """True while every key of the toggle shortcut is held at once."""
    return all(_user32.GetAsyncKeyState(key) & _KEY_IS_DOWN for key in HOTKEY_KEYS)


class RemainingTimeWidget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", OPACITY)
        self.root.attributes("-topmost", True)
        self.root.attributes("-toolwindow", True)  # no taskbar button, no Alt+Tab entry
        self.root.configure(bg="black")

        self.label = tk.Label(
            self.root,
            text="",
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            fg=COLOR_NORMAL,
            bg="black",
            padx=12,
            pady=6,
        )
        self.label.pack()

        self.hidden = False
        self.hotkey_was_down = False

        self.root.update_idletasks()
        self._apply_click_through()

        self.root.after(HOTKEY_POLL_MS, self.check_hotkey)
        self.root.after(RERAISE_INTERVAL_MS, self.keep_on_top)
        self.update_label()

    def _hwnd(self):
        return _user32.GetAncestor(self.root.winfo_id(), _GA_ROOT)

    def _apply_click_through(self):
        hwnd = self._hwnd()
        style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        _user32.SetWindowLongW(
            hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE
        )
        # A layered window does not render until its alpha is set, and Tk only
        # sets it for an opacity below 1.0.
        _user32.SetLayeredWindowAttributes(hwnd, 0, int(OPACITY * 255), _LWA_ALPHA)

    def _position_in_corner(self):
        # Let Tk lay the new text out first, or the width is the previous one
        # and the box lands partly off the edge of the screen.
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        screen_width = self.root.winfo_screenwidth()
        x = SIDE_MARGIN_PX if CORNER == "left" else screen_width - width - SIDE_MARGIN_PX
        y = TOP_MARGIN_PX
        self.root.geometry(f"+{x}+{y}")

    def keep_on_top(self):
        """Move the box back above any topmost window raised since, without
        taking focus and without showing it while hidden."""
        if not self.hidden:
            _user32.SetWindowPos(
                self._hwnd(), _HWND_TOPMOST, 0, 0, 0, 0, _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE
            )
        self.root.after(RERAISE_INTERVAL_MS, self.keep_on_top)

    def check_hotkey(self):
        """Toggle once per press, rather than on every poll while it is held."""
        down = hotkey_is_down()
        if down and not self.hotkey_was_down:
            self.toggle_visibility()
        self.hotkey_was_down = down
        self.root.after(HOTKEY_POLL_MS, self.check_hotkey)

    def toggle_visibility(self):
        self.hidden = not self.hidden
        if self.hidden:
            self.root.withdraw()
        else:
            self.root.deiconify()
            # Showing the window again can drop everything set on it once, so
            # put the whole lot back.
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self._apply_click_through()
            self._position_in_corner()

    def read_remaining_seconds(self):
        """Seconds left, or None while the monitor isn't publishing them."""
        try:
            age = time.time() - REMAINING_TIME_FILE_PATH.stat().st_mtime
            remaining = int(REMAINING_TIME_FILE_PATH.read_text(encoding="utf-8").strip())
        except Exception:
            return None
        # A reboot can bring granted time or a new day, so an old number may be
        # wrong and not just late; say nothing until the monitor publishes again.
        if age > STALE_AFTER_SECONDS:
            return None
        return remaining

    def update_label(self):
        remaining = self.read_remaining_seconds()
        if remaining is None:
            text = "Time: --"
            color = COLOR_NORMAL
        elif remaining <= 0:
            text = "Time's up"
            color = COLOR_CRITICAL
        else:
            text = format_remaining(remaining)
            color = color_for(remaining)

        self.label.config(text=text, fg=color)
        if not self.hidden:
            self._position_in_corner()
        self.root.after(POLL_INTERVAL_MS, self.update_label)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    RemainingTimeWidget().run()
