"""What startup and one tick do on the child's machine, told as short
scenarios with a clock. The machine itself (who is logged in, the message
on screen, the shutdown) is recorded instead of done, and every file the
monitor touches lives in a temp dir. Offline unless a test goes online."""
import datetime
import hashlib
import hmac
import random

import pytest

import monitor
import os_tooling
import remote_sync
from config import (
    CHECK_INTERVAL_SECONDS,
    NIGHT_SHUTDOWN_DELAY_SECONDS,
    SHUTDOWN_DELAY_SECONDS,
    SIGNATURE_CHARS,
)
from remote_sync import Grant, SettingsChange, SyncAnswer
from settings import settings_in_force, write_settings_file

HOUR = 60 * 60
NIGHT_HOUR = 21  # the first hour outside the allowed window below
SETTINGS = {  # what the settings file holds in every scenario, whatever the defaults are
    "DAILY_LIMIT_SECONDS": HOUR,
    "CARRYOVER": True,
    "MAX_CARRYOVER_SECONDS": 5 * HOUR,
    "EARLIEST_HOUR_INCLUDED": 6,
    "LATEST_HOUR_INCLUDED": NIGHT_HOUR - 1,
    "DAILY_LIMIT_OVERRIDES": {},
}
KID = "kid"
SECRET = b"\x01\x02\x03\x04"
TODAY = datetime.date(2026, 9, 14)  # Monday
TOMORROW = TODAY + datetime.timedelta(days=1)


def at(hour, minute=0, date=TODAY):
    return datetime.datetime(date.year, date.month, date.day, hour, minute, 0)


class Machine:
    """The child's PC as the monitor sees it and acts on it."""

    def __init__(self):
        self.logged_in = True
        self.notifications = []  # what the child saw on screen
        self.shutdowns = []  # the delay of every shutdown ordered


@pytest.fixture
def machine(monkeypatch):
    m = Machine()
    monkeypatch.setattr(os_tooling, "user_logged_in", lambda user: m.logged_in)
    monkeypatch.setattr(os_tooling, "notify", lambda message, user: m.notifications.append(message))
    monkeypatch.setattr(os_tooling, "shutdown", lambda delay: m.shutdowns.append(delay))
    return m


@pytest.fixture
def files(tmp_path, monkeypatch):
    """Every file the monitor touches, redirected into tmp_path, with SETTINGS
    in force. No server url is written, so the monitor is offline until a test
    calls write_server_files()."""
    monkeypatch.setattr(monitor, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(monitor, "SHARED_DIR", tmp_path / "shared")
    data_dir = tmp_path / "data" / KID  # as the installer leaves them
    shared = tmp_path / "shared" / KID
    data_dir.mkdir(parents=True)
    shared.mkdir(parents=True)
    paths = {
        "data_dir": data_dir,
        "today": data_dir / f"{TODAY.isoformat()}.json",
        "redeem": shared / "extra_time.txt",
        "remaining": shared / "remaining_time.txt",
        "used_codes": data_dir / "used_redeem_codes.txt",
        "settings": data_dir / "settings.json",
        "server_url": data_dir / "server_url.txt",
        "token": data_dir / "child_token.txt",
        "applied_grants": data_dir / "applied_grants.json",
        "outcome": data_dir / "settings_change_outcome.json",
    }
    write_settings_file(SETTINGS, paths["settings"])
    return paths


def write_server_files(files):
    files["server_url"].write_text("https://screentime.example.com\n", encoding="utf-8")
    files["token"].write_text("child-token-123\n", encoding="utf-8")


def write_day(files, date=TODAY, spent=0, granted=0, last_tick=None):
    data = monitor.load_data("never-there.json")  # the defaults
    data.update(time_spent_sec=spent, granted_sec=granted, last_tick=last_tick)
    monitor.save_data(data, files["data_dir"] / f"{date.isoformat()}.json")


def day_data(files, date) -> dict:
    return monitor.load_data(files["data_dir"] / f"{date.isoformat()}.json")


def today_data(files) -> dict:
    return day_data(files, TODAY)


def remaining_shown(files) -> int:
    """What the widget would display."""
    return int(files["remaining"].read_text(encoding="utf-8"))


def redeem_code(seconds, date="2026-09-14") -> str:
    payload = f"{date}:{seconds}"
    sign = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:SIGNATURE_CHARS]
    return f"{payload}:{sign}"


