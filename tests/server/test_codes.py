"""Offline extra-time codes made on the server, under a key derived from the
family's secret and the child's name."""
import hashlib
import hmac
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import add_parent
import db
import monitor

FAMILY_SECRET = "0102030405060708090a0b0c0d0e0f10"


def key_on_the_machine(child_name: str) -> bytes:
    """What the install keeps in secret.txt, computed here on its own so the
    test does not trust the server's derivation."""
    return bytes.fromhex(
        hmac.new(bytes.fromhex(FAMILY_SECRET), child_name.encode(), hashlib.sha256).hexdigest()[:32]
    )


@pytest.fixture
def anna(client):
    """Anna, logged in, family secret set, with Tom (syncs) and Elias (offline install)."""
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    connection.executescript(f"""
        UPDATE families SET secret = '{FAMILY_SECRET}';
        INSERT INTO children (id, family_id, name, token) VALUES
            (1, 1, 'Tom', 'tom-token'),
            (3, 1, 'Elias', 'elias-token');
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


def accepted_by_the_monitor(code: str, child_name: str, tmp_path):
    redeem_file = tmp_path / "extra_time.txt"
    redeem_file.write_text(code)
    today = datetime.now(ZoneInfo("Europe/Prague")).date()
    return monitor.handle_redeem_file(redeem_file, key_on_the_machine(child_name), today)


def code_on(page: str) -> str:
    return page.split('<code class="code">')[1].split("</code>")[0]


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


def test_a_family_without_a_secret_has_no_codes(anna):
    connection = db.connect()
    connection.execute("UPDATE families SET secret = NULL")
    connection.commit()
    assert "Extra time codes" not in anna.get("/").text
    assert "Elias" not in anna.get("/codes").text
    answer = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": 30})
    assert answer.status_code == 404


def test_a_preset_button_sets_the_minutes(anna, tmp_path):
    # the browser sends the pressed preset and the number field, in that order
    page = anna.post("/codes", data={"child_id": 3, "kind": "time", "minutes": ["15", "60"]}).text
    result = accepted_by_the_monitor(code_on(page), "Elias", tmp_path)
    assert result["extra_time_sec"] == 900
