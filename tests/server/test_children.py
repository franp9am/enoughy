"""A parent adds a child on the page and gets the setup code for the installer."""
import re

import db


def setup_code(page: str) -> str:
    return re.search(r"<code>(\d{6})</code>", page).group(1)


def test_adding_a_child_shows_its_setup_code_and_not_the_token(anna_logged_in):
    answer = anna_logged_in.post("/children", data={"name": "Tom"})
    assert answer.status_code == 200  # followed the redirect back to /children
    assert "Tom" in answer.text and "good until" in answer.text
    tom = db.connect().execute("SELECT token, secret FROM children").fetchone()
    assert tom["token"] not in answer.text
    traded = anna_logged_in.post("/api/setup", json={"code": setup_code(answer.text)})
    assert traded.json() == {"token": tom["token"], "secret": tom["secret"]}


def test_a_used_or_expired_code_gives_way_to_a_button_for_a_new_one(anna_logged_in):
    page = anna_logged_in.post("/children", data={"name": "Tom"}).text
    anna_logged_in.post("/api/setup", json={"code": setup_code(page)})
    page = anna_logged_in.get("/children").text
    assert "<code>" not in page and "Setup code</button>" in page
    page = anna_logged_in.post("/children/setup-code", data={"child_id": 1}).text
    assert "<code>" in page and "Setup code</button>" not in page


def test_a_code_for_another_family_s_child_is_refused(anna_logged_in, client):
    anna_logged_in.post("/children", data={"name": "Tom"})
    client.get("/logout")
    client.post("/register", data={"login": "bob", "password": "correct horse", "password_again": "correct horse"})
    assert client.post("/children/setup-code", data={"child_id": 1}).status_code == 404


def test_a_second_child_of_the_same_name_is_refused(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    answer = anna_logged_in.post("/children", data={"name": "Tom"})
    assert answer.status_code == 400


def test_a_nameless_child_is_refused(anna_logged_in):
    answer = anna_logged_in.post("/children", data={"name": "  "})
    assert answer.status_code == 400


def test_adding_a_child_needs_a_login(client):
    answer = client.post("/children", data={"name": "Tom"}, follow_redirects=False)
    assert answer.headers["location"] == "/login"


def test_a_new_child_is_on_the_children_page_not_the_dashboard(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    dashboard = anna_logged_in.get("/").text
    assert "Tom" not in dashboard  # nothing has synced for him yet
    assert "Tom" in anna_logged_in.get("/children").text


def test_a_removed_child_is_gone_with_their_history_and_their_monitor_is_refused(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    token = db.connect().execute("SELECT token FROM children").fetchone()["token"]
    report = {"date": "2026-10-12", "time_spent_sec": 600, "carryover_sec": 0, "granted_sec": 0,
              "remaining_sec": 3000, "last_tick": None, "applied_grant_ids": []}
    monitor = {"Authorization": f"Bearer {token}"}
    assert anna_logged_in.post("/api/sync", json=report, headers=monitor).status_code == 200
    anna_logged_in.post("/grants", data={"child_id": 1, "minutes": 10})
    page = anna_logged_in.post("/children/delete", data={"child_id": 1}).text
    assert "Tom" not in page
    connection = db.connect()
    for table in ("children", "status", "grants", "setup_codes"):
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    assert anna_logged_in.post("/api/sync", json=report, headers=monitor).status_code == 401
    assert anna_logged_in.post("/children", data={"name": "Tom"}).status_code == 200  # the name is free again


def test_removing_another_family_s_child_is_refused(anna_logged_in, client):
    anna_logged_in.post("/children", data={"name": "Tom"})
    client.get("/logout")
    client.post("/register", data={"login": "bob", "password": "correct horse", "password_again": "correct horse"})
    assert client.post("/children/delete", data={"child_id": 1}).status_code == 404
    assert db.connect().execute("SELECT count(*) FROM children").fetchone()[0] == 1
