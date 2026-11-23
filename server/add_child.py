import secrets
import sqlite3
import sys

import db


MIN_TOKEN_CHARS = 16
MAX_NAME_CHARS = 32
MAX_CHILDREN = 16  # in one family; more than any has, and an end to what one account can store


def add_child(
    connection: sqlite3.Connection, family_id: int, name: str, token: str | None = None
) -> str:
    """Adds the child, with a secret of its own for the offline codes, and
    returns the token its monitor will sync with."""
    if not name:
        raise ValueError("a name is needed")
    if len(name) > MAX_NAME_CHARS:
        raise ValueError(f"name too long, at most {MAX_NAME_CHARS} characters")
    if token is None:
        token = secrets.token_hex(16)
    if len(token) < MIN_TOKEN_CHARS:
        raise ValueError(f"the token needs at least {MIN_TOKEN_CHARS} characters")
    with connection:
        children = connection.execute(
            "SELECT COUNT(*) FROM children WHERE family_id = ?", (family_id,)
        ).fetchone()[0]
        if children >= MAX_CHILDREN:
            raise ValueError(f"family can have {MAX_CHILDREN} children max")
        connection.execute(
            "INSERT INTO children (family_id, name, token, secret) VALUES (?, ?, ?, ?)",
            (family_id, name, token, secrets.token_hex(16)),
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
