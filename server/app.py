import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import add_child
import add_parent
import db
from auth import (
    NotLoggedIn, Parent, authenticated_child_id, current_parent, end_session, local_path,
    parent_from_credentials, start_session,
)
from children import (
    SETUP_CODE_LIFETIME, children_in_family, children_with_codes, extra_time_code,
    make_setup_code, require_child_in_family, synced_children,
)
from views import (
    DISPLAY_TIMEZONE, child_reported_settings, csv_download, export_filename,
    formatted_local_time, last_seen, last_week, pending_grants, settings_fields,
    settings_view, wanted_settings,
)

# What enoughy.com/install sends the browser to: the exe of the newest release,
# which release.ps1 uploads under this name. The page tells the parent the
# address, since it is typed on the child's computer, not clicked.
INSTALLER_URL = "https://github.com/franp9am/enoughy/releases/latest/download/enoughy-setup.exe"

# The offline code page, the one file in parent/; the same repo checkout serves it.
EXTRA_TIME_PAGE = Path(__file__).parent.parent / "parent" / "extra_time.html"


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
    monitor_version: str | None = None


class SetupRequest(BaseModel):
    code: str


class SetupResponse(BaseModel):
    token: str
    secret: str


class PendingGrant(BaseModel):
    id: int
    seconds: int


class SettingsChange(BaseModel):
    id: int
    settings: dict


class SyncResponse(BaseModel):
    pending_grants: list[PendingGrant]
    settings_change: SettingsChange | None = None





db.create_schema()

app = FastAPI()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(NotLoggedIn)
def send_to_login(request: Request, error: NotLoggedIn) -> RedirectResponse:
    """To the login page, which brings the browser back here once logged in."""
    if request.method != "GET":
        return RedirectResponse("/login", status_code=303)
    next_path = request.url.path
    if request.url.query:
        next_path += "?" + request.url.query
    return RedirectResponse("/login?" + urlencode({"next": next_path}), status_code=303)


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
                                   reported_settings, monitor_version)
               VALUES (:child_id, :date, :time_spent_sec, :carryover_sec,
                       :granted_sec, :remaining_sec, :last_tick, :updated_at,
                       :reported_settings, :monitor_version)
               ON CONFLICT (child_id, date) DO UPDATE SET
                   time_spent_sec = :time_spent_sec,
                   carryover_sec = :carryover_sec,
                   granted_sec = :granted_sec,
                   remaining_sec = :remaining_sec,
                   last_tick = :last_tick,
                   updated_at = :updated_at,
                   reported_settings = :reported_settings,
                   monitor_version = :monitor_version""",
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
                "monitor_version": sync_request.monitor_version,
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


@app.post("/api/setup")
def setup(request: SetupRequest) -> SetupResponse:
    """The installer trades the setup code for the child's token and secret.
    The code is gone with the trade, so it works once; one past its lifetime
    is as unknown as a wrong one. A child from before secrets gets one here,
    since the installer is about to write what the server says. The code is
    the only credential, and what keeps it from being guessed is the rate
    limit in front of the server."""
    lifetime_ago = (datetime.now(timezone.utc) - SETUP_CODE_LIFETIME).isoformat(timespec="seconds")
    connection = db.connect()
    with connection:
        child = connection.execute(
            """SELECT children.id, token, secret FROM setup_codes
               JOIN children ON children.id = child_id
               WHERE code = :code AND created_at > :lifetime_ago""",
            {"code": request.code.strip(), "lifetime_ago": lifetime_ago},
        ).fetchone()
        if child is not None:
            secret = child["secret"] or secrets.token_hex(16)
            connection.execute(
                "UPDATE children SET secret = :secret WHERE id = :child_id",
                {"secret": secret, "child_id": child["id"]},
            )
            connection.execute(
                "DELETE FROM setup_codes WHERE child_id = :child_id", {"child_id": child["id"]}
            )
    connection.close()
    if child is None:
        raise HTTPException(status_code=401, detail="unknown or expired code")
    return SetupResponse(token=child["token"], secret=secret)


@app.get("/install")
def install() -> RedirectResponse:
    """The address a parent types on the child's computer; follows every release."""
    return RedirectResponse(INSTALLER_URL, status_code=302)


