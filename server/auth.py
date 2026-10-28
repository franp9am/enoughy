"""Who the person behind a request is, and how they prove it.

A parent proves who they are once, with login and password, and from then on
by the session cookie that `start_session` set. Swapping this for an identity
provider means rewriting this module and nothing else.
"""
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import bcrypt
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

import db

SESSION_COOKIE = "session"
SESSION_DAYS = 90


@dataclass
class Parent:
    id: int
    login: str
    family_id: int


class NotLoggedIn(Exception):
    pass


def parent_from_credentials(
    connection: sqlite3.Connection, login: str, password: str
) -> Parent | None:
    """The parent with this login and password, or None."""
    row = connection.execute(
        "SELECT id, login, family_id, password_hash FROM parents WHERE login = :login",
        {"login": login},
    ).fetchone()
    if row is None or not row["password_hash"]:
        return None  # a parent without a password yet cannot log in
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None
    return Parent(id=row["id"], login=row["login"], family_id=row["family_id"])


def current_parent(request: Request) -> Parent:
    """The parent whose session cookie this request carries; NotLoggedIn otherwise."""
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise NotLoggedIn()
    connection = db.connect()
    session = connection.execute(
        "SELECT parent_id FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if session is None:
        connection.close()
        raise NotLoggedIn()
    parent = connection.execute(
        "SELECT id, login, family_id FROM parents WHERE id = ?", (session["parent_id"],)
    ).fetchone()
    connection.close()
    return Parent(id=parent["id"], login=parent["login"], family_id=parent["family_id"])


def local_path(candidate: str) -> str:
    """The page to return to after login: a path on this site, or the front page."""
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return "/"


def start_session(
    connection: sqlite3.Connection, parent_id: int, next_path: str = "/"
) -> RedirectResponse:
    """A new session for the parent, and the browser sent to `next_path` with its cookie."""
    session_id = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection:
        connection.execute(
            "INSERT INTO sessions (id, parent_id, created_at) VALUES (?, ?, ?)",
            (session_id, parent_id, created_at),
        )
    response = RedirectResponse(local_path(next_path), status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,  # page scripts cannot read it
        secure=True,  # sent over https only
        samesite="lax",  # not sent with forms posted from other sites
    )
    return response


def end_session(connection: sqlite3.Connection, request: Request) -> RedirectResponse:
    """Deletes the session, so the cookie is worthless even if the browser keeps it."""
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        with connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response



def authenticated_child_id(authorization: str) -> int:
    """The child behind a monitor's request, proved by its bearer token."""
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
