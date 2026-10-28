"""What the pages show: times, durations and the per-child summaries,
read from the database and put into words. No routes and no FastAPI here
beyond the CSV Response."""
import csv
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.responses import Response

# The page is read by the family, not by whoever happens to host it, so the
# rendered times must not depend on the server process's own timezone.
DISPLAY_TIMEZONE = ZoneInfo("Europe/Prague")


@dataclass
class GrantView:
    minutes: int
    created: str
    granted_by: str


@dataclass
class LastSeenView:
    synced: str
    remaining: str


@dataclass
class SettingsView:
    in_force: str
    waiting_since: str | None  # when a parent asked for something the child has yet to answer
    refused: str | None  # the change the child answered with a refusal, in words


# One widget per setting name, in the page's order: how the value shows as boxes
# and how the form's answer reads back into the value the monitor expects. Each
# widget reads and writes its own boxes only. A name not here is a JSON box
# after the widgets, so a monitor reporting a new setting works on day one. A
# name's meaning never changes; a new meaning is a new name. The widgets
# convert shape, minutes to seconds and clock times to the monitor's strings;
# the ranges stay the monitor's.
WIDGETS = {
    "DAILY_LIMIT_SECONDS": "minutes",
    "ALLOWED_HOURS": "hours",  # two time boxes with "no night" under them
    "MAX_CARRYOVER_SECONDS": "carryover cap",  # a box with "no carryover" and "unlimited" under it; 0 and null
    "DAILY_LIMIT_OVERRIDES": "limit exceptions",  # a minutes box per weekday, blank for none
    "ALLOWED_HOURS_OVERRIDES": "hours exceptions",  # two time boxes and "no night" per weekday, blank for none
}

# in the monitor's order, which is date.weekday(); the words are the page's
WEEKDAYS = (
    ("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"), ("thu", "Thursday"),
    ("fri", "Friday"), ("sat", "Saturday"), ("sun", "Sunday"),
)