def tick(now):
    monitor.tick(now, KID, SECRET)


# --- ticks -----------------------------------------------------------------


def test_a_tick_charges_the_minute_since_the_last_one(machine, files):
    write_day(files, spent=600, last_tick="2026-09-14 07:59:00")

    tick(at(8, 0))

    data = today_data(files)
    assert data["time_spent_sec"] == 660
    assert data["last_tick"] == "2026-09-14 08:00:00"
    assert data["ticks"] == ["08:00:00"]
    assert remaining_shown(files) == HOUR - 660
    assert machine.shutdowns == []
    assert machine.notifications == []


def test_the_first_tick_of_a_day_creates_the_file_and_charges_one_interval(machine, files):
    tick(at(8, 0))
    assert today_data(files)["time_spent_sec"] == CHECK_INTERVAL_SECONDS
    assert remaining_shown(files) == HOUR - CHECK_INTERVAL_SECONDS


def test_time_up_orders_the_shutdown(machine, files):
    write_day(files, spent=HOUR)

    tick(at(8, 0))

    assert machine.shutdowns == [SHUTDOWN_DELAY_SECONDS]
    assert machine.notifications == ["time up"]
    assert remaining_shown(files) == 0
    data = today_data(files)
    assert data["time_spent_sec"] == HOUR  # nothing more is charged
    assert data["event_log"] == ["time up 2026-09-14 08:00:00"]


def test_night_time_orders_the_shutdown(machine, files):
    write_day(files, spent=600)

    tick(at(NIGHT_HOUR))

    assert machine.shutdowns == [NIGHT_SHUTDOWN_DELAY_SECONDS]
    assert machine.notifications == ["Night time"]
    assert remaining_shown(files) == 0
    assert today_data(files)["time_spent_sec"] == 600


def test_the_child_is_warned_five_minutes_before_night_once(machine, files):
    tick(at(20, 54))  # NIGHT_HOUR is 21
    assert machine.notifications == []

    tick(at(20, 55))
    tick(at(20, 56))

    assert machine.notifications == ["5 minutes to night"]
    assert today_data(files)["event_log"] == ["5 minutes to night 2026-09-14 20:55:00"]
    assert machine.shutdowns == []


def test_no_warning_when_night_never_comes(machine, files):
    write_settings_file(
        {**SETTINGS, "EARLIEST_HOUR_INCLUDED": 0, "LATEST_HOUR_INCLUDED": 23}, files["settings"]
    )
    tick(at(23, 55))
    assert machine.notifications == []


def test_the_warning_looks_across_midnight(machine, files):
    write_settings_file({**SETTINGS, "LATEST_HOUR_INCLUDED": 23}, files["settings"])
    tick(at(23, 55))
    assert machine.notifications == ["5 minutes to night"]


def test_a_logged_out_child_is_charged_nothing(machine, files):
    machine.logged_in = False
    write_day(files, spent=600)

    tick(at(8, 0))

    assert today_data(files)["time_spent_sec"] == 600
    assert remaining_shown(files) == HOUR - 600  # still published, so the widget does not go blank


def test_a_logged_out_child_is_not_shut_down_at_night(machine, files):
    machine.logged_in = False

    tick(at(NIGHT_HOUR))

    assert machine.shutdowns == []
    assert machine.notifications == []


def test_a_redeem_code_adds_its_time_once(machine, files):
    files["redeem"].write_text(redeem_code(600), encoding="utf-8")
    write_day(files, spent=600)

    tick(at(8, 0))
    tick(at(8, 1))  # the code is still in the file

    data = today_data(files)
    assert data["granted_sec"] == 600
    assert machine.notifications == ["extra time 600"]
    assert data["event_log"] == ["redeem code 600 2026-09-14 08:00:00"]
    assert redeem_code(600) in files["used_codes"].read_text(encoding="utf-8")


