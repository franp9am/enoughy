import csv
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import db

# The page is read by the family, not by whoever happens to host it, so the
# rendered times must not depend on the server process's own timezone.
DISPLAY_TIMEZONE = ZoneInfo("Europe/Prague")

# The account that exists only to be the wrong password, in nginx's htpasswd for
# /logout and nowhere else. No parent may use this login.
LOGOUT_LOGIN = "logout"


class SettingsChangeOutcome(BaseModel):
    id: int  # of the settings change
    taken: bool


class SyncRequest(BaseModel):
    date: str
    time_spent_sec: int
    carryover_sec: int
    granted_sec: int
    remaining_sec: int
    last_tick: str | None
    applied_grant_ids: list[int]
    # the settings in force on the child; None from a client too old to say
    settings: dict | None = None
    # of the last change delivered to the child; None before any
    settings_change_outcome: SettingsChangeOutcome | None = None


class PendingGrant(BaseModel):
    id: int
    seconds: int


class SettingsChange(BaseModel):
    id: int
    settings: dict


class SyncResponse(BaseModel):
    pending_grants: list[PendingGrant]
    settings_change: SettingsChange | None = None


@dataclass
class Parent:
    id: int
    login: str
    family_id: int


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


@dataclass
class SettingsField:
    name: str  # the monitor's own name for the setting, raw
    value: str  # as JSON, so 3600 comes back an int and true a bool
    wide: bool  # a dict or list needs a whole row, not a number-sized box


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
    # only what is in effect is named, so carryover that is off says nothing
    cap = settings["MAX_CARRYOVER_SECONDS"]
    if settings["CARRYOVER"]:
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


