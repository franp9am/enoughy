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
