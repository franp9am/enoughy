"""For the maintainer: a new password for a parent who lost theirs.

    uv run python set_password.py <login>

Every session of that parent is ended too, so a stolen cookie dies with the
old password.
"""
import getpass
import sys

import bcrypt

import db
from add_parent import MIN_PASSWORD_CHARS


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python set_password.py <login>")
    login = sys.argv[1]
    password = getpass.getpass(f"new password for {login}: ")
    if len(password) < MIN_PASSWORD_CHARS:
        sys.exit(f"the password needs at least {MIN_PASSWORD_CHARS} characters")
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()
    connection = db.connect()
    with connection:
        changed = connection.execute(
            "UPDATE parents SET password_hash = ? WHERE login = ?", (password_hash, login)
        ).rowcount
        if changed == 0:
            sys.exit(f"no parent {login!r}")
        connection.execute(
            "DELETE FROM sessions WHERE parent_id = (SELECT id FROM parents WHERE login = ?)",
            (login,),
        )
    connection.close()
    print(f"password of {login} changed, and they are logged out everywhere")


if __name__ == "__main__":
    main()
