import getpass
import sqlite3
import sys

import bcrypt

import db


def family_id(connection: sqlite3.Connection, family_name: str) -> int:
    """Families are created on first use: the first parent of a family makes it exist."""
    connection.execute("INSERT OR IGNORE INTO families (name) VALUES (?)", (family_name,))
    return connection.execute(
        "SELECT id FROM families WHERE name = ?", (family_name,)
    ).fetchone()["id"]


MIN_PASSWORD_CHARS = 8


def add_parent(
    connection: sqlite3.Connection, login: str, password: str, family_name: str | None = None
) -> int:
    """A parent who registers gets a family of their own, named after them.
    Returns the new parent's id."""
    if not login:
        raise ValueError("a login is needed")
    if len(password) < MIN_PASSWORD_CHARS:
        raise ValueError(f"the password needs at least {MIN_PASSWORD_CHARS} characters")
    if family_name is None:
        family_name = login
    # Work factor 10 is about 100 ms per check: slow enough that a stolen
    # database does not give the passwords up, fast enough for a login form.
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10))
    with connection:
        inserted = connection.execute(
            "INSERT INTO parents (login, family_id, password_hash) VALUES (?, ?, ?)",
            (login, family_id(connection, family_name), password_hash.decode()),
        )
    return inserted.lastrowid


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: python add_parent.py <login> [family]")
    login = sys.argv[1]
    family_name = sys.argv[2] if len(sys.argv) == 3 else login
    password = getpass.getpass(f"password for {login}: ")
    db.create_schema()
    connection = db.connect()
    try:
        add_parent(connection, login, password, family_name)
    except sqlite3.IntegrityError:
        sys.exit(f"parent {login!r} already exists")
    except ValueError as error:
        sys.exit(str(error))
    finally:
        connection.close()
    print(f"{login} added to family {family_name}")


if __name__ == "__main__":
    main()
