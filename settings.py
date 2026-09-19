"""What the parent changes from the server: the settings' schema, their
validation, and the child's settings file. What is fixed at install -- paths,
intervals, the version -- is in config.py."""
import json
import os
import re
import sys
from pathlib import Path

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # in date.weekday() order
DAILY_LIMIT_RANGE = range(24 * 60 * 60 + 1)


def is_int_in(value, allowed: range) -> bool:
    # bool is an int subclass: without the exclusion, True would pass as 1
    return isinstance(value, int) and not isinstance(value, bool) and value in allowed


def minutes(time_of_day: str) -> int:
    """"20:30" as minutes since midnight; "24:00" is the end of the day."""
    hours, mins = time_of_day.split(":")
    return int(hours) * 60 + int(mins)


def is_time_of_day(value) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"\d{1,2}:[0-5]\d", value) is not None
        and minutes(value) <= 24 * 60
    )


def is_hours_window(value) -> bool:
    """A window is two moments, `[day_starts, night_starts]`: ["6:00", "20:30"]
    allows 6:00 up to 20:30, and at 20:30 sharp the night begins -- the second
    is the shutdown time, not the last allowed one. Both are times of day from
    "0:00" to "24:00", at least an hour apart, since an empty window would shut
    the machine down before a correction could arrive. None is no night at all."""
    return value is None or (
        isinstance(value, list)
        and len(value) == 2
        and all(is_time_of_day(moment) for moment in value)
        and minutes(value[0]) + 60 <= minutes(value[1])
    )


# Read these through settings_in_force(), never directly: the child's settings file
# holds what is in force, and these are only what a child starts with and falls back to.
SETTINGS = {
    "DAILY_LIMIT_SECONDS": {
        "default": 1 * 60 * 60,
        "allowed": DAILY_LIMIT_RANGE
    },
    "CARRYOVER": {
        "default": True,
        "allowed": (True, False)
    },
    "MAX_CARRYOVER_SECONDS": {
        "default": 5 * 60 * 60,
        "allowed": range(sys.maxsize),  # any non-negative int; a day can use at most its limit anyway
        "nullable": True,  # null is no cap; the default stays a number so a report types the field
    },
    "ALLOWED_HOURS": {
        # [day starts, night starts]: usable from 6:00, the night begins at 21:00
        "default": ["6:00", "21:00"],
        "allowed": is_hours_window,
        "nullable": True,  # null is no night
    },
    "DAILY_LIMIT_OVERRIDES": {
        # a weekday named here gets its own limit, e.g. {"mon": 1800}
        "default": {},
        "allowed": {"keys": WEEKDAY_NAMES, "values": DAILY_LIMIT_RANGE},
    },
    "ALLOWED_HOURS_OVERRIDES": {
        # a weekday named here gets its own window, e.g. {"fri": ["6:00", "23:00"]}: Friday's night begins at 23:00,
        # or null: no night that day
        "default": {},
        "allowed": {"keys": WEEKDAY_NAMES, "values": is_hours_window},
    },
}


def default_settings() -> dict:
    return {name: setting["default"] for name, setting in SETTINGS.items()}


def allowed_by(spec, value) -> bool:
    if isinstance(spec, range):
        return is_int_in(value, spec)
    elif isinstance(spec, tuple):
        return type(value) is type(spec[0]) and value in spec
    elif isinstance(spec, dict):
        # a dict with keys from "keys", each value allowed by the "values" spec; empty is fine
        return isinstance(value, dict) and all(
            key in spec["keys"] and allowed_by(spec["values"], item)
            for key, item in value.items()
        )
    elif callable(spec):
        return spec(value)
    else:
        # an "allowed" spec this function doesn't handle is a bug in SETTINGS;
        # dropping the value keeps the monitor ticking
        return False


def value_allowed(name: str, value) -> bool:
    if value is None:
        return SETTINGS[name].get("nullable", False)
    return allowed_by(SETTINGS[name]["allowed"], value)


def validated_settings(stored: dict, fallback=None) -> dict:
    """All of `stored` or none of it: one value this monitor may not take and
    `fallback` is kept whole, never a mix of the two.

    `fallback` is what is already in force, or the defaults when nothing is. It
    also supplies any setting `stored` does not mention, which is how a machine
    upgraded to a monitor with a new setting keeps the ones it already had.
    """
    if fallback is None:
        fallback = default_settings()
    if any(name not in SETTINGS or not value_allowed(name, value)
           for name, value in stored.items()):
        return dict(fallback)
    return {name: stored.get(name, fallback[name]) for name in SETTINGS}


def upgraded(stored: dict) -> dict:
    """A file written before 0.7 has the window as two hours, the last one
    included. Goes once no such machine remains, like the layout move in
    install.ps1; anything else in the old names is left for validation to reject."""
    old = stored.get("EARLIEST_HOUR_INCLUDED"), stored.get("LATEST_HOUR_INCLUDED")
    if all(is_int_in(hour, range(24)) for hour in old):
        stored = {name: value for name, value in stored.items() if not name.endswith("_HOUR_INCLUDED")}
        stored["ALLOWED_HOURS"] = [f"{old[0]}:00", f"{old[1] + 1}:00"]  # the night began when the last included hour ended
    return stored


def stored_settings(settings_file: Path) -> dict:
    try:
        stored = json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception:  # whatever the file holds, the monitor's tick must go on
        return {}
    return upgraded(stored) if isinstance(stored, dict) else {}


def settings_in_force(settings_file: Path) -> dict:
    """The file, with the default for anything it lacks."""
    return validated_settings(stored_settings(settings_file))


def write_settings_file(settings: dict, settings_file: Path) -> None:
    tmp_file = settings_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp_file, settings_file)  # atomic


def save_settings(sent: dict, settings_file: Path) -> dict:
    """Store what the server sent, keeping what is in force wherever it may not."""
    settings = validated_settings(sent, settings_in_force(settings_file))
    write_settings_file(settings, settings_file)
    return settings


def ensure_settings_file(settings_file: Path) -> None:
    """A child that has never had one starts from the defaults above."""
    if not settings_file.is_file():
        write_settings_file(default_settings(), settings_file)
