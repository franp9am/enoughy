import secrets
import sqlite3
import sys

import db


MIN_TOKEN_CHARS = 16


def add_child(
    connection: sqlite3.Connection, family_id: int, name: str, token: str | None = None
) -> str:
    """Adds the child and returns the token its monitor will sync with."""
    if not name:
        raise ValueError("a name is needed")
    if token is None:
        token = secrets.token_hex(16)
    if len(token) < MIN_TOKEN_CHARS:
        raise ValueError(f"the token needs at least {MIN_TOKEN_CHARS} characters")
    with connection:
        connection.execute(
            "INSERT INTO children (family_id, name, token) VALUES (?, ?, ?)",
            (family_id, name, token),
        )
    return token


def main() -> None:
    if len(sys.argv) not in (3, 4):
        sys.exit("usage: python add_child.py <family> <name> [token]")
    family_name, name = sys.argv[1], sys.argv[2]
    token = sys.argv[3] if len(sys.argv) == 4 else None
    db.create_schema()
    connection = db.connect()
    family = connection.execute(
        "SELECT id FROM families WHERE name = ?", (family_name,)
    ).fetchone()
    if family is None:
        connection.close()
        sys.exit(f"no family {family_name!r} -- create it with add_parent.py")
    try:
        print(add_child(connection, family["id"], name, token))
    except sqlite3.IntegrityError:
        sys.exit(f"child {name!r} already exists in family {family_name!r}")
    except ValueError as error:
        sys.exit(str(error))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
