"""What the parent changes from the server: the settings' schema, their
validation, and the child's settings file. What is fixed at install -- paths,
intervals, the version -- is in config.py."""
import json
import os
import sys
from pathlib import Path

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # in date.weekday() order
DAILY_LIMIT_RANGE = range(24 * 60 * 60 + 1)

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
    "EARLIEST_HOUR_INCLUDED": {
        "default": 6,
        "allowed": range(24)
    },
    "LATEST_HOUR_INCLUDED": {
        "default": 20,
        "allowed": range(24)
    },
    "DAILY_LIMIT_OVERRIDES": {
        # a weekday named here gets its own limit, e.g. {"mon": 1800}
        "default": {},
        "allowed": {"keys": WEEKDAY_NAMES, "values": DAILY_LIMIT_RANGE},
    },
}


def default_settings() -> dict:
    return {name: setting["default"] for name, setting in SETTINGS.items()}


def is_int_in(value, allowed: range) -> bool:
    # bool is an int subclass: without the exclusion, True would pass as 1
    return isinstance(value, int) and not isinstance(value, bool) and value in allowed


def value_allowed(name: str, value) -> bool:
    if value is None:
        return SETTINGS[name].get("nullable", False)
    allowed = SETTINGS[name]["allowed"]
    if isinstance(allowed, range):
        return is_int_in(value, allowed)
    elif isinstance(allowed, tuple):
        return type(value) is type(allowed[0]) and value in allowed
    elif isinstance(allowed, dict):
        # a dict with keys from "keys" and int values in the "values" range; empty is fine
        return isinstance(value, dict) and all(
            key in allowed["keys"] and is_int_in(item, allowed["values"])
            for key, item in value.items()
        )
    else:
        # an "allowed" spec this function doesn't handle is a bug in SETTINGS;
        # dropping the value keeps the monitor ticking
        return False


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
    settings = {name: stored.get(name, fallback[name]) for name in SETTINGS}
    # an unusable window would shut the machine down before a correction could arrive
    if settings["EARLIEST_HOUR_INCLUDED"] > settings["LATEST_HOUR_INCLUDED"]:
        return dict(fallback)
    return settings


def stored_settings(settings_file: Path) -> dict:
    try:
        stored = json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception:  # whatever the file holds, the monitor's tick must go on
        return {}
    return stored if isinstance(stored, dict) else {}


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
