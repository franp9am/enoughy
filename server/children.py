"""The children of a family: who the dashboard and the code page list,
setup codes for the installer, and the offline codes signed with a child's key."""
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta

from fastapi import HTTPException

from views import formatted_local_time

# A setup code, the six digits the installer trades for a child's token and
# secret, lasts this long after the page shows it: from the page to the
# child's computer, with the download and the account pages in between.
SETUP_CODE_LIFETIME = timedelta(hours=1)


def children_in_family(connection: sqlite3.Connection, family_id: int, now: datetime) -> list[dict]:
    """Each child with its setup code and the local time the code is good
    until, both None once it is used or past its lifetime."""
    lifetime_ago = (now - SETUP_CODE_LIFETIME).isoformat(timespec="seconds")
    rows = connection.execute(
        """SELECT children.id, name, code, created_at FROM children
           LEFT JOIN setup_codes ON child_id = children.id AND created_at > :lifetime_ago
           WHERE family_id = :family_id ORDER BY children.id""",
        {"family_id": family_id, "lifetime_ago": lifetime_ago},
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "code": row["code"],
            "good_until": row["code"] and formatted_local_time(
                (datetime.fromisoformat(row["created_at"]) + SETUP_CODE_LIFETIME).isoformat()
            ),
        }
        for row in rows
    ]


def make_setup_code(connection: sqlite3.Connection, child_id: int, now: datetime) -> str:
    """A fresh six-digit code for the child, in place of the one it had.
    Codes are unique while pending, so a collision with another child's,
    one in a million, is simply drawn again."""
    with connection:
        connection.execute("DELETE FROM setup_codes WHERE child_id = :child_id", {"child_id": child_id})
        while True:
            code = f"{secrets.randbelow(1_000_000):06}"
            try:
                connection.execute(
                    "INSERT INTO setup_codes (child_id, code, created_at) VALUES (?, ?, ?)",
                    (child_id, code, now.isoformat(timespec="seconds")),
                )
                return code
            except sqlite3.IntegrityError:
                continue


def synced_children(connection: sqlite3.Connection, family_id: int) -> list[sqlite3.Row]:
    """The children the dashboard is about: those whose machine has reported at least once."""
    return connection.execute(
        "SELECT id, name FROM children WHERE family_id = :family_id"
        " AND EXISTS (SELECT 1 FROM status WHERE status.child_id = children.id) ORDER BY id",
        {"family_id": family_id},
    ).fetchall()


def children_with_codes(connection: sqlite3.Connection, family_id: int) -> list[sqlite3.Row]:
    """The children /codes is about: those whose key the server knows."""
    return connection.execute(
        "SELECT id, name FROM children WHERE family_id = :family_id AND secret IS NOT NULL"
        " ORDER BY id",
        {"family_id": family_id},
    ).fetchall()


# Mirror of read_redeem_file in monitor/monitor.py and of the signing in
# parent/extra_time.html: a code is <minutes>:<signature> for extra time or
# nn:<signature> for no night, good on the day it was made: the signature is
# HMAC-SHA256 of <date>:<minutes> or <date>:nn under the child's key, cut to
# SIGNATURE_CHARS, which must equal monitor/config.py.
SIGNATURE_CHARS = 4


def extra_time_code(key_hex: str, date: str, what: str) -> str:
    payload = f"{date}:{what}"
    signature = hmac.new(bytes.fromhex(key_hex), payload.encode(), hashlib.sha256).hexdigest()
    return f"{what}:{signature[:SIGNATURE_CHARS]}"


def require_child_in_family(
    connection: sqlite3.Connection, child_id: int, family_id: int
) -> sqlite3.Row:
    """A child belonging to another family is indistinguishable from one that does not exist."""
    child = connection.execute(
        "SELECT id, name, secret FROM children WHERE id = :child_id AND family_id = :family_id",
        {"child_id": child_id, "family_id": family_id},
    ).fetchone()
    if child is None:
        raise HTTPException(status_code=404, detail="unknown child")
    return child
