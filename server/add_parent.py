import getpass
import sqlite3
import sys

import bcrypt

import db


def family_id(connection: sqlite3.Connection, family_name: str) -> int:
    """Families are created on first use: the first parent of a family makes it exist."""
    connection.execute(
        "INSERT OR IGNORE INTO families (name) VALUES (?)", (family_name,)
    )
    return connection.execute(
        "SELECT id FROM families WHERE name = ?", (family_name,)
    ).fetchone()["id"]


def add_parent(
    connection: sqlite3.Connection, login: str, family_name: str, password: str
) -> None:
    if not password:
        raise ValueError("empty password")
    # Work factor 10 is about 100 ms per check: slow enough that a stolen
    # database does not give the passwords up, fast enough for a login form.
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10))
    with connection:
        connection.execute(
            "INSERT INTO parents (login, family_id, password_hash) VALUES (?, ?, ?)",
            (login, family_id(connection, family_name), password_hash.decode()),
        )


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: python add_parent.py <login> <family>")
    login, family_name = sys.argv[1], sys.argv[2]
    password = getpass.getpass(f"password for {login}: ")
    db.create_schema()
    connection = db.connect()
    try:
        add_parent(connection, login, family_name, password)
    except sqlite3.IntegrityError:
        sys.exit(f"parent {login!r} already exists")
    except ValueError as error:
        sys.exit(str(error))
    finally:
        connection.close()
    print(f"{login} added to family {family_name}")


if __name__ == "__main__":
    main()
