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
