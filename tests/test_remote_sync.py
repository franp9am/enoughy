"""The client side of the sync protocol: what goes to the server, what is
made of the answer, and the small files that carry state between syncs."""
import io
import json
import urllib.error

import pytest

import remote_sync
from config import MONITOR_VERSION, SYNC_TIMEOUT_SECONDS

SERVER_URL = "https://screentime.example.com"
TOKEN = "child-token-123"
SETTINGS = {"DAILY_LIMIT_SECONDS": 3600, "CARRYOVER": True}


def status(**overrides):
    fields = {
        "date": "2026-09-14",
        "time_spent_sec": 1200,
        "carryover_sec": 300,
        "granted_sec": 0,
        "remaining_sec": 2700,
        "last_tick": "2026-09-14 08:00:00",
        "settings": SETTINGS,
        "settings_change_outcome": None,
    }
    return remote_sync.DailyStatus(**{**fields, **overrides})


class FakeServer:
    """Stands in for urlopen. A test sets `reply` (what the server answers) or
    `error` (what the connection raises) before sending, and afterwards reads
    `request` (what the monitor sent) and `timeout`."""

    def __init__(self):
        self.reply = {"pending_grants": [], "settings_change": None}
        self.error = None
        self.request = None
        self.timeout = None

    def urlopen(self, request, timeout=None):
        """Called by send_status in place of the real urlopen."""
        self.request = request
        self.timeout = timeout
        if self.error is not None:
            raise self.error
        return io.BytesIO(json.dumps(self.reply).encode("utf-8"))


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(remote_sync.urllib.request, "urlopen", fake.urlopen)
    return fake


def send(server, applied_grant_ids=(), **status_overrides):
    return remote_sync.send_status(
        status(**status_overrides), list(applied_grant_ids), SERVER_URL, TOKEN
    )


def sent_payload(server) -> dict:
    return json.loads(server.request.data.decode("utf-8"))


# --- the request -----------------------------------------------------------


def test_the_request_is_a_json_post_to_the_sync_endpoint(server):
    send(server)
    request = server.request
    assert request.full_url == SERVER_URL + "/api/sync"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert isinstance(json.loads(request.data), dict)  # the body is what the header says
    assert server.timeout == SYNC_TIMEOUT_SECONDS


def test_the_body_carries_every_field_of_the_status(server):
    send(server)
    sent = sent_payload(server)
    assert sent["date"] == "2026-09-14"
    assert sent["time_spent_sec"] == 1200
    assert sent["carryover_sec"] == 300
    assert sent["granted_sec"] == 0
    assert sent["remaining_sec"] == 2700
    assert sent["last_tick"] == "2026-09-14 08:00:00"
    assert sent["settings"] == SETTINGS
    assert sent["settings_change_outcome"] is None


def test_the_child_token_goes_in_the_bearer_header_not_the_body(server):
    send(server)
    assert server.request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert TOKEN not in server.request.data.decode("utf-8")


def test_applied_grant_ids_and_the_monitor_version_ride_along(server):
    send(server, applied_grant_ids=[7, 3])
    sent = sent_payload(server)
    assert sent["applied_grant_ids"] == [7, 3]
    assert sent["monitor_version"] == MONITOR_VERSION


def test_the_outcome_of_the_last_settings_change_is_reported(server):
    send(server, settings_change_outcome={"id": 5, "taken": False})
    assert sent_payload(server)["settings_change_outcome"] == {"id": 5, "taken": False}


# --- the answer ------------------------------------------------------------


def test_no_grants_and_no_change(server):
    answer = send(server)
    assert answer.pending_grants == []
    assert answer.settings_change is None


def test_grants_parse_to_ints_in_order(server):
    server.reply = {
        "pending_grants": [{"id": "4", "seconds": "600"}, {"id": 9, "seconds": 1800}],
        "settings_change": None,
    }
    answer = send(server)
    assert answer.pending_grants == [
        remote_sync.Grant(id=4, seconds=600),
        remote_sync.Grant(id=9, seconds=1800),
    ]


