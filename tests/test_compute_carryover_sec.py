import datetime
import json

import monitor

MON = datetime.date(2026, 9, 14)  # today in every test below
SUN = MON - datetime.timedelta(days=1)
SAT = MON - datetime.timedelta(days=2)
FRI = MON - datetime.timedelta(days=3)
HOUR = 60 * 60


def settings(**overrides):
    """The settings the function reads, pinned here so that a changed default in
    settings.py cannot move the numbers below."""
    return {
        "DAILY_LIMIT_SECONDS": HOUR,
        "MAX_CARRYOVER_SECONDS": 5 * HOUR,
        "DAILY_LIMIT_OVERRIDES": {},
        **overrides,
    }


def write_day(tmp_path, date, spent=0, carryover=0, granted=0):
    data = {"time_spent_sec": spent, "carryover_sec": carryover, "granted_sec": granted}
    (tmp_path / f"{date.isoformat()}.json").write_text(json.dumps(data), encoding="utf-8")


# `tmp_path` is a fixture built into pytest: a test that names it as a parameter
# receives a fresh, empty folder, unique to that test and cleaned up afterwards.
def test_no_previous_day_means_no_carryover(tmp_path):
    assert monitor.compute_carryover_sec(MON, settings(), tmp_path) == 0


def test_files_that_are_not_earlier_days_are_ignored(tmp_path):
    write_day(tmp_path, MON, spent=0)  # today itself
    write_day(tmp_path, MON + datetime.timedelta(days=1), spent=0)  # the clock once ran ahead
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    assert monitor.compute_carryover_sec(MON, settings(), tmp_path) == 0


def test_leftover_from_yesterday_is_carried(tmp_path):
    write_day(tmp_path, SUN, spent=1000)
    assert monitor.compute_carryover_sec(MON, settings(), tmp_path) == HOUR - 1000


def test_yesterdays_own_carryover_and_grants_count_toward_its_leftover(tmp_path):
    write_day(tmp_path, SUN, spent=3800, carryover=500, granted=200)
    assert monitor.compute_carryover_sec(MON, settings(), tmp_path) == HOUR + 500 + 200 - 3800


def test_overspent_yesterday_carries_nothing_not_a_debt(tmp_path):
    write_day(tmp_path, SUN, spent=HOUR + 300, granted=100)
    assert monitor.compute_carryover_sec(MON, settings(), tmp_path) == 0


def test_days_without_a_file_add_their_full_limit(tmp_path):
    write_day(tmp_path, FRI, spent=HOUR - 600)  # then Sat and Sun the machine was off
    assert monitor.compute_carryover_sec(MON, settings(), tmp_path) == 600 + HOUR + HOUR


def test_cap_limits_the_total_and_none_means_no_cap(tmp_path):
    write_day(tmp_path, FRI, spent=0)  # 3 full hours would carry over
    assert monitor.compute_carryover_sec(MON, settings(MAX_CARRYOVER_SECONDS=1000), tmp_path) == 1000
    assert monitor.compute_carryover_sec(MON, settings(MAX_CARRYOVER_SECONDS=None), tmp_path) == 3 * HOUR


def test_each_day_counts_with_its_own_weekday_limit(tmp_path):
    overrides = {"fri": 1800, "sat": 2 * HOUR}  # sun keeps the general 1 hour
    write_day(tmp_path, FRI, spent=300)
    result = monitor.compute_carryover_sec(
        MON, settings(DAILY_LIMIT_OVERRIDES=overrides, MAX_CARRYOVER_SECONDS=None), tmp_path
    )
    assert result == (1800 - 300) + 2 * HOUR + HOUR


def test_a_long_absence_adds_every_skipped_day_and_the_cap_keeps_it_sane(tmp_path):
    last_seen = MON - datetime.timedelta(days=100)  # 99 whole days without a file
    write_day(tmp_path, last_seen, spent=HOUR - 60)
    uncapped = monitor.compute_carryover_sec(MON, settings(MAX_CARRYOVER_SECONDS=None), tmp_path)
    assert uncapped == 60 + 99 * HOUR
    assert monitor.compute_carryover_sec(MON, settings(), tmp_path) == 5 * HOUR
