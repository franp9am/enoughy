"""The monitor on the child's machine reports in with the child's token."""
import db

REPORT = {
    "date": "2026-10-12", "time_spent_sec": 600, "carryover_sec": 0, "granted_sec": 0,
    "remaining_sec": 3000, "last_tick": None, "applied_grant_ids": [],
}


def test_a_child_with_a_token_syncs_and_appears_on_the_dashboard(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    token = db.connect().execute("SELECT token FROM children").fetchone()["token"]
    answer = anna_logged_in.post(
        "/api/sync", json=REPORT, headers={"Authorization": f"Bearer {token}"}
    )
    assert answer.status_code == 200
    assert answer.json()["pending_grants"] == []
    assert "Tom" in anna_logged_in.get("/").text


def test_an_unknown_token_is_refused(client):
    answer = client.post("/api/sync", json=REPORT, headers={"Authorization": "Bearer nope"})
    assert answer.status_code == 401


def test_each_event_sent_is_a_line_in_the_journal(anna_logged_in, caplog):
    anna_logged_in.post("/children", data={"name": "Tom"})
    child = db.connect().execute("SELECT id, token FROM children").fetchone()
    events = ["redeem code 600 2026-10-12 08:00:00", "shutdown night 2026-10-12 21:00:00"]
    with caplog.at_level("INFO"):
        answer = anna_logged_in.post(
            "/api/sync", json={**REPORT, "event_log": events},
            headers={"Authorization": f"Bearer {child['token']}"},
        )
    assert answer.status_code == 200
    lines = [record.getMessage() for record in caplog.records if record.name == "app"]
    assert lines[-2:] == [f"child {child['id']} event: {entry}" for entry in events]


import pytest


@pytest.fixture
def report(anna_logged_in):
    """Tom's monitor reports, with what the test changes in the report."""
    anna_logged_in.post("/children", data={"name": "Tom"})
    token = db.connect().execute("SELECT token FROM children").fetchone()["token"]
    def post(**changed):
        return anna_logged_in.post(
            "/api/sync", json={**REPORT, **changed}, headers={"Authorization": f"Bearer {token}"}
        )
    return post


def days_kept():
    return [row["date"] for row in db.connect().execute("SELECT date FROM status ORDER BY date")]


def test_a_date_two_days_from_the_servers_is_taken_and_a_third_is_not(report):
    """The tests' server lives on 2026-10-12."""
    assert report(date="2026-10-10").status_code == 200
    assert report(date="2026-10-14").status_code == 200
    assert report(date="2026-10-09").status_code == 422
    assert report(date="2026-10-15").status_code == 422
    assert days_kept() == ["2026-10-10", "2026-10-14"]


@pytest.mark.parametrize("day", ["christmas", "", "2026-10-12 and more", "2026-13-01"])
def test_what_is_not_a_date_is_refused(report, day):
    assert report(date=day).status_code == 422
    assert days_kept() == []


def test_a_day_spelled_another_way_is_the_same_row(report):
    assert report(date="2026-10-12").status_code == 200
    assert report(date="20261012").status_code == 200
    assert days_kept() == ["2026-10-12"]


def test_settings_longer_than_a_monitors_are_refused(report):
    assert report(settings={"DAILY_LIMIT_SECONDS": 3600}).status_code == 200
    assert report(settings={"padding": "x" * 5000}).status_code == 422


@pytest.mark.parametrize("changed", [
    {"time_spent_sec": 10**30}, {"remaining_sec": -10**30},
    {"last_tick": "x" * 41}, {"monitor_version": "x" * 41},
    {"applied_grant_ids": [2**63]}, {"applied_grant_ids": list(range(10_001))},
])
def test_a_number_or_a_text_past_its_end_is_refused(report, changed):
    assert report(**changed).status_code == 422
    assert days_kept() == []


def events_printed(caplog):
    return [record.getMessage() for record in caplog.records if record.name == "app" and " event" in record.getMessage()]


def test_a_long_event_log_is_taken_whole_and_printed_in_part(report, caplog):
    """Taken, or the monitor would send it again for ever; in part, or printing it would be the server's whole day."""
    with caplog.at_level("INFO"):
        assert report(event_log=[f"event {number}" for number in range(1500)]).status_code == 200
    lines = events_printed(caplog)
    assert len(lines) == 1001
    assert lines[999] == "child 1 event: event 999"
    assert lines[1000] == "child 1 sent 500 more events, not printed"


def test_a_long_entry_is_cut_and_its_line_breaks_are_marked(report, caplog):
    with caplog.at_level("INFO"):
        report(event_log=["crash\nINFO app: parent 5 logged in", "x" * 5000])
    forged, long = events_printed(caplog)
    assert forged == "child 1 event: crash\n    | INFO app: parent 5 logged in"
    assert long == "child 1 event: " + "x" * 4000