@app.get("/extra-time-codes")
def extra_time_codes() -> FileResponse:
    """The offline code page, no login: it signs in the browser with a key the parent types."""
    return FileResponse(EXTRA_TIME_PAGE)


@app.get("/health")
def health() -> dict[str, str]:
    connection = db.connect()
    connection.execute("SELECT count(*) FROM children").fetchone()
    connection.close()
    return {"status": "ok"}


def parent_if_logged_in(request: Request) -> Parent | None:
    """For the pages a stranger may read too: the parent, or None."""
    try:
        return current_parent(request)
    except NotLoggedIn:
        return None


@app.get("/")
def index(request: Request, child_id: int | None = None) -> Response:
    """The dashboard for a parent; anyone else is sent to what enoughy is."""
    parent = parent_if_logged_in(request)
    if parent is None:
        return RedirectResponse("/intro", status_code=303)
    connection = db.connect()
    children = synced_children(connection, parent.family_id)
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
        },
    )


@app.get("/intro")
def intro(request: Request) -> HTMLResponse:
    """The front page: a drawing, six lines and the links to the three pages behind it."""
    return templates.TemplateResponse(request, "landing.html", {"parent": parent_if_logged_in(request)})


@app.get("/how")
def how(request: Request) -> HTMLResponse:
    """What enoughy does, the long version of the landing page's first line."""
    return templates.TemplateResponse(request, "how.html", {"parent": parent_if_logged_in(request)})


@app.get("/why")
def why(request: Request) -> HTMLResponse:
    """Why this one and not Family Safety, the long version of the second line."""
    return templates.TemplateResponse(request, "why.html", {"parent": parent_if_logged_in(request)})


@app.get("/setup")
def setup_page(request: Request) -> HTMLResponse:
    """The parent's manual: account, child, installer, limit."""
    return templates.TemplateResponse(request, "setup.html", {"parent": parent_if_logged_in(request)})


@app.get("/login")
def login_form(request: Request) -> HTMLResponse:
    next_path = request.query_params.get("next", "/")
    return templates.TemplateResponse(
        request, "login.html", {"error": None, "next": local_path(next_path)}
    )


@app.post("/login")
async def login(request: Request) -> Response:
    form = await request.form()
    connection = db.connect()
    parent = parent_from_credentials(connection, form.get("login", ""), form.get("password", ""))
    if parent is None:
        connection.close()
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Wrong login or password.", "next": local_path(form.get("next", "/"))},
            status_code=401,
        )
    response = start_session(connection, parent.id, form.get("next", "/"))
    connection.close()
    return response


@app.get("/register")
def register_form(request: Request, invitation: str = "") -> HTMLResponse:
    if not invited(invitation):
        return by_invitation_only(request)
    return templates.TemplateResponse(
        request, "register.html", {"error": None, "invitation": invitation}
    )


def invited(invitation: str) -> bool:
    """Registration is open while ENOUGHY_INVITE is unset; otherwise the link
    handed out by the maintainer carries the value, and the form passes it on."""
    wanted = os.environ.get("ENOUGHY_INVITE")
    return not wanted or hmac.compare_digest(invitation, wanted)


def by_invitation_only(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "register.html", {"closed": True}, status_code=403)


@app.post("/register")
async def register(request: Request) -> Response:
    form = await request.form()
    invitation = form.get("invitation", "")
    if not invited(invitation):
        return by_invitation_only(request)
    login = form.get("login", "").strip()
    if form.get("password", "") != form.get("password_again", ""):
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "The two passwords differ.", "invitation": invitation},
            status_code=400,
        )
    connection = db.connect()
    try:
        parent_id = add_parent.add_parent(connection, login, form.get("password", ""))
    except ValueError as error:
        connection.close()
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": str(error).capitalize() + ".", "invitation": invitation},
            status_code=400,
        )
    except sqlite3.IntegrityError:
        connection.close()
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": f"{login} is taken.", "invitation": invitation},
            status_code=400,
        )
    response = start_session(connection, parent_id, next_path="/parent")
    connection.close()
    return response


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    connection = db.connect()
    response = end_session(connection, request)
    connection.close()
    return response


