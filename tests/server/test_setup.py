"""The installer trades a setup code for the child's token and secret."""
from datetime import datetime, timedelta, timezone

import app
import db


def code_made(code: str, age: timedelta = timedelta(0)) -> None:
    """The one code Tom has, as the page will make it."""
    created_at = (datetime.now(timezone.utc) - age).isoformat(timespec="seconds")
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO setup_codes (child_id, code, created_at) VALUES (1, ?, ?)",
            (code, created_at),
        )


def test_a_code_is_traded_for_the_token_and_the_secret_once(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    code_made("123456")
    answer = anna_logged_in.post("/api/setup", json={"code": " 123456 "})
    assert answer.status_code == 200
    tom = db.connect().execute("SELECT token, secret FROM children").fetchone()
    assert answer.json() == {"token": tom["token"], "secret": tom["secret"]}
    assert anna_logged_in.post("/api/setup", json={"code": "123456"}).status_code == 401


def test_a_child_without_a_secret_gets_one_with_the_trade(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    with db.connect() as connection:
        connection.execute("UPDATE children SET secret = NULL")
    code_made("123456")
    answer = anna_logged_in.post("/api/setup", json={"code": "123456"})
    secret = db.connect().execute("SELECT secret FROM children").fetchone()["secret"]
    assert len(secret) == 32 and answer.json()["secret"] == secret


def test_a_code_older_than_its_lifetime_is_unknown(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    code_made("123456", age=app.SETUP_CODE_LIFETIME + timedelta(seconds=1))
    assert anna_logged_in.post("/api/setup", json={"code": "123456"}).status_code == 401

