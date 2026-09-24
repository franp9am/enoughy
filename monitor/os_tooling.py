import ctypes
import subprocess
import time
from ctypes import wintypes
from typing import Optional

WTS_CURRENT_SERVER = None  # the C macro is a null handle, and ctypes passes None as one
WTS_SESSION_INFO_EX = 25  # the info class that carries the lock state
WTS_ACTIVE = 0  # a disconnected session is nobody sitting at the screen
WTS_LOCKED = 0  # the one session flag that means locked; reversed on windows 7
SESSION_GONE = (2, 7022)  # ERROR_FILE_NOT_FOUND, ERROR_CTX_WINSTATION_NOT_FOUND
MESSAGE_BOX_OK = 0
NO_TIMEOUT = 0
WAIT_FOR_CLICK = False
SHUTDOWN_GRACE_SECONDS = 10
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# None off windows, so importing this module never breaks tests of the pure logic
_wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True) if hasattr(ctypes, "WinDLL") else None


class SessionEntry(ctypes.Structure):
    _fields_ = [("id", wintypes.DWORD), ("station", wintypes.LPWSTR), ("state", ctypes.c_int)]


class SessionDetail(ctypes.Structure):
    """The front of WTSINFOEXW. The underscored fields are never read; they are
    declared because ctypes places a field by the size of everything before it."""

    _fields_ = [
        ("_level", wintypes.DWORD),
        ("_alignment", wintypes.DWORD),  # the record below it is 8-byte aligned
        ("_id", wintypes.DWORD),
        ("state", ctypes.c_int),
        ("flags", ctypes.c_long),
        ("_station", ctypes.c_wchar * 33),
        ("user", ctypes.c_wchar * 21),
    ]


def _session_ids() -> list[int]:
    entries, count = ctypes.POINTER(SessionEntry)(), wintypes.DWORD()
    if not _wtsapi32.WTSEnumerateSessionsW(WTS_CURRENT_SERVER, 0, 1,
                                           ctypes.byref(entries), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [entries[i].id for i in range(count.value)]
    finally:
        _wtsapi32.WTSFreeMemory(entries)


def _session_user(session_id: int) -> Optional[tuple]:
    """The user of that session and whether they are at an unlocked screen; the
    name is empty where nobody is logged in. None when the session ended between
    the enumeration and this call, which is ordinary at logoff. Raises when
    windows will not answer, which must never read as a screen nobody is at."""
    detail, size = ctypes.POINTER(SessionDetail)(), wintypes.DWORD()
    if not _wtsapi32.WTSQuerySessionInformationW(WTS_CURRENT_SERVER, session_id,
                                                 WTS_SESSION_INFO_EX,
                                                 ctypes.byref(detail), ctypes.byref(size)):
        error = ctypes.get_last_error()
        if error in SESSION_GONE:
            return None
        raise ctypes.WinError(error)
    try:
        session = detail.contents
        # Only an explicit lock counts as locked. Windows answers
        # WTS_SESSIONSTATE_UNKNOWN (-1) for sessions it holds no state for, and
        # reading that as a locked screen would hand out unlimited time.
        return session.user, session.state == WTS_ACTIVE and session.flags != WTS_LOCKED
    finally:
        _wtsapi32.WTSFreeMemory(detail)


def _sessions() -> dict[int, tuple]:
    """Session id to (user, at screen) for every session somebody is logged in to."""
    if _wtsapi32 is None:
        raise OSError("wtsapi32 exists only on windows")
    sessions = {}
    for session_id in _session_ids():
        answer = _session_user(session_id)
        if answer is not None and answer[0]:
            sessions[session_id] = answer
    return sessions


def users_at_screen() -> dict[int, str]:
    """Session id to user, for everyone logged in with the screen unlocked."""
    return {id_: user for id_, (user, at_screen) in _sessions().items() if at_screen}


def user_logged_in(user: str) -> bool:
    """Whether that user is logged in with the screen unlocked, which is the
    only question the monitor asks. The legacy fallback covers a windows whose
    session API will not answer; it cannot see a locked screen, so it errs
    towards "the child is here" rather than towards unlimited screen time."""
    try:
        return any(name.lower() == user.lower() for name in users_at_screen().values())
    except OSError:
        return legacy_user_logged_in(user)


def notify(message: str, user: str) -> None:
    title = "Screen time"
    clicked_button = wintypes.DWORD()
    try:
        for session_id, name in users_at_screen().items():
            if name.lower() == user.lower():
                _wtsapi32.WTSSendMessageW(WTS_CURRENT_SERVER, session_id,
                                          title, len(title.encode("utf-16-le")),
                                          message, len(message.encode("utf-16-le")),
                                          MESSAGE_BOX_OK, NO_TIMEOUT,
                                          ctypes.byref(clicked_button), WAIT_FOR_CLICK)
    except OSError:
        legacy_notify(message, user)


def shutdown(delay_seconds: int) -> None:
    """Force-closes apps and powers off, blocking until the machine is down; the
    undelayed repeat defeats `shutdown /a`."""
    for delay in (delay_seconds, 0):
        subprocess.run(["shutdown", "/s", "/f", "/t", str(delay)], creationflags=CREATE_NO_WINDOW)
        time.sleep(delay + SHUTDOWN_GRACE_SECONDS)


# --- legacy ---
# What the monitor used before the session API above; neither tool exists on
# windows Home. Only reached when that API will not answer at all.


def legacy_query_users() -> str:
    """May only work on windows Pro"""
    r = subprocess.run(
        ["query", "user"],
        capture_output=True,
        text=True,
        errors="ignore"
    )
    return r.stdout


def legacy_user_has_tasks(user: str) -> bool:
    """Should also work on windows Home"""
    cmd = f'tasklist /V | findstr /I "{user}"'
    r = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        errors="ignore"
    )
    return r.returncode == 0 and bool(r.stdout.strip())


def legacy_user_logged_in(user: str) -> bool:
    try:
        qu = legacy_query_users().lower()
        return user.lower() in qu
    except Exception:  # query user doesnt work or doesnt return a string
        return legacy_user_has_tasks(user)


def legacy_notify(message: str, user: str) -> None:
    """May only work on windows Pro"""
    try:
        subprocess.run(
            ["msg", user, message],
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        # not critical
        pass
