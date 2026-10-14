"""Offline extra-time codes made on the server, under the child's own secret."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import add_parent
import db
import monitor

SECRETS = {"Tom": "0102030405060708090a0b0c0d0e0f10", "Elias": "101112131415161718191a1b1c1d1e1f"}


def key_on_the_machine(child_name: str) -> bytes:
    """What the install keeps in secret.txt."""
    return bytes.fromhex(SECRETS[child_name])


@pytest.fixture
def anna(client):
    """Anna, logged in, with Tom (syncs) and Elias (offline install), both with a secret."""
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    connection.executescript(f"""
        INSERT INTO children (id, family_id, name, token, secret) VALUES
            (1, 1, 'Tom', 'tom-token', '{SECRETS["Tom"]}'),
            (3, 1, 'Elias', 'elias-token', '{SECRETS["Elias"]}');
        INSERT INTO status (child_id, date, time_spent_sec, remaining_sec, updated_at) VALUES
            (1, '2026-10-11', 600, 3000, '2026-10-11T10:00:00+00:00');
    """)
    connection.close()
    client.post("/login", data={"login": "anna", "password": "correct horse"})
    return client


def test_the_dashboard_lists_only_children_that_have_synced(anna):
    page = anna.get("/").text
    assert "Tom" in page
    assert "Elias" not in page


def test_the_codes_page_lists_every_child(anna):
    page = anna.get("/codes").text
    assert "Tom" in page and "Elias" in page


def accepted_by_the_monitor(code: str, child_name: str, tmp_path, today=None):
    redeem_file = tmp_path / "extra_time.txt"
    redeem_file.write_text(code)
    today = today or datetime.now(ZoneInfo("Europe/Prague")).date()
    return monitor.read_redeem_file(redeem_file, key_on_the_machine(child_name), today)


def code_on(page: str) -> str:
    return page.split('<div class="code"><code>')[1].split("</code>")[0]


def test_an_extra_time_code_is_one_the_monitor_accepts(anna, tmp_path):
    page = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": 30}).text
    result = accepted_by_the_monitor(code_on(page), "Elias", tmp_path)
    assert result["status"] == "valid"
    assert result["extra_time_sec"] == 1800


def test_a_no_night_code_is_one_the_monitor_accepts(anna, tmp_path):
    page = anna.post("/codes", data={"child_id": 3, "kind": "nonight", "minutes": 60}).text
    result = accepted_by_the_monitor(code_on(page), "Elias", tmp_path)
    assert result["status"] == "valid"
    assert result["nonight"] is True


def test_a_code_for_another_day_is_good_on_that_day_only(anna, tmp_path):
    page = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": 30, "date": "2026-12-24"}).text
    code = code_on(page)
    assert accepted_by_the_monitor(code, "Elias", tmp_path, date(2026, 12, 24))["status"] == "valid"
    assert accepted_by_the_monitor(code, "Elias", tmp_path)["status"] == "invalid signature"


def test_a_day_that_is_no_day_is_refused(anna):
    answer = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": 30, "date": "christmas"})
    assert answer.status_code == 400


def test_a_siblings_code_is_refused_on_the_other_machine(anna, tmp_path):
    page = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": 30}).text
    result = accepted_by_the_monitor(code_on(page), "Tom", tmp_path)
    assert result["status"] == "invalid signature"


def test_no_code_for_another_familys_child(anna):
    connection = db.connect()
    add_parent.add_parent(connection, "petr", password="correct horse")
    connection.execute(
        "INSERT INTO children (id, family_id, name, token) VALUES (9, 2, 'Jan', 'jan')"
    )
    connection.commit()
    answer = anna.post("/codes", data={"child_id": 9, "kind": "time", "minutes": 30})
    assert answer.status_code == 404


def test_a_child_whose_secret_the_server_does_not_know_has_no_codes(anna):
    connection = db.connect()
    connection.execute("UPDATE children SET secret = NULL WHERE name = 'Elias'")
    connection.commit()
    page = anna.get("/codes").text
    assert "Tom" in page and "Elias" not in page
    answer = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": 30})
    assert answer.status_code == 404


def test_without_any_secret_the_codes_page_lists_no_child(anna):
    connection = db.connect()
    connection.execute("UPDATE children SET secret = NULL")
    connection.commit()
    assert "Elias" not in anna.get("/codes").text


def test_a_child_added_on_the_page_gets_a_secret_of_its_own(anna):
    anna.post("/children", data={"name": "Mia"})
    secrets = [row["secret"] for row in db.connect().execute("SELECT secret FROM children")]
    mia = secrets[-1]
    assert re.fullmatch(r"[0-9a-f]{32}", mia)
    assert mia not in secrets[:-1]


def test_the_page_keeps_the_typed_minutes(anna, tmp_path):
    page = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": "45"}).text
    assert 'name="minutes" step="1" min="1" value="45"' in page
    result = accepted_by_the_monitor(code_on(page), "Elias", tmp_path)
    assert result["extra_time_sec"] == 2700