def test_a_redeem_code_saves_a_machine_whose_time_is_up(machine, files):
    files["redeem"].write_text(redeem_code(600), encoding="utf-8")
    write_day(files, spent=HOUR)

    tick(at(8, 0))

    assert machine.shutdowns == []
    assert today_data(files)["time_spent_sec"] == HOUR + CHECK_INTERVAL_SECONDS


def test_fractions_of_a_second_are_carried_to_the_next_tick_not_lost(machine, files):
    # Every stamp is whole seconds, but each tick stores the truncated wall
    # clock and charges the difference to the previous stamp, so the charges
    # telescope: the day's total is the truncated real span, not ticks x 60.
    # 50 ticks stay inside the hour; the gaps are 60 s plus random milliseconds
    gaps = random.Random(1).choices(range(0, 1000), k=50)
    now = at(8, 0)
    tick(now)
    for gap in gaps:
        now += datetime.timedelta(seconds=60, milliseconds=gap)
        tick(now)

    real_span = int((now - at(8, 0)).total_seconds())
    assert real_span > 50 * 60  # the fractions add up to something
    assert today_data(files)["time_spent_sec"] == CHECK_INTERVAL_SECONDS + real_span


# --- startup ---------------------------------------------------------------


def test_startup_creates_today_with_yesterdays_leftover(machine, files):
    write_day(files, date=TODAY - datetime.timedelta(days=1), spent=HOUR // 2)

    monitor.startup(at(7, 30), KID)

    data = today_data(files)
    assert data["carryover_sec"] == HOUR // 2
    assert data["time_spent_sec"] == 0
    assert remaining_shown(files) == HOUR + HOUR // 2
    assert data["event_log"] == ["carryover 1800 sec from previous day 2026-09-14 07:30:00"]


def test_startup_publishes_a_number_even_when_the_child_is_not_there(machine, files):
    machine.logged_in = False
    write_day(files, spent=600)
    monitor.startup(at(7, 30), KID)
    assert remaining_shown(files) == HOUR - 600


def test_a_machine_left_on_overnight_opens_the_new_day_at_midnight(machine, files):
    machine.logged_in = False
    write_day(files, spent=HOUR // 2, last_tick="2026-09-14 20:59:00")

    tick(at(0, date=TOMORROW))

    tomorrow = day_data(files, TOMORROW)
    assert tomorrow["carryover_sec"] == HOUR // 2
    assert tomorrow["time_spent_sec"] == 0
    assert tomorrow["last_tick"] is None  # yesterday's ticks do not spill over
    assert remaining_shown(files) == HOUR + HOUR // 2
    assert machine.shutdowns == []


def test_a_logged_in_child_starts_the_new_day_at_midnight(machine, files):
    write_settings_file(
        {**SETTINGS, "EARLIEST_HOUR_INCLUDED": 0, "LATEST_HOUR_INCLUDED": 23}, files["settings"]
    )
    write_day(files, spent=HOUR // 2, last_tick="2026-09-14 23:58:00")

    tick(at(23, 59))
    tick(at(0, date=TOMORROW))

    assert machine.shutdowns == []
    assert today_data(files)["time_spent_sec"] == HOUR // 2 + 60  # the 23:59 tick, charged to yesterday
    tomorrow = day_data(files, TOMORROW)
    assert tomorrow["carryover_sec"] == HOUR // 2 - 60
    assert tomorrow["time_spent_sec"] == CHECK_INTERVAL_SECONDS  # the first tick of a day is flat
    assert remaining_shown(files) == HOUR + tomorrow["carryover_sec"] - CHECK_INTERVAL_SECONDS


# --- with the server -------------------------------------------------------


def test_startup_applies_a_grant_waiting_on_the_server(machine, files, sync):
    write_server_files(files)
    write_day(files, spent=HOUR)  # yesterday evening the time was up
    sync.answer = SyncAnswer(pending_grants=[Grant(id=4, seconds=600)], settings_change=None)

    monitor.startup(at(8, 0), KID)
    tick(at(8, 1))  # reports the id, so the server does not send the grant again

    assert machine.shutdowns == []
    assert machine.notifications == ["extra time 600"]
    data = today_data(files)
    assert data["granted_sec"] == 600
    assert data["time_spent_sec"] == HOUR + CHECK_INTERVAL_SECONDS


def test_startup_reports_a_grant_applied_before_the_reboot(machine, files, sync):
    write_server_files(files)
    write_day(files, granted=600)  # the grant was applied ...
    remote_sync.save_applied_grant_ids([4], files["applied_grants"])  # ... but the server never heard

    monitor.startup(at(8, 0), KID)  # the server answers with nothing pending

    assert sync.applied_grant_ids == [4]
    assert today_data(files)["granted_sec"] == 600
    assert remote_sync.load_applied_grant_ids(files["applied_grants"]) == []


def test_a_grant_saves_a_machine_whose_time_is_up(machine, files, sync):
    write_server_files(files)
    write_day(files, spent=HOUR)
    sync.answer = SyncAnswer(pending_grants=[Grant(id=4, seconds=600)], settings_change=None)

    tick(at(8, 0))

    assert machine.shutdowns == []
    assert today_data(files)["time_spent_sec"] == HOUR + CHECK_INTERVAL_SECONDS


def test_a_negative_grant_from_the_server_orders_the_shutdown(machine, files, sync):
    write_server_files(files)
    write_day(files, spent=HOUR - 300)  # five minutes left
    sync.answer = SyncAnswer(pending_grants=[Grant(id=4, seconds=-600)], settings_change=None)

    tick(at(8, 0))

    assert machine.shutdowns == [SHUTDOWN_DELAY_SECONDS]
    assert machine.notifications == ["extra time -600", "time up"]
    assert today_data(files)["granted_sec"] == -600
    assert remaining_shown(files) == 0


def test_a_lower_limit_from_the_server_orders_the_shutdown(machine, files, sync):
    write_server_files(files)
    write_day(files, spent=HOUR // 2)
    sync.answer = SyncAnswer(
        pending_grants=[],
        settings_change=SettingsChange(id=7, settings={"DAILY_LIMIT_SECONDS": HOUR // 4}),
    )

    tick(at(8, 0))

    assert machine.shutdowns == [SHUTDOWN_DELAY_SECONDS]
    assert settings_in_force(files["settings"])["DAILY_LIMIT_SECONDS"] == HOUR // 4
    assert remaining_shown(files) == 0


def test_an_earlier_night_from_the_server_lags_one_tick(machine, files, sync):
    write_server_files(files)
    write_day(files, spent=HOUR // 2)
    sync.answer = SyncAnswer(
        pending_grants=[],
        settings_change=SettingsChange(id=8, settings={"LATEST_HOUR_INCLUDED": 17}),
    )

    tick(at(18, 30))  # night is checked before the sync, with the hours known so far
    assert machine.shutdowns == []
    assert settings_in_force(files["settings"])["LATEST_HOUR_INCLUDED"] == 17

    tick(at(18, 31))
    assert machine.shutdowns == [NIGHT_SHUTDOWN_DELAY_SECONDS]
    assert machine.notifications == ["5 minutes to night", "Night time"]  # the warning uses the new hours


def test_the_server_hears_of_a_shutdown_before_it_happens(machine, files, sync, monkeypatch):
    write_server_files(files)
    write_day(files, spent=HOUR)
    syncs_before_shutdown = []
    monkeypatch.setattr(os_tooling, "shutdown", lambda delay: syncs_before_shutdown.append(sync.calls))

    tick(at(8, 0))

    assert syncs_before_shutdown == [2]  # the regular one and the last word
    assert sync.status.remaining_sec == 0
