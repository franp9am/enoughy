"""Copies of the database in `backups`, the folder next to it, against the
maintainer's own mistakes: a wrong ALTER TABLE, a bug that spoils rows. They
never leave the machine, so they are no help when the machine is lost.

    uv run python backup.py

takes one and drops all but the newest KEPT; a systemd timer runs it every
night, the maintainer by hand before touching the live database. Putting one
back is stopping the server and copying the file over the database.

A family that is removed is gone from the copies too: see `forget`.
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import db

KEPT = 7


def folder() -> Path:
    return db.DB_PATH.parent / "backups"


def copies() -> list[Path]:
    """Oldest first: the name carries the time the copy was taken."""
    return sorted(folder().glob("enoughy-*.sqlite"))


def take(connection: sqlite3.Connection, now: datetime | None = None) -> Path:
    """A copy of the database as it is now, and the old ones beyond KEPT dropped.

    VACUUM INTO and not a copy of the file: it is safe while the server
    writes, and it carries only the rows that exist, where the file's free
    pages could still hold what was deleted."""
    now = now or datetime.now(timezone.utc)
    # the file holds password hashes, tokens and the keys of the offline codes
    folder().mkdir(mode=0o700, exist_ok=True)
    copy = folder() / f"enoughy-{now:%Y%m%dT%H%M%SZ}.sqlite"
    # under another name until it is whole, so a failed one is never counted
    unfinished = copy.with_suffix(".unfinished")
    unfinished.unlink(missing_ok=True)
    connection.execute("VACUUM INTO ?", (str(unfinished),))
    os.chmod(unfinished, 0o600)
    os.replace(unfinished, copy)
    for old in copies()[:-KEPT]:
        old.unlink()
    return copy


def forget(connection: sqlite3.Connection) -> None:
    """After a family is removed: every copy goes, since each still holds it,
    and one of the database without it takes their place. Where no copy was
    ever taken there is nothing to forget, and none is started."""
    old = copies()
    if not old:
        return
    for copy in old:
        copy.unlink()
    take(connection)


def main() -> None:
    connection = db.connect()
    print(take(connection))
    connection.close()


if __name__ == "__main__":
    main()
