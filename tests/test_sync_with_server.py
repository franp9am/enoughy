"""What one sync does to the day's data, the settings in force and the files
between syncs. The wire is covered in test_remote_sync; here send_status is
replaced by the `sync` fake from conftest, which hands back a ready
SyncAnswer or raises."""
import datetime
import json

import pytest

import monitor
import os_tooling
import remote_sync
from remote_sync import Grant, SettingsChange, SyncAnswer
from settings import default_settings, write_settings_file

NOW = datetime.datetime(2026, 9, 14, 8, 0, 0)  # Monday morning
HOUR = 60 * 60
KID = "kid"


@pytest.fixture
def files(tmp_path, monkeypatch):
    """Every file a sync reads or writes, redirected into tmp_path. The server
    url and token are present, so a sync goes ahead unless a test removes them."""
    monkeypatch.setattr(monitor, "DATA_DIR", tmp_path)
    data_dir = tmp_path / KID
    data_dir.mkdir()
    paths = {
        "server_url": data_dir / "server_url.txt",
        "token": data_dir / "child_token.txt",
        "applied_grants": data_dir / "applied_grants.json",
        "outcome": data_dir / "settings_change_outcome.json",
        "settings": data_dir / "settings.json",
        "datafile": data_dir / "2026-09-14.json",
    }
    paths["server_url"].write_text("https://screentime.example.com\n", encoding="utf-8")
    paths["token"].write_text("child-token-123\n", encoding="utf-8")
    return paths


@pytest.fixture
def notifications(monkeypatch):
    """Messages the child would have seen on screen."""
    shown = []
    monkeypatch.setattr(os_tooling, "notify", lambda message, user: shown.append((message, user)))
    return shown


def day_data(spent=1200, carryover=300, granted=0):
    data = monitor.load_data("never-there.json")  # the defaults
    data.update(time_spent_sec=spent, carryover_sec=carryover, granted_sec=granted)
    data["last_tick"] = "2026-09-14 07:59:00"
    return data


def settings(**overrides):
    return {**default_settings(), **overrides}


def run(files, data=None, in_force=None):
    """One sync, as the monitor calls it; returns (settings to carry on with, data)."""
    data = day_data() if data is None else data
    in_force = settings() if in_force is None else in_force
    new_settings = monitor.sync_with_server(data, files["datafile"], NOW, in_force, KID)
    return new_settings, data


