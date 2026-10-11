"""Offline extra-time codes made on the server, for a child whose secret it knows."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import add_parent
import db
import monitor

SECRET = "0102030405060708090a0b0c0d0e0f10"


@pytest.fixture
def anna(client):
    """Anna, logged in, with Tom (syncs, has a secret), Nora (syncs, no secret)
    and Elias (offline install, has a secret)."""
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    connection.executescript(f"""
        INSERT INTO children (id, family_id, name, token, secret) VALUES
            (1, 1, 'Tom', 'tom-token', '{SECRET}'),
            (2, 1, 'Nora', 'nora-token', NULL),
            (3, 1, 'Elias', 'elias-token', '{SECRET}');
        INSERT INTO status (child_id, date, time_spent_sec, remaining_sec, updated_at) VALUES
            (1, '2026-10-11', 600, 3000, '2026-10-11T10:00:00+00:00'),
            (2, '2026-10-11', 600, 3000, '2026-10-11T10:00:00+00:00');
    """)
    connection.close()
    client.post("/login", data={"login": "anna", "password": "correct horse"})
    return client


def test_the_dashboard_lists_only_children_that_have_synced(anna):
    page = anna.get("/").text
    assert "Tom" in page and "Nora" in page
    assert "Elias" not in page


def test_the_codes_page_lists_only_children_with_a_secret(anna):
    page = anna.get("/codes").text
    assert "Tom" in page and "Elias" in page
    assert "Nora" not in page


def accepted_by_the_monitor(code: str, tmp_path):
    redeem_file = tmp_path / "extra_time.txt"
    redeem_file.write_text(code)
    today = datetime.now(ZoneInfo("Europe/Prague")).date()
    return monitor.handle_redeem_file(redeem_file, bytes.fromhex(SECRET), today)


def test_an_extra_time_code_is_one_the_monitor_accepts(anna, tmp_path):
    page = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": 30}).text
    code = page.split('<code class="code">')[1].split("</code>")[0]
    result = accepted_by_the_monitor(code, tmp_path)
    assert result["status"] == "valid"
    assert result["extra_time_sec"] == 1800


def test_a_no_night_code_is_one_the_monitor_accepts(anna, tmp_path):
    page = anna.post("/codes", data={"child_id": 3, "kind": "nonight", "minutes": 60}).text
    code = page.split('<code class="code">')[1].split("</code>")[0]
    result = accepted_by_the_monitor(code, tmp_path)
    assert result["status"] == "valid"
    assert result["nonight"] is True


def test_no_code_for_another_familys_child(anna):
    connection = db.connect()
    add_parent.add_parent(connection, "petr", password="correct horse")
    connection.execute(
        f"INSERT INTO children (id, family_id, name, token, secret) VALUES (9, 2, 'Jan', 'jan', '{SECRET}')"
    )
    connection.commit()
    answer = anna.post("/codes", data={"child_id": 9, "kind": "time", "minutes": 30})
    assert answer.status_code == 404


def test_the_dashboard_links_to_codes_only_when_there_are_some(anna):
    assert "Extra time codes" in anna.get("/").text
    connection = db.connect()
    connection.execute("UPDATE children SET secret = NULL")
    connection.commit()
    assert "Extra time codes" not in anna.get("/").text
