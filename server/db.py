import os
import sqlite3
from pathlib import Path

DB_PATH = Path(
    os.environ.get("CHILD_CONTROL_DB") or Path(__file__).parent / "data" / "child_control.sqlite"
)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS parents (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    family_id INTEGER NOT NULL REFERENCES families(id)
);
CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY,
    family_id INTEGER NOT NULL REFERENCES families(id),
    name TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    UNIQUE (family_id, name)
);
CREATE TABLE IF NOT EXISTS grants (
    id INTEGER PRIMARY KEY,
    child_id INTEGER NOT NULL REFERENCES children(id),
    granted_by INTEGER NOT NULL REFERENCES parents(id),
    seconds INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    acked_at TEXT
);
-- `settings` is every setting the parent wants in force, as JSON, never a
-- subset; the newest row for a child is the one that counts.
CREATE TABLE IF NOT EXISTS settings_changes (
    id INTEGER PRIMARY KEY,
    child_id INTEGER NOT NULL REFERENCES children(id),
    changed_by INTEGER NOT NULL REFERENCES parents(id),
    settings TEXT NOT NULL,
    created_at TEXT NOT NULL,
    -- NULL until the child answers, then 'taken' or 'refused'; a change is
    -- sent only while this is NULL
    outcome TEXT
);
CREATE TABLE IF NOT EXISTS status (
    child_id INTEGER NOT NULL REFERENCES children(id),
    date TEXT NOT NULL,
    time_spent_sec INTEGER NOT NULL,
    carryover_sec INTEGER NOT NULL DEFAULT 0,
    granted_sec INTEGER NOT NULL DEFAULT 0,
    remaining_sec INTEGER NOT NULL,
    last_tick TEXT,
    updated_at TEXT NOT NULL,
    reported_settings TEXT,
    -- NULL from a monitor too old to say; added by hand to the live database
    monitor_version TEXT,
    PRIMARY KEY (child_id, date)
);
"""


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema() -> None:
    connection = connect()
    connection.executescript(SCHEMA)
    connection.commit()
    connection.close()