def saved(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- when no sync happens --------------------------------------------------


def test_without_a_server_url_nothing_is_sent_and_settings_are_returned_as_is(files, sync):
    files["server_url"].unlink()
    in_force = settings(DAILY_LIMIT_SECONDS=2 * HOUR)
    new_settings, data = run(files, in_force=in_force)
    assert new_settings == in_force
    assert sync.calls == 0
    assert not files["datafile"].exists()


def test_without_a_token_nothing_is_sent_either(files, sync):
    files["token"].write_text("", encoding="utf-8")
    run(files)
    assert sync.calls == 0


def test_a_server_that_fails_leaves_everything_as_it_was(files, sync, notifications):
    sync.error = ConnectionError("down")
    remote_sync.save_applied_grant_ids([4], files["applied_grants"])
    in_force = settings(DAILY_LIMIT_SECONDS=2 * HOUR)
    before = day_data()

    new_settings, data = run(files, data=day_data(), in_force=in_force)

    assert new_settings == in_force
    assert data == before
    assert notifications == []
    assert not files["datafile"].exists()
    assert not files["outcome"].exists()
    # the unacknowledged grant is kept for the next attempt
    assert remote_sync.load_applied_grant_ids(files["applied_grants"]) == [4]


# --- what is sent ----------------------------------------------------------


def test_the_report_is_todays_numbers_with_the_settings_in_force(files, sync):
    in_force = settings(DAILY_LIMIT_SECONDS=2 * HOUR)
    run(files, data=day_data(spent=1200, carryover=300, granted=600), in_force=in_force)
    status = sync.status
    assert sync.server_url == "https://screentime.example.com"
    assert sync.token == "child-token-123"
    assert status.date == "2026-09-14"
    assert status.time_spent_sec == 1200
    assert status.carryover_sec == 300
    assert status.granted_sec == 600
    assert status.remaining_sec == 2 * HOUR + 300 + 600 - 1200
    assert status.last_tick == "2026-09-14 07:59:00"
    assert status.settings == in_force


def test_grants_applied_last_time_are_acknowledged_now(files, sync):
    remote_sync.save_applied_grant_ids([4, 7], files["applied_grants"])
    run(files)
    assert sync.applied_grant_ids == [4, 7]


def test_the_outcome_of_the_last_settings_change_is_reported(files, sync):
    remote_sync.save_settings_change_outcome(12, False, files["outcome"])
    run(files)
    assert sync.status.settings_change_outcome == {"id": 12, "taken": False}


def test_with_nothing_pending_no_file_is_written(files, sync):
    run(files)
    assert not files["datafile"].exists()
    assert not files["applied_grants"].exists()
    assert not files["outcome"].exists()


# --- grants ----------------------------------------------------------------


def test_a_grant_adds_time_tells_the_child_and_is_saved(files, sync, notifications):
    sync.answer = SyncAnswer(pending_grants=[Grant(id=4, seconds=600)], settings_change=None)

    _, data = run(files, data=day_data(granted=0))

    assert data["granted_sec"] == 600
    assert data["event_log"] == ["server grant 600 sec id 4 2026-09-14 08:00:00"]
    assert notifications == [("extra time 600", KID)]
    assert saved(files["datafile"])["granted_sec"] == 600
    # remembered so the next sync acknowledges it and the server stops sending it
    assert remote_sync.load_applied_grant_ids(files["applied_grants"]) == [4]


def test_several_grants_are_all_applied(files, sync, notifications):
    sync.answer = SyncAnswer(
        pending_grants=[Grant(id=4, seconds=600), Grant(id=5, seconds=900)],
        settings_change=None,
    )
    _, data = run(files, data=day_data(granted=100))
    assert data["granted_sec"] == 100 + 600 + 900
    assert len(notifications) == 2
    assert remote_sync.load_applied_grant_ids(files["applied_grants"]) == [4, 5]


def test_once_the_server_has_heard_the_ids_they_are_dropped(files, sync):
    remote_sync.save_applied_grant_ids([4], files["applied_grants"])
    run(files)  # server answers with nothing pending: it has taken note of 4
    assert remote_sync.load_applied_grant_ids(files["applied_grants"]) == []


def test_a_grant_repeated_by_the_server_is_applied_again(files, sync):
    # The server keeps sending a grant until it hears the id back. If the
    # previous sync applied it but crashed before recording the id, the
    # monitor applies it once more rather than risk losing it.
    sync.answer = SyncAnswer(pending_grants=[Grant(id=4, seconds=600)], settings_change=None)
    _, data = run(files, data=day_data(granted=600))
    assert data["granted_sec"] == 1200
    assert remote_sync.load_applied_grant_ids(files["applied_grants"]) == [4]


# --- settings --------------------------------------------------------------


def test_an_acceptable_settings_change_is_taken_and_written(files, sync):
    wanted = settings(DAILY_LIMIT_SECONDS=30 * 60, CARRYOVER=False)
    sync.answer = SyncAnswer(pending_grants=[], settings_change=SettingsChange(id=12, settings=wanted))

    new_settings, data = run(files, in_force=settings())

    assert new_settings == wanted
    assert saved(files["settings"]) == wanted
    assert saved(files["outcome"]) == {"id": 12, "taken": True}
    assert data["event_log"] == [f"server settings taken {wanted} 2026-09-14 08:00:00"]
    assert saved(files["datafile"])["event_log"] == data["event_log"]


def test_an_unacceptable_settings_change_is_refused_and_reported(files, sync):
    in_force = settings(DAILY_LIMIT_SECONDS=2 * HOUR)
    write_settings_file(in_force, files["settings"])
    wanted = settings(ALLOWED_HOURS=["6:00", "25:00"])  # no such hour
    sync.answer = SyncAnswer(pending_grants=[], settings_change=SettingsChange(id=13, settings=wanted))

    new_settings, data = run(files, in_force=in_force)

    assert new_settings == in_force
    assert saved(files["settings"]) == in_force
    assert saved(files["outcome"]) == {"id": 13, "taken": False}
    assert data["event_log"] == [f"server settings refused {wanted} 2026-09-14 08:00:00"]


def test_a_partial_change_is_filled_from_the_file_and_counts_as_taken(files, sync):
    # only when the monitor gained a setting while the change was in flight;
    # "taken" is judged on the settings the change does name
    in_force = settings(DAILY_LIMIT_SECONDS=2 * HOUR)
    write_settings_file(in_force, files["settings"])
    sync.answer = SyncAnswer(
        pending_grants=[], settings_change=SettingsChange(id=14, settings={"CARRYOVER": False})
    )

    new_settings, _ = run(files, in_force=in_force)

    assert new_settings == {**in_force, "CARRYOVER": False}
    assert saved(files["outcome"]) == {"id": 14, "taken": True}


def test_a_grant_and_a_settings_change_in_one_answer_are_both_applied(files, sync, notifications):
    wanted = settings(CARRYOVER=False)
    sync.answer = SyncAnswer(
        pending_grants=[Grant(id=4, seconds=600)],
        settings_change=SettingsChange(id=12, settings=wanted),
    )
    new_settings, data = run(files)
    assert new_settings == wanted
    assert data["granted_sec"] == 600
    assert notifications == [("extra time 600", KID)]
    on_disk = saved(files["datafile"])
    assert on_disk["granted_sec"] == 600
    assert len(on_disk["event_log"]) == 2