@app.get("/parent")
def parent_page(request: Request) -> HTMLResponse:
    """The parent's own page: the children and what is done to them, and the way out."""
    parent = current_parent(request)
    connection = db.connect()
    children = children_in_family(connection, parent.family_id, datetime.now(timezone.utc))
    connection.close()
    return templates.TemplateResponse(
        request,
        "parent.html",
        {"parent": parent, "children": children, "lifetime_hours": SETUP_CODE_LIFETIME // timedelta(hours=1)},
    )


@app.post("/children")
async def create_child(request: Request) -> RedirectResponse:
    parent = current_parent(request)
    form = await request.form()
    name = form.get("name", "").strip()
    connection = db.connect()
    try:
        add_child.add_child(connection, parent.family_id, name)
        child_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        make_setup_code(connection, child_id, datetime.now(timezone.utc))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail=f"you already have a child named {name}")
    finally:
        connection.close()
    return RedirectResponse("/parent", status_code=303)


@app.post("/children/setup-code")
async def new_setup_code(request: Request) -> RedirectResponse:
    """For a code that was let expire, or a reinstall of an existing child."""
    parent = current_parent(request)
    form = await request.form()
    connection = db.connect()
    try:
        child = require_child_in_family(connection, int(form.get("child_id", 0)), parent.family_id)
        make_setup_code(connection, child["id"], datetime.now(timezone.utc))
    finally:
        connection.close()
    return RedirectResponse("/parent", status_code=303)


@app.post("/children/delete")
async def delete_child(request: Request) -> RedirectResponse:
    """The child and everything the server holds about them. The monitor on
    their machine, if any, is refused at its next sync and goes on offline."""
    parent = current_parent(request)
    form = await request.form()
    connection = db.connect()
    try:
        child = require_child_in_family(connection, int(form.get("child_id", 0)), parent.family_id)
        with connection:
            for table in ("status", "grants", "settings_changes", "setup_codes", "children"):
                connection.execute(
                    f"DELETE FROM {table} WHERE {'id' if table == 'children' else 'child_id'} = :child_id",
                    {"child_id": child["id"]},
                )
    finally:
        connection.close()
    return RedirectResponse("/parent", status_code=303)


@app.get("/codes")
def codes_page(request: Request, child_id: int | None = None) -> HTMLResponse:
    parent = current_parent(request)
    connection = db.connect()
    children = children_with_codes(connection, parent.family_id)
    connection.close()
    selected_child = next(
        (child for child in children if child["id"] == child_id),
        children[0] if children else None,
    )
    return templates.TemplateResponse(
        request,
        "codes.html",
        {
            "parent": parent,
            "children": children,
            "selected_child": selected_child,
            "date": datetime.now(DISPLAY_TIMEZONE).date().isoformat(),
            "minutes": 60,
            "code": None,
        },
    )


@app.post("/codes")
async def make_code(request: Request) -> HTMLResponse:
    """A code for the day in the form, today unless the parent picked one,
    signed here so the secret stays on the server."""
    parent = current_parent(request)
    form = await request.form()
    kind = "nonight" if form.get("kind") == "nonight" else "time"
    try:
        child_id = int(form["child_id"])
        minutes = int(form.get("minutes", "")) if kind == "time" else 0
        if kind == "time" and minutes < 1:
            raise ValueError
        date = form.get("date", "").strip() or datetime.now(DISPLAY_TIMEZONE).date().isoformat()
        date = datetime.fromisoformat(date).date().isoformat()
    except (KeyError, ValueError, IndexError):
        raise HTTPException(status_code=400, detail="child_id and minutes must be whole numbers, date a day")
    connection = db.connect()
    try:
        child = require_child_in_family(connection, child_id, parent.family_id)
        if child["secret"] is None:
            raise HTTPException(status_code=404, detail="no secret for this child")
        children = children_with_codes(connection, parent.family_id)
    finally:
        connection.close()
    what = "nn" if kind == "nonight" else str(minutes)
    code = extra_time_code(child["secret"], date, what)
    return templates.TemplateResponse(
        request,
        "codes.html",
        {
            "parent": parent,
            "children": children,
            "selected_child": child,
            "date": date,
            "minutes": minutes or 60,
            "code": {"kind": kind, "text": code},
        },
    )


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