def settings_fields(connection: sqlite3.Connection, child_id: int) -> list[SettingsField] | None:
    """One input per setting the child reports -- its report is the whole schema,
    so a machine never heard from gets no form and no invented defaults.

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
    fields = []
    for name, value in reported.items():
        shown = prefill.get(name, value)
        fields.append(
            SettingsField(
                name=name, value=json.dumps(shown), wide=isinstance(shown, (dict, list))
            )
        )
    return fields


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


def children_in_family(connection: sqlite3.Connection, family_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT id, name FROM children WHERE family_id = :family_id ORDER BY id",
        {"family_id": family_id},
    ).fetchall()


def require_child_in_family(
    connection: sqlite3.Connection, child_id: int, family_id: int
) -> sqlite3.Row:
    """A child belonging to another family is indistinguishable from one that does not exist."""
    child = connection.execute(
        "SELECT id, name FROM children WHERE id = :child_id AND family_id = :family_id",
        {"child_id": child_id, "family_id": family_id},
    ).fetchone()
    if child is None:
        raise HTTPException(status_code=404, detail="unknown child")
    return child


db.create_schema()

app = FastAPI()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def current_parent(request: Request) -> Parent:
    """The only place that knows how a person proves who they are.

    nginx does the authenticating and passes the name it verified; swapping it
    for a session cookie or an identity provider means rewriting this function
    and nothing else. The app must therefore never be reachable except through
    the proxy, which overwrites the header on every request.
    """
    login = request.headers.get("x-remote-user", "")
    if not login:
        raise HTTPException(status_code=403, detail="request did not come through the proxy")
    connection = db.connect()
    parent = connection.execute(
        "SELECT id, login, family_id FROM parents WHERE login = :login", {"login": login}
    ).fetchone()
    connection.close()
    if parent is None:
        raise HTTPException(status_code=403, detail=f"no parent for {login}")
    return Parent(id=parent["id"], login=parent["login"], family_id=parent["family_id"])


def authenticated_child_id(authorization: str) -> int:
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    connection = db.connect()
    child = connection.execute(
        "SELECT id FROM children WHERE token = :token", {"token": token}
    ).fetchone()
    connection.close()
    if child is None:
        raise HTTPException(status_code=401, detail="unknown token")
    return child["id"]


@app.post("/api/sync")
def sync(http_request: Request, sync_request: SyncRequest) -> SyncResponse:
    child_id = authenticated_child_id(http_request.headers.get("authorization", ""))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reported_settings = sync_request.settings
    connection = db.connect()
    with connection:
        connection.execute(
            """INSERT INTO status (child_id, date, time_spent_sec, carryover_sec,
                                   granted_sec, remaining_sec, last_tick, updated_at,
                                   reported_settings)
               VALUES (:child_id, :date, :time_spent_sec, :carryover_sec,
                       :granted_sec, :remaining_sec, :last_tick, :updated_at,
                       :reported_settings)
               ON CONFLICT (child_id, date) DO UPDATE SET
                   time_spent_sec = :time_spent_sec,
                   carryover_sec = :carryover_sec,
                   granted_sec = :granted_sec,
                   remaining_sec = :remaining_sec,
                   last_tick = :last_tick,
                   updated_at = :updated_at,
                   reported_settings = :reported_settings""",
            {
                "child_id": child_id,
                "date": sync_request.date,
                "time_spent_sec": sync_request.time_spent_sec,
                "carryover_sec": sync_request.carryover_sec,
                "granted_sec": sync_request.granted_sec,
                "remaining_sec": sync_request.remaining_sec,
                "last_tick": sync_request.last_tick,
                "updated_at": now,
                # NULL, not "null": a client too old to report settings must not
                # look like one reporting nothing in particular
                "reported_settings": (
                    None if reported_settings is None else json.dumps(reported_settings)
                ),
            },
        )
        connection.executemany(
            """UPDATE grants SET acked_at = :now
               WHERE id = :grant_id AND child_id = :child_id AND acked_at IS NULL""",
            [
                {"now": now, "grant_id": grant_id, "child_id": child_id}
                for grant_id in sync_request.applied_grant_ids
            ],
        )
        pending = connection.execute(
            """SELECT id, seconds FROM grants
               WHERE child_id = :child_id AND acked_at IS NULL
               ORDER BY id""",
            {"child_id": child_id},
        ).fetchall()
        change_to_send = None
        wanted = wanted_settings(connection, child_id)
        if wanted is not None and wanted["outcome"] is None:
            outcome = sync_request.settings_change_outcome
            if outcome is not None and outcome.id == wanted["id"]:
                connection.execute(
                    """UPDATE settings_changes SET outcome = :outcome
                       WHERE id = :change_id""",
                    {"outcome": "taken" if outcome.taken else "refused", "change_id": wanted["id"]},
                )
            else:
                change_to_send = SettingsChange(
                    id=wanted["id"], settings=json.loads(wanted["settings"])
                )
    connection.close()
    return SyncResponse(
        pending_grants=[PendingGrant(id=row["id"], seconds=row["seconds"]) for row in pending],
        settings_change=change_to_send,
    )


@app.get("/health")
def health() -> dict[str, str]:
    connection = db.connect()
    connection.execute("SELECT count(*) FROM children").fetchone()
    connection.close()
    return {"status": "ok"}


@app.get("/")
def index(request: Request, child_id: int | None = None) -> HTMLResponse:
    parent = current_parent(request)
    connection = db.connect()
    children = children_in_family(connection, parent.family_id)
    selected_child = next(
        (child for child in children if child["id"] == child_id),
        children[0] if children else None,
    )
    if selected_child is None:
        waiting, status, week, settings = [], None, None, None
    else:
        waiting = pending_grants(connection, selected_child["id"])
        status = last_seen(connection, selected_child["id"])
        week = last_week(connection, selected_child["id"])
        settings = settings_view(connection, selected_child["id"])
    connection.close()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "parent": parent,
            "children": children,
            "selected_child": selected_child,
            "pending_grants": waiting,
            "last_seen": status,
            "settings": settings,
            "week": week,
            "logout_login": LOGOUT_LOGIN,
        },
    )


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    """Signs the parent out by handing the browser a useless password.

    The logout/logout account is real on the /logout endpoint:
    nginx checks this one path against an htpasswd file of its own that holds
    nothing else, so the login here succeeds.

    A browser keeps only one password per site, so it drops the
    parent's real one and keeps the junk one. We then send it back to /,
    where the junk password is refused and the login box opens.

    The check below is there because nginx has to be the one asking for the
    password. If it stops guarding this path, the browser is never asked, so
    nothing replaces the real password and the parent stays logged in.

    The redirect has to name the address in full. The parent gets here from
    https://logout:logout@<host>/logout, and a bare "/" would tell the browser
    to reuse everything in front of it -- logout:logout included. It would
    arrive back at / still carrying the junk password, and a password in the
    address always wins over one typed into the login box.

    TODO: replace all of this with a session cookie and a login form, where
    signing out simply deletes the cookie.
    """
    login = request.headers.get("x-remote-user", "")
    if login != LOGOUT_LOGIN:
        raise HTTPException(status_code=403, detail="/logout was not password-protected")
    host = request.headers.get("host", "")
    return RedirectResponse(f"https://{host}/", status_code=302)


@app.post("/grants")
async def create_grant(request: Request) -> RedirectResponse:
    parent = current_parent(request)
    form = await request.form()
    try:
        child_id = int(form["child_id"])
        seconds = int(form["minutes"]) * 60
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="child_id and minutes must be whole numbers")
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = db.connect()
    try:
        require_child_in_family(connection, child_id, parent.family_id)
        with connection:
            connection.execute(
                """INSERT INTO grants (child_id, granted_by, seconds, created_at)
                   VALUES (:child_id, :granted_by, :seconds, :created_at)""",
                {
                    "child_id": child_id,
                    "granted_by": parent.id,
                    "seconds": seconds,
                    "created_at": created_at,
                },
            )
    finally:
        connection.close()
    target = request.url_for("index").include_query_params(child_id=child_id)
    return RedirectResponse(str(target), status_code=303)


@app.get("/settings")
def settings_page(request: Request, child_id: int) -> HTMLResponse:
    parent = current_parent(request)
    connection = db.connect()
    try:
        child = require_child_in_family(connection, child_id, parent.family_id)
        view = settings_view(connection, child_id)
        fields = settings_fields(connection, child_id)
    finally:
        connection.close()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "parent": parent,
            "child": child,
            "settings": view,
            "fields": fields,
            "logout_login": LOGOUT_LOGIN,
        },
    )


@app.post("/settings")
async def change_settings(request: Request) -> RedirectResponse:
    parent = current_parent(request)
    form = await request.form()
    try:
        child_id = int(form["child_id"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="child_id must be a whole number")
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = db.connect()
    try:
        require_child_in_family(connection, child_id, parent.family_id)
        # the child's report names the settings; the form must answer all of
        # them, since a change is every setting the parent wants, never a subset
        reported = child_reported_settings(connection, child_id)
        if reported is None:
            raise HTTPException(status_code=409, detail="this monitor has never reported settings")
        try:
            new_settings = {name: json.loads(form[name]) for name in reported}
        except (KeyError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="every setting needs a JSON value, like 3600 or true",
            )
        # Any JSON value goes through: the monitor's ranges and types are its
        # own, and the server talks to monitors of several versions at once, so
        # it holds no opinion of its own. A value the monitor will not take
        # comes back refused, and is shown as sent.
        with connection:
            connection.execute(
                """INSERT INTO settings_changes (child_id, changed_by, settings, created_at)
                   VALUES (:child_id, :changed_by, :settings, :created_at)""",
                {
                    "child_id": child_id,
                    "changed_by": parent.id,
                    "settings": json.dumps(new_settings),
                    "created_at": created_at,
                },
            )
    finally:
        connection.close()
    target = request.url_for("settings_page").include_query_params(child_id=child_id)
    return RedirectResponse(str(target), status_code=303)


@app.get("/export/grants")
def export_grants(request: Request, child_id: int) -> Response:
    parent = current_parent(request)
    connection = db.connect()
    try:
        child_name = require_child_in_family(connection, child_id, parent.family_id)["name"]
        rows = connection.execute(
            """SELECT grants.id, grants.seconds, grants.created_at, grants.acked_at, parents.login
               FROM grants
               JOIN parents ON parents.id = grants.granted_by
               WHERE grants.child_id = :child_id
               ORDER BY grants.id""",
            {"child_id": child_id},
        ).fetchall()
    finally:
        connection.close()
    zone = DISPLAY_TIMEZONE.key
    return csv_download(
        filename=export_filename(child_name, "grants"),
        header=["id", "minutes", "granted by", f"created ({zone})", f"applied ({zone})"],
        rows=[
            [
                row["id"],
                row["seconds"] // 60,
                row["login"],
                formatted_local_time(row["created_at"]),
                formatted_local_time(row["acked_at"]) if row["acked_at"] else "",
            ]
            for row in rows
        ],
    )


@app.get("/export/screen-time")
def export_screen_time(request: Request, child_id: int) -> Response:
    parent = current_parent(request)
    connection = db.connect()
    try:
        child_name = require_child_in_family(connection, child_id, parent.family_id)["name"]
        rows = connection.execute(
            """SELECT date, time_spent_sec, carryover_sec, granted_sec, remaining_sec,
                      last_tick, updated_at
               FROM status
               WHERE child_id = :child_id
               ORDER BY date""",
            {"child_id": child_id},
        ).fetchall()
    finally:
        connection.close()
    zone = DISPLAY_TIMEZONE.key
    return csv_download(
        filename=export_filename(child_name, "screen-time"),
        header=[
            "date",
            "time_spent_sec",
            "carryover_sec",
            "granted_sec",
            "remaining_sec",
            "last_tick (device clock)",
            f"synced ({zone})",
        ],
        rows=[
            [
                row["date"],
                row["time_spent_sec"],
                row["carryover_sec"],
                row["granted_sec"],
                row["remaining_sec"],
                row["last_tick"] or "",
                formatted_local_time(row["updated_at"]),
            ]
            for row in rows
        ],
    )