def in_minutes(seconds) -> str:
    # a value the box cannot show, such as a string from an older change still
    # in flight, leaves it empty for the parent to fill
    return str(seconds // 60) if isinstance(seconds, int) else ""


def as_clock_time(moment) -> str:
    """"6:00" as the "06:00" a time box takes. The box stops at 23:59, so the
    monitor's "24:00", the end of the day, shows a minute early; anything that
    is not a time of day leaves the box empty."""
    if moment == "24:00":
        return "23:59"
    try:
        hours, mins = moment.split(":")
        return f"{int(hours):02d}:{mins}"
    except (AttributeError, ValueError):
        return ""


def clock_pair(window) -> tuple[str, str]:
    """A window as its two time boxes; no night, or junk, is two empty ones."""
    if isinstance(window, list) and len(window) == 2:
        return as_clock_time(window[0]), as_clock_time(window[1])
    return "", ""


def settings_field(name: str, value) -> dict:
    """What the page shows for one setting: its name, its widget, and the
    widget's boxes."""
    widget = WIDGETS.get(name, "json")
    field = {"name": name, "widget": widget}
    if widget == "minutes":
        field["minutes"] = in_minutes(value)
    elif widget == "hours":
        field["day"], field["night"] = clock_pair(value)
        field["no_night"] = value is None
    elif widget == "carryover cap":
        # the box takes typing only while neither checkbox is on; a ticked one freezes it at 0 or the infinity sign
        field["carryover"] = "off" if value == 0 else "unlimited" if value is None else "capped"
        field["cap"] = "0" if value == 0 else "\u221e" if value is None else in_minutes(value)
    elif widget == "limit exceptions":
        limits = value if isinstance(value, dict) else {}
        field["rows"] = [{"weekday": weekday, "word": word, "minutes": in_minutes(limits.get(weekday))}
                         for weekday, word in WEEKDAYS]
        field["open"] = bool(limits)
    elif widget == "hours exceptions":
        windows = value if isinstance(value, dict) else {}
        field["rows"] = []
        for weekday, word in WEEKDAYS:
            day, night = clock_pair(windows.get(weekday))
            field["rows"].append({"weekday": weekday, "word": word, "day": day, "night": night,
                                  "no_night": weekday in windows and windows[weekday] is None})
        field["open"] = bool(windows)
    else:
        field["json"] = json.dumps(value)
        field["wide"] = isinstance(value, (dict, list))  # a dict or list needs a whole row, not a number-sized box
    return field


def as_monitor_time(clock_time: str) -> str:
    """"06:00" from a time box as the "6:00" the installer writes, so the in-force
    line reads the same whoever set it. ValueError when it is not hours:minutes."""
    hours, mins = clock_time.split(":")
    return f"{int(hours)}:{mins}"


def window_from_boxes(form, day_box: str, night_box: str, no_night_box: str):
    """Two time boxes and a "no night" checkbox as the monitor's window: the
    checkbox or both boxes empty is no night, one box empty is a ValueError.
    Both empty and no checkbox is None too; a caller that tells the two apart
    looks at the checkbox itself."""
    if no_night_box in form:
        return None
    day, night = form[day_box], form[night_box]
    if day == "" and night == "":
        return None
    if day == "" or night == "":
        raise ValueError("one time of two")
    return [as_monitor_time(day), as_monitor_time(night)]


def setting_from_form(name: str, form) -> object:
    """The form's answer for one setting as the value the monitor expects.
    KeyError when the form lacks a box, ValueError when one holds no value."""
    widget = WIDGETS.get(name, "json")
    if widget == "minutes":
        return int(form[name]) * 60
    if widget == "hours":
        return window_from_boxes(form, "day_starts", "night_starts", "no_night")
    if widget == "carryover cap":
        off, unlimited = "no_carryover" in form, "unlimited_carryover" in form
        if off and unlimited:
            raise ValueError("both no carryover and unlimited carryover")
        return 0 if off else None if unlimited else int(form[name]) * 60
    if widget == "limit exceptions":
        minutes = {weekday: form[f"limit_{weekday}"].strip() for weekday, _ in WEEKDAYS}
        return {weekday: int(box) * 60 for weekday, box in minutes.items() if box != ""}
    if widget == "hours exceptions":
        windows = {}
        for weekday, _ in WEEKDAYS:
            window = window_from_boxes(form, f"day_starts_{weekday}", f"night_starts_{weekday}", f"no_night_{weekday}")
            if window is not None or f"no_night_{weekday}" in form:
                windows[weekday] = window
        return windows
    return json.loads(form[name])


@dataclass
class DayUsage:
    weekday: str
    spent: str
    bar_percent: int
    is_today: bool


@dataclass
class WeekUsage:
    days: list[DayUsage]
    total: str


def formatted_local_time(utc_timestamp: str) -> str:
    local = datetime.fromisoformat(utc_timestamp).astimezone(DISPLAY_TIMEZONE)
    return local.strftime("%Y-%m-%d %H:%M")


def duration_in_words(seconds: int) -> str:
    """Negative means the child is past the limit, e.g. after a negative grant."""
    hours, minutes = divmod(abs(seconds) // 60, 60)
    if hours == 0 and minutes == 0:
        return "no time left"
    magnitude = f"{hours} h {minutes} min" if hours else f"{minutes} min"
    return magnitude if seconds > 0 else f"{magnitude} over"


def compact_duration(seconds: int) -> str:
    hours, minutes = divmod(seconds // 60, 60)
    if seconds <= 0:
        return "0"
    if hours == 0:
        return f"{minutes}m"
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h{minutes:02d}"


def percent_of_tallest(seconds: int, tallest: int) -> int:
    """Any use at all gets at least a sliver, so a short day is not an empty column."""
    if seconds == 0:
        return 0
    return max(round(100 * seconds / tallest), 1)


def last_week(connection: sqlite3.Connection, child_id: int) -> WeekUsage:
    """Time spent on each of the last seven days, oldest first; missing days count as zero."""
    today = datetime.now(DISPLAY_TIMEZONE).date()
    days = [today - timedelta(days=offset) for offset in reversed(range(7))]
    rows = connection.execute(
        """SELECT date, time_spent_sec FROM status
           WHERE child_id = :child_id AND date >= :first_day""",
        {"child_id": child_id, "first_day": days[0].isoformat()},
    ).fetchall()
    spent_on = {row["date"]: row["time_spent_sec"] for row in rows}
    seconds_per_day = [max(spent_on.get(day.isoformat(), 0), 0) for day in days]
    # An hour is the shortest scale, so a quiet week doesn't look like a busy one.
    tallest = max(max(seconds_per_day), 3600)
    return WeekUsage(
        days=[
            DayUsage(
                weekday=day.strftime("%a"),
                spent=compact_duration(seconds),
                bar_percent=percent_of_tallest(seconds, tallest),
                is_today=day == today,
            )
            for day, seconds in zip(days, seconds_per_day)
        ],
        total=compact_duration(sum(seconds_per_day)),
    )


def last_seen(connection: sqlite3.Connection, child_id: int) -> LastSeenView | None:
    row = connection.execute(
        """SELECT remaining_sec, updated_at FROM status
           WHERE child_id = :child_id
           ORDER BY date DESC
           LIMIT 1""",
        {"child_id": child_id},
    ).fetchone()
    if row is None:
        return None
    return LastSeenView(
        synced=formatted_local_time(row["updated_at"]),
        remaining=duration_in_words(row["remaining_sec"]),
    )


def pending_grants(connection: sqlite3.Connection, child_id: int) -> list[GrantView]:
    rows = connection.execute(
        """SELECT grants.seconds, grants.created_at, parents.login FROM grants
           JOIN parents ON parents.id = grants.granted_by
           WHERE grants.child_id = :child_id AND grants.acked_at IS NULL
           ORDER BY grants.id DESC""",
        {"child_id": child_id},
    ).fetchall()
    return [
        GrantView(
            minutes=row["seconds"] // 60,
            created=formatted_local_time(row["created_at"]),
            granted_by=row["login"],
        )
        for row in rows
    ]


def wanted_settings(connection: sqlite3.Connection, child_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT id, settings, created_at, outcome FROM settings_changes
           WHERE child_id = :child_id
           ORDER BY id DESC
           LIMIT 1""",
        {"child_id": child_id},
    ).fetchone()


def settings_in_words(settings: dict) -> str:
    """The settings the child reports, on one line."""
    # non-breaking space so a wrap never splits a value from the word it belongs to
    limit = f"{compact_duration(settings['DAILY_LIMIT_SECONDS'])}/d"
    # .get: a monitor older than the setting does not report it. The days are
    # not spelled out here: the settings page shows the dict as the child sent it.
    if settings.get("DAILY_LIMIT_OVERRIDES"):
        limit = f"{limit}\u00a0+overrides"
    if "ALLOWED_HOURS" in settings:
        hours = settings["ALLOWED_HOURS"]  # [day starts, night starts], or null for no night
    else:
        # before 0.7 the window came as two hours, the last one included in
        # full; goes once every machine installed before 0.7 is reinstalled
        hours = (settings["EARLIEST_HOUR_INCLUDED"], settings["LATEST_HOUR_INCLUDED"] + 1)
    window = "no night" if hours is None else f"{hours[0]}-{hours[1]}"
    if settings.get("ALLOWED_HOURS_OVERRIDES"):
        window = f"{window}\u00a0+overrides"
    parts = [limit, window]
    # only what is in effect is named, so carryover that is off says nothing;
    # before 1.3 off was a flag of its own, since then it is a cap of 0
    cap = settings["MAX_CARRYOVER_SECONDS"]
    if settings.get("CARRYOVER", True) and cap != 0:
        parts.append("carryover" if cap is None else f"carryover\u00a0≤{compact_duration(cap)}")
    return ", ".join(parts)


def settings_view(connection: sqlite3.Connection, child_id: int) -> SettingsView | None:
    row = connection.execute(
        """SELECT reported_settings FROM status
           WHERE child_id = :child_id
           ORDER BY date DESC
           LIMIT 1""",
        {"child_id": child_id},
    ).fetchone()
    if row is None:
        return None
    if row["reported_settings"] is None:
        return SettingsView(
            in_force="not reported by this monitor", waiting_since=None, refused=None
        )
    # What is in force is what the child reports, always. The change row says
    # only how the last question was answered -- nothing here infers the child's
    # state from a comparison, so a machine we have not heard from cannot be
    # made to look like one that refused something.
    wanted = wanted_settings(connection, child_id)
    unanswered = wanted is not None and wanted["outcome"] is None
    refused = wanted is not None and wanted["outcome"] == "refused"
    return SettingsView(
        in_force=settings_in_words(json.loads(row["reported_settings"])),
        waiting_since=formatted_local_time(wanted["created_at"]) if unanswered else None,
        refused=settings_as_sent(json.loads(wanted["settings"])) if refused else None,
    )


def settings_as_sent(settings: dict) -> str:
    """A refused change, field by field as the parent typed it. It is whatever
    JSON they sent, so the wording cannot be trusted with it; and a refusal is
    the one time the field names help, since they say what was rejected."""
    return ", ".join(f"{name}={json.dumps(value)}" for name, value in settings.items())


def child_reported_settings(connection: sqlite3.Connection, child_id: int) -> dict | None:
    """What is in force on the child's PC, or None from a machine never heard from."""
    row = connection.execute(
        """SELECT reported_settings FROM status
           WHERE child_id = :child_id
           ORDER BY date DESC
           LIMIT 1""",
        {"child_id": child_id},
    ).fetchone()
    if row is None or row["reported_settings"] is None:
        return None
    return json.loads(row["reported_settings"])


def settings_fields(connection: sqlite3.Connection, child_id: int) -> list[dict] | None:
    """A widget per setting the child reports, the known ones first in the
    page's order -- its report is the whole schema, so a machine never heard
    from gets no form and no invented defaults.

    Prefilled from the change still in flight when there is one, not from the
    child, so a second parent pressing Save does not silently revert the first.
    """
    reported = child_reported_settings(connection, child_id)
    if reported is None:
        return None
    prefill = reported
    wanted = wanted_settings(connection, child_id)
    if wanted is not None and wanted["outcome"] is None:
        prefill = json.loads(wanted["settings"])  # an ask still in transit wins
    shown = {name: prefill.get(name, value) for name, value in reported.items()}
    known = [name for name in WIDGETS if name in shown]
    unknown = [name for name in shown if name not in WIDGETS]
    return [settings_field(name, shown[name]) for name in known + unknown]


def csv_download(filename: str, header: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def export_filename(child_name: str, table: str) -> str:
    """Child names are free text, so keep only what is safe in a header and a filename."""
    return f"{re.sub(r'[^A-Za-z0-9]+', '-', child_name).strip('-') or 'child'}-{table}.csv"