def test_a_settings_change_is_taken_as_sent(server):
    server.reply = {
        "pending_grants": [],
        "settings_change": {"id": "12", "settings": {"DAILY_LIMIT_SECONDS": 1800}},
    }
    answer = send(server)
    assert answer.settings_change == remote_sync.SettingsChange(
        id=12, settings={"DAILY_LIMIT_SECONDS": 1800}
    )


def test_a_missing_or_odd_settings_change_is_none(server):
    server.reply = {"pending_grants": []}  # an older server that knows no settings
    assert send(server).settings_change is None
    server.reply = {"pending_grants": [], "settings_change": "soon"}
    assert send(server).settings_change is None


def test_a_server_that_fails_raises_to_the_caller(server):
    server.error = urllib.error.URLError("connection refused")
    with pytest.raises(Exception):
        send(server)


def test_an_answer_that_is_not_the_protocol_raises_to_the_caller(server):
    server.reply = {"grants": []}  # no pending_grants at all
    with pytest.raises(Exception):
        send(server)
    server.reply = {"pending_grants": [{"id": "four", "seconds": 600}]}
    with pytest.raises(Exception):
        send(server)


# --- the files written by the setup ----------------------------------------


def test_the_server_url_is_read_without_whitespace_or_trailing_slash(tmp_path):
    f = tmp_path / "server_url.txt"
    f.write_text("https://screentime.example.com/\r\n", encoding="utf-8")
    assert remote_sync.load_server_url(f) == "https://screentime.example.com"


def test_no_server_url_means_offline(tmp_path):
    f = tmp_path / "server_url.txt"
    assert remote_sync.load_server_url(f) == ""
    f.write_text(" \n", encoding="utf-8")
    assert remote_sync.load_server_url(f) == ""


def test_the_child_token_is_read_stripped_and_empty_when_missing(tmp_path):
    f = tmp_path / "child_token.txt"
    assert remote_sync.load_child_token(f) == ""
    f.write_text("  abc123\n", encoding="utf-8")
    assert remote_sync.load_child_token(f) == "abc123"


# --- state carried between syncs -------------------------------------------


def test_applied_grant_ids_survive_a_round_trip_sorted(tmp_path):
    f = tmp_path / "applied_grants.json"
    remote_sync.save_applied_grant_ids([9, 4, 7], f)
    assert remote_sync.load_applied_grant_ids(f) == [4, 7, 9]
    assert not f.with_suffix(".tmp").exists()


def test_saving_no_grant_ids_clears_the_file(tmp_path):
    f = tmp_path / "applied_grants.json"
    remote_sync.save_applied_grant_ids([4], f)
    remote_sync.save_applied_grant_ids([], f)
    assert remote_sync.load_applied_grant_ids(f) == []


def test_unusable_applied_grant_ids_are_none_at_all(tmp_path):
    f = tmp_path / "applied_grants.json"
    assert remote_sync.load_applied_grant_ids(f) == []  # never written
    f.write_text("{not json", encoding="utf-8")
    assert remote_sync.load_applied_grant_ids(f) == []
    f.write_text('[1, "two"]', encoding="utf-8")
    assert remote_sync.load_applied_grant_ids(f) == []


def test_the_settings_change_outcome_survives_a_round_trip(tmp_path):
    f = tmp_path / "settings_change_outcome.json"
    remote_sync.save_settings_change_outcome(12, False, f)
    assert remote_sync.load_settings_change_outcome(f) == {"id": 12, "taken": False}
    remote_sync.save_settings_change_outcome(13, True, f)
    assert remote_sync.load_settings_change_outcome(f) == {"id": 13, "taken": True}
    assert not f.with_suffix(".tmp").exists()


def test_a_missing_or_odd_outcome_file_is_no_outcome(tmp_path):
    f = tmp_path / "settings_change_outcome.json"
    assert remote_sync.load_settings_change_outcome(f) is None
    f.write_text("[12, true]", encoding="utf-8")
    assert remote_sync.load_settings_change_outcome(f) is None
    f.write_text("", encoding="utf-8")
    assert remote_sync.load_settings_change_outcome(f) is None
