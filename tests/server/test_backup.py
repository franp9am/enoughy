"""Copies of the database in a folder next to it, and a removed family gone from them."""
import sqlite3
from datetime import datetime, timedelta, timezone

import backup
import db

NIGHT = datetime(2026, 11, 23, 3, 0, tzinfo=timezone.utc)


def logins(copy) -> list[str]:
    connection = sqlite3.connect(copy)
    found = [row[0] for row in connection.execute("SELECT login FROM parents ORDER BY login")]
    connection.close()
    return found


def test_a_copy_holds_what_the_database_held_then(anna_logged_in):
    copy = backup.take(db.connect(), NIGHT)
    anna_logged_in.get("/logout")
    anna_logged_in.post("/register", data={"login": "bob", "password": "battery staple", "password_again": "battery staple"})
    assert copy.name == "enoughy-20261123T030000Z.sqlite"
    assert copy.parent == db.DB_PATH.parent / "backups"
    assert logins(copy) == ["anna"]
    assert logins(db.DB_PATH) == ["anna", "bob"]


def test_only_the_newest_are_kept(client):
    connection = db.connect()
    for day in range(backup.KEPT + 3):
        backup.take(connection, NIGHT + timedelta(days=day))
    kept = backup.copies()
    assert len(kept) == backup.KEPT
    assert kept[0].name == "enoughy-20261126T030000Z.sqlite"
    assert kept[-1].name == "enoughy-20261202T030000Z.sqlite"


def test_a_copy_taken_twice_in_one_second_is_one_copy(client):
    connection = db.connect()
    backup.take(connection, NIGHT)
    backup.take(connection, NIGHT)
    assert len(backup.copies()) == 1
    assert [path.name for path in backup.folder().iterdir()] == ["enoughy-20261123T030000Z.sqlite"]


def test_a_removed_family_is_gone_from_the_copies(anna_logged_in, client):
    client.get("/logout")
    client.post("/register", data={"login": "bob", "password": "battery staple", "password_again": "battery staple"})
    connection = db.connect()
    backup.take(connection, NIGHT)
    backup.take(connection, NIGHT + timedelta(days=1))
    client.post("/family/delete", data={"password": "battery staple"})
    (copy,) = backup.copies()
    assert logins(copy) == ["anna"]
    assert b"bob" not in copy.read_bytes()


def test_removing_a_family_starts_no_copies_where_none_were_taken(anna_logged_in):
    anna_logged_in.post("/family/delete", data={"password": "correct horse"})
    assert not backup.folder().exists()
