"""A family and every trace of it. A parent removes their own on their page;
the maintainer removes one named by one of its parents:

    uv run python remove_family.py <login>

which shows what is about to go and asks for the family name back before
deleting. A monitor still installed is refused at its next sync and goes on
offline. The backups made before are deleted too, since each still holds
the family, and a new one is taken without it.
"""
import sqlite3
import sys

import backup
import db


def remove_family(connection: sqlite3.Connection, family_id: int) -> None:
    """The children with their status, grants, settings changes and setup codes,
    then every parent of the family with their sessions, then the family, and
    last the backups that still hold any of it."""
    of_family = "(SELECT id FROM {} WHERE family_id = ?)"
    with connection:
        for table in ("status", "grants", "settings_changes", "setup_codes"):
            connection.execute(
                f"DELETE FROM {table} WHERE child_id IN {of_family.format('children')}", (family_id,)
            )
        connection.execute("DELETE FROM children WHERE family_id = ?", (family_id,))
        connection.execute(
            f"DELETE FROM sessions WHERE parent_id IN {of_family.format('parents')}", (family_id,)
        )
        connection.execute("DELETE FROM parents WHERE family_id = ?", (family_id,))
        connection.execute("DELETE FROM families WHERE id = ?", (family_id,))
    backup.forget(connection)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python remove_family.py <login>")
    login = sys.argv[1]
    connection = db.connect()
    family = connection.execute(
        "SELECT families.id, families.name FROM families"
        " JOIN parents ON parents.family_id = families.id WHERE parents.login = ?",
        (login,),
    ).fetchone()
    if family is None:
        sys.exit(f"no parent {login!r}")
    parents = [row["login"] for row in connection.execute(
        "SELECT login FROM parents WHERE family_id = ? ORDER BY login", (family["id"],)
    )]
    children = connection.execute(
        "SELECT id, name FROM children WHERE family_id = ? ORDER BY name", (family["id"],)
    ).fetchall()
    print(f"family {family['name']!r}: parents {', '.join(parents)};"
          f" children {', '.join(child['name'] for child in children) or 'none'}")
    if input("type the family name to delete all of it: ") != family["name"]:
        sys.exit("nothing deleted")
    remove_family(connection, family["id"])
    connection.close()
    print(f"family {family['name']!r} removed")


if __name__ == "__main__":
    main()
