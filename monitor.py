import datetime
import hashlib
import hmac
import json
import os
import time
import traceback
from pathlib import Path
from typing import Optional

import os_tooling
import remote_sync
from config import (
    CHECK_INTERVAL_SECONDS,
    CRASH_LOG_FILE,
    DATA_DIR,
    MAX_REDEEM_FILE_BYTES,
    NETWORK_WARMUP_SECONDS,
    NIGHT_SHUTDOWN_DELAY_SECONDS,
    NIGHT_WARNING_SECONDS,
    SHARED_DIR,
    SHUTDOWN_DELAY_SECONDS,
    SIGNATURE_CHARS,
    STARTUP_DELAY_SECONDS,
)
from settings import WEEKDAY_NAMES, ensure_settings_file, minutes, save_settings, settings_in_force

DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_secret(secret_file: Path) -> bytes:
    """The key redeem codes are signed with; empty when missing or malformed,
    and with an empty key no code is accepted."""
    try:
        return bytes.fromhex(secret_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return b""


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"  # shared by every stamp written and read
TICK_TIME_FORMAT = "%H:%M:%S"  # ticks live in a per-date file, so no date needed


def get_datafile(now, data_dir: Path) -> Path:
    return data_dir / (now.date().isoformat() + ".json")


def find_previous_datafile(today: datetime.date, data_dir: Path) -> Optional[Path]:
    """Find the most recent data file for a date before today, if any."""
    prev_dates = []
    for p in data_dir.glob("*.json"):
        try:
            d = datetime.date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d < today:
            prev_dates.append(d)
    if not prev_dates:
        return None
    return data_dir / (max(prev_dates).isoformat() + ".json")


def compute_carryover_sec(today: datetime.date, settings, data_dir: Path) -> int:
    """Leftover time from the last day with data, plus its own full limit for
    every calendar day in between that has no data file (machine was off),
    capped at MAX_CARRYOVER_SECONDS unless that is None."""
    prev_file = find_previous_datafile(today, data_dir)
    if prev_file is None:
        return 0
    prev_date = datetime.date.fromisoformat(prev_file.stem)
    prev_data = load_data(prev_file)
    leftover = max(0, remaining_seconds(prev_data, settings, prev_date))
    missing_days = (today - prev_date).days - 1  # fully skipped days, no file
    carryover = leftover + sum(
        daily_limit_seconds(prev_date + datetime.timedelta(days=offset), settings)
        for offset in range(1, missing_days + 1)
    )
    cap = settings["MAX_CARRYOVER_SECONDS"]
    return carryover if cap is None else min(carryover, cap)


def allowed_hours(date: datetime.date, settings):
    """The day's own `[day starts, night starts]` when its weekday has one, else
    the general one; None is no night."""
    weekday = WEEKDAY_NAMES[date.weekday()]
    return settings["ALLOWED_HOURS_OVERRIDES"].get(weekday, settings["ALLOWED_HOURS"])


def is_night_time(now, settings):
    window = allowed_hours(now.date(), settings)
    if window is None:
        return False
    day_starts, night_starts = window
    # ["6:00", "20:30"]: 20:29 is still day, 20:30 is night
    return not minutes(day_starts) <= now.hour * 60 + now.minute < minutes(night_starts)


def load_data(datafile):
    # A file that parses but is missing keys (or isn't a dict at all) must not
    # crash the loop, so defaults fill in whatever is absent.
    data = {
        "time_spent_sec": 0,
        "ticks": [],
        "last_tick": None,
        "carryover_sec": 0,
        "granted_sec": 0,
        "event_log": [],
    }
    try:
        with open(datafile, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        pass
    return data


def save_data(data, datafile):
    tmp_file = datafile.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_file, datafile)  # atomic, prevents random breakage


def load_used_codes(used_codes_file: Path) -> set:
    """Codes are not tied to a date, so used ones are tracked across days:
    one code per line, and a line cut short by a crash matches no code."""
    try:
        return set(used_codes_file.read_text(encoding="utf-8").split())
    except OSError:
        return set()


def record_used_code(code: str, used_codes_file: Path):
    with open(used_codes_file, "a", encoding="utf-8") as f:
        f.write(code + "\n")


def redeem_unused_code(redeem_file: Path, secret: bytes, used_codes_file: Path) -> int:
    """Seconds granted by the code in the redeem file: zero unless the code is
    valid and has never been used, in which case it is entered in the ledger
    before its seconds are handed out."""
    redeem = handle_redeem_file(redeem_file, secret)
    if redeem["status"] != "valid":
        return 0
    if redeem["redeem_code"] in load_used_codes(used_codes_file):
        return 0
    record_used_code(redeem["redeem_code"], used_codes_file)
    return redeem["extra_time_sec"]


def daily_limit_seconds(date: datetime.date, settings) -> int:
    """The day's own limit when its weekday has one, else the general one."""
    weekday = WEEKDAY_NAMES[date.weekday()]
    return settings["DAILY_LIMIT_OVERRIDES"].get(weekday, settings["DAILY_LIMIT_SECONDS"])


def remaining_seconds(data, settings, date: datetime.date):
    """`date` is the day `data` belongs to; the limit may differ per weekday."""
    return (
        daily_limit_seconds(date, settings)
        + data["carryover_sec"]
        + data["granted_sec"]
        - data["time_spent_sec"]
    )


def write_remaining_time_file(remaining_sec, target: Path):
    """Publish remaining seconds to a child-readable file for a UI to display."""
    tmp_file = target.with_suffix(".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(str(max(0, remaining_sec)))
        os.replace(tmp_file, target)
    except Exception:
        pass  # not critical


def log_unexpected_error():
    """Append the current traceback to the crash log; never raise itself."""
    try:
        now_str = datetime.datetime.now().strftime(TIMESTAMP_FORMAT)
        with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"--- {now_str} ---\n{traceback.format_exc()}\n")
    except Exception:
        pass


def load_children(data_dir: Path) -> list:
    """The children's accounts: every directory install.ps1 made under data;
    there is no default."""
    children = sorted(p.name for p in data_dir.iterdir() if p.is_dir()) if data_dir.is_dir() else []
    if not children:
        raise ValueError(f"No child directory in {data_dir}; run install.ps1 to set one up")
    return children


def verify(msg: bytes, sig_hex: str, secret: bytes) -> bool:
    expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()[:SIGNATURE_CHARS]
    return expected == sig_hex


def handle_redeem_file(redeem_file: Path, secret: bytes):
    """Checks the redeem code from file and adds the time to the data file"""
    if not len(secret):  # if secret is not loaded, program should not break
        return {
            "status": "cannot load secret",
            "redeem_code": None,
            "extra_time_sec": 0,
        }

    if not redeem_file.is_file():
        try:
            redeem_file.parent.mkdir(parents=True, exist_ok=True)
            redeem_file.touch()
        except Exception:
            pass
        return {
            "status": "no_file",
            "redeem_code": None,
            "extra_time_sec": 0,
        }
    # prevent an attack with loading large files
    if os.path.getsize(redeem_file) > MAX_REDEEM_FILE_BYTES:
        return {
            "status": "file too large",
            "redeem_code": None,
            "extra_time_sec": 0,
        }
    try:
        with open(redeem_file) as f:
            redeem_content = f.read().strip()
    except Exception:
        return {
            "status": "cannot read file",
            "redeem_code": None,
            "extra_time_sec": 0,
        }

    if not redeem_content:
        return {
            "status": "empty file",
            "redeem_code": None,
            "extra_time_sec": 0,
        }

    if not isinstance(redeem_content, str):
        return {
            "status": "cannot read file",
            "redeem_code": None,
            "extra_time_sec": 0,
        }

    parts = redeem_content.split(":")
    # we expect three parts in the format: date:extra_time:signature
    if not len(parts) == 3:
        return {
            "status": "invalid format",
            "redeem_code": redeem_content,
            "extra_time_sec": 0,
        }

    req_date = parts[0]
    try:
        req_extra_time = int(parts[1])  # trying to convert to integer
    except Exception:
        return {
            "status": "invalid format",
            "redeem_code": redeem_content,
            "extra_time_sec": 0,
        }

    req_sig = parts[2]
    # The date is a signed nonce that keeps otherwise-identical codes distinct;
    # it is not checked against the calendar, so a code has no expiry date.
    extracted_payload = f"{req_date}:{req_extra_time}".encode()

    if not verify(extracted_payload, req_sig, secret):
        return {
            "status": "invalid signature",
            "redeem_code": redeem_content,
            "extra_time_sec": 0,
        }

    # Normalize the code so variants like "0600", "+600" or " 600" (all
    # accepted by int()) count as the same code in the used-codes ledger.
    normalized_code = f"{req_date}:{req_extra_time}:{req_sig}"

    return {
        "status": "valid",
        "redeem_code": normalized_code,
        "extra_time_sec": req_extra_time,
    }


def sync_with_server(data, datafile, now, settings, child: str) -> dict:
    """Report today's totals to the parent's server, apply the grants it sends
    back and adopt any settings it sends with them. A server that is down, slow
    or unreachable simply leaves the local numbers and settings untouched.

    Returns the settings to carry on with, which are the ones passed in unless
    the server changed them."""
    data_dir = DATA_DIR / child
    server_url = remote_sync.load_server_url(data_dir / "server_url.txt")
    token = remote_sync.load_child_token(data_dir / "child_token.txt")
    if not server_url or not token:
        return settings
    applied_grants_file = data_dir / "applied_grants.json"
    outcome_file = data_dir / "settings_change_outcome.json"  # of the last change delivered

    now_str = now.strftime(TIMESTAMP_FORMAT)
    status = remote_sync.DailyStatus(
        date=now.date().isoformat(),
        time_spent_sec=data["time_spent_sec"],
        carryover_sec=data["carryover_sec"],
        granted_sec=data["granted_sec"],
        remaining_sec=remaining_seconds(data, settings, now.date()),
        last_tick=data["last_tick"],
        settings=settings,
        settings_change_outcome=remote_sync.load_settings_change_outcome(outcome_file),
    )
    applied_grant_ids = remote_sync.load_applied_grant_ids(applied_grants_file)
    try:
        answer = remote_sync.send_status(status, applied_grant_ids, server_url, token)
    except Exception:
        return settings  # offline is the normal case, not a crash

    # The server keeps sending a grant until it hears the id back, so applying
    # first and recording afterwards can repeat a grant, never lose one.
    for grant in answer.pending_grants:
        data["granted_sec"] += grant.seconds
        data["event_log"].append(f"server grant {grant.seconds} sec id {grant.id} {now_str}")
        os_tooling.notify(f"extra time {grant.seconds}", child)
    change = answer.settings_change
    if change is not None:
        in_force = save_settings(change.settings, data_dir / "settings.json")
        taken = all(in_force.get(name) == value for name, value in change.settings.items())
        verdict = "taken" if taken else "refused"
        data["event_log"].append(f"server settings {verdict} {change.settings} {now_str}")
        remote_sync.save_settings_change_outcome(change.id, taken, outcome_file)
        settings = in_force
    if answer.pending_grants or change is not None:
        save_data(data, datafile)
    if answer.pending_grants or applied_grant_ids:
        remote_sync.save_applied_grant_ids(
            [grant.id for grant in answer.pending_grants], applied_grants_file
        )
    return settings


def ensure_datafile(datafile, now, settings):
    """Create today's datafile if it doesn't exist yet, applying carryover if
    configured; otherwise just load what's already there."""
    if datafile.is_file():
        return load_data(datafile)
    data = load_data(datafile)  # defaults, since the file doesn't exist
    if settings["CARRYOVER"]:
        carryover = compute_carryover_sec(now.date(), settings, datafile.parent)
        if carryover > 0:
            data["carryover_sec"] = carryover
            now_str = now.strftime(TIMESTAMP_FORMAT)
            data["event_log"].append(f"carryover {carryover} sec from previous day {now_str}")
    save_data(data, datafile)
    return data


def seconds_to_charge(data, now):
    """Real seconds since the last tick when that gap looks like an ordinary
    tick, otherwise the nominal interval. A tick is one sleep plus its own
    overhead, so anything longer means the machine slept, rebooted or skipped
    ticks -- and anything shorter means the clock moved backwards (DST); none
    of that is time the child spent at the screen."""
    try:
        previous = datetime.datetime.strptime(data["last_tick"], TIMESTAMP_FORMAT)
    except (KeyError, TypeError, ValueError):
        return CHECK_INTERVAL_SECONDS  # no previous tick today
    elapsed = int((now - previous).total_seconds())
    if CHECK_INTERVAL_SECONDS <= elapsed <= 2 * CHECK_INTERVAL_SECONDS:
        return elapsed
    return CHECK_INTERVAL_SECONDS


def startup(now, child: str):
    """Before the first tick: the settings file if the child never had one,
    today's data with any carryover, a first sync so that a grant made while
    the machine was off counts from the first tick, and a first number for
    the widget."""
    settings_file = DATA_DIR / child / "settings.json"
    ensure_settings_file(settings_file)
    datafile = get_datafile(now, DATA_DIR / child)
    settings = settings_in_force(settings_file)
    data = ensure_datafile(datafile, now, settings)
    if os_tooling.user_logged_in(child):
        settings = sync_with_server(data, datafile, now, settings, child)
    write_remaining_time_file(
        remaining_seconds(data, settings, now.date()), SHARED_DIR / child / "remaining_time.txt"
    )


def shut_down(reason, delay_seconds, data, datafile, now, settings, child: str):
    """Tell the child, record why, get the last word to the server, and only
    then order the shutdown."""
    write_remaining_time_file(0, SHARED_DIR / child / "remaining_time.txt")
    os_tooling.notify(reason, child)
    data["event_log"].append(f"{reason} {now.strftime(TIMESTAMP_FORMAT)}")
    save_data(data, datafile)
    # without this the page keeps stale numbers, and a grant that caused this
    # shutdown stays pending until the next boot
    sync_with_server(data, datafile, now, settings, child)
    # last, because it blocks until the machine goes down; a failure above
    # only costs this tick, the next one retries
    os_tooling.shutdown(delay_seconds)


def tick(now, child: str, secret: bytes):
    """One check of one child: charge the time since the last one, or shut the
    machine down when the time is up or the allowed hours are over."""
    now_str = now.strftime(TIMESTAMP_FORMAT)
    data_dir, shared_dir = DATA_DIR / child, SHARED_DIR / child
    remaining_time_file = shared_dir / "remaining_time.txt"  # read by the widget
    datafile = get_datafile(now, data_dir)
    settings = settings_in_force(data_dir / "settings.json")
    data = ensure_datafile(datafile, now, settings)

    if not os_tooling.user_logged_in(child):
        # Nothing is being spent, but keep publishing: the widget treats a
        # file that stops being refreshed as "the monitor is gone".
        write_remaining_time_file(remaining_seconds(data, settings, now.date()), remaining_time_file)
        return

    if is_night_time(now, settings):
        shut_down(
            reason="Night time",
            delay_seconds=NIGHT_SHUTDOWN_DELAY_SECONDS,
            data=data,
            datafile=datafile,
            now=now,
            settings=settings,
            child=child,
        )
        return

    extra_time = redeem_unused_code(
        shared_dir / "extra_time.txt", secret, data_dir / "used_redeem_codes.txt"
    )
    if extra_time:
        data["event_log"].append(f"redeem code {extra_time} {now_str}")
        data["granted_sec"] += extra_time
        os_tooling.notify(f"extra time {extra_time}", child)
        save_data(data, datafile)

    settings = sync_with_server(data, datafile, now, settings, child)

    if remaining_seconds(data, settings, now.date()) <= 0:
        shut_down(
            reason="time up",
            delay_seconds=SHUTDOWN_DELAY_SECONDS,
            data=data,
            datafile=datafile,
            now=now,
            settings=settings,
            child=child,
        )
        return

    soon = now + datetime.timedelta(seconds=NIGHT_WARNING_SECONDS)
    warning = f"{NIGHT_WARNING_SECONDS // 60} minutes to night"
    if is_night_time(soon, settings) and not any(e.startswith(warning) for e in data["event_log"]):
        os_tooling.notify(warning, child)
        data["event_log"].append(f"{warning} {now_str}")  # once a day: the log remembers

    data["time_spent_sec"] += seconds_to_charge(data, now)
    data["ticks"].append(now.strftime(TICK_TIME_FORMAT))
    data["last_tick"] = now_str
    save_data(data, datafile)
    write_remaining_time_file(remaining_seconds(data, settings, now.date()), remaining_time_file)


def main():
    """One loop for the machine, each child in turn. The installer sets up one
    child today, but nothing here assumes there is only one."""
    try:
        children = load_children(DATA_DIR)
    except Exception:
        log_unexpected_error()  # a failure this early leaves no other trace
        raise
    secrets = {child: load_secret(DATA_DIR / child / "secret.txt") for child in children}

    time.sleep(NETWORK_WARMUP_SECONDS)  # let the network come up before syncing
    for child in children:
        try:
            startup(datetime.datetime.now(), child)
        except Exception:
            log_unexpected_error()
    # the rest of the delay, waiting for the redeem file to be created
    time.sleep(max(0, STARTUP_DELAY_SECONDS - NETWORK_WARMUP_SECONDS))

    while True:
        # A transient failure (locked file, redeem file vanishing mid-check,
        # odd data on disk) must not kill the monitor: log it, skip this tick
        # and try again, instead of leaving the machine unrestricted.
        for child in children:
            try:
                tick(datetime.datetime.now(), child, secrets[child])
            except Exception:
                log_unexpected_error()
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
