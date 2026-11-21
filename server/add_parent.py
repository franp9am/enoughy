import getpass
import sqlite3
import sys
import unicodedata
from pathlib import Path

import bcrypt
from zxcvbn import zxcvbn

import db


def family_id(connection: sqlite3.Connection, family_name: str) -> int:
    """Families are created on first use: the first parent of a family makes it exist."""
    connection.execute("INSERT OR IGNORE INTO families (name) VALUES (?)", (family_name,))
    return connection.execute(
        "SELECT id FROM families WHERE name = ?", (family_name,)
    ).fetchone()["id"]


MIN_PASSWORD_CHARS = 8
# zxcvbn says how many guesses a password takes at least. No rules for the parent
# to satisfy: 12345678, qwertyuiop, anna1985 and heslo123 simply come out too low.
# It is a floor and not an estimate: characters it finds no pattern in count as
# ten possibilities each, so eight random ones are 10^8 where the truth is 10^15.
MIN_PASSWORD_GUESSES = 10 ** 7
MAX_PASSWORD_CHARS = 72  # what bcrypt hashes and zxcvbn accepts


def without_diacritics(word: str) -> str:
    return unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode()


def czech_words() -> list[str]:
    """Every word of czech_words.txt, followed by itself without diacritics."""
    lines = Path(__file__).with_name("czech_words.txt").read_text(encoding="utf-8").splitlines()
    words = [word for line in lines if not line.startswith("#") for word in line.split()]
    return list(dict.fromkeys(form for word in words for form in (word, without_diacritics(word))))


CZECH_WORDS = czech_words()


def password_fault(password: str, login: str) -> str | None:
    """Why this password will not do for this parent, or None when it will."""
    if len(password) < MIN_PASSWORD_CHARS:
        return f"the password needs at least {MIN_PASSWORD_CHARS} characters"
    if len(password) > MAX_PASSWORD_CHARS:
        return f"the password can have at most {MAX_PASSWORD_CHARS} characters"
    if zxcvbn(password, user_inputs=[login, "enoughy"] + CZECH_WORDS)["guesses"] < MIN_PASSWORD_GUESSES:
        return "password too simple, robots would guess it.\nPlease try another one"
    return None


def add_parent(
    connection: sqlite3.Connection, login: str, password: str, family_name: str | None = None
) -> int:
    """A parent who registers gets a family of their own, named after them.
    Returns the new parent's id."""
    if not login:
        raise ValueError("a login is needed")
    fault = password_fault(password, login)
    if fault:
        raise ValueError(fault)
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
