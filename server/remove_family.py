"""For the maintainer: a family and every trace of it, named by one of its parents.

    uv run python remove_family.py <login>

Shows what is about to go and asks for the family name back before deleting:
the children with their status, grants, settings changes and setup codes,
then every parent of the family with their sessions, then the family. A
monitor still installed is refused at its next sync and goes on offline.
"""
import sys

import db


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
    with connection:
        for child in children:
            for table in ("status", "grants", "settings_changes", "setup_codes"):
                connection.execute(f"DELETE FROM {table} WHERE child_id = ?", (child["id"],))
        connection.execute("DELETE FROM children WHERE family_id = ?", (family["id"],))
        connection.execute(
            "DELETE FROM sessions WHERE parent_id IN (SELECT id FROM parents WHERE family_id = ?)",
            (family["id"],),
        )
        connection.execute("DELETE FROM parents WHERE family_id = ?", (family["id"],))
        connection.execute("DELETE FROM families WHERE id = ?", (family["id"],))
    connection.close()
    print(f"family {family['name']!r} removed")


if __name__ == "__main__":
    main()
