import datetime

import monitor

SETTINGS = {"ALLOWED_HOURS": ["6:00", "21:00"], "ALLOWED_HOURS_OVERRIDES": {"fri": ["8:00", "23:00"]}}
MON = datetime.date(2026, 9, 14)
FRI = datetime.date(2026, 9, 18)


def at(hour, minute=0, date=MON):
    return datetime.datetime(date.year, date.month, date.day, hour, minute)


def test_the_whole_first_hour_is_day():
    assert not monitor.is_night_time(at(6, 0), SETTINGS)
    assert not monitor.is_night_time(at(6, 59), SETTINGS)


def test_the_window_ends_when_until_begins():
    assert not monitor.is_night_time(at(20, 59), SETTINGS)
    assert monitor.is_night_time(at(21, 0), SETTINGS)


def test_just_before_the_window_is_night():
    assert monitor.is_night_time(at(5, 59), SETTINGS)


def test_midnight_is_night():
    assert monitor.is_night_time(at(0, 0), SETTINGS)


def test_a_weekday_with_its_own_window_uses_it():
    assert monitor.is_night_time(at(7, 59, FRI), SETTINGS)
    assert not monitor.is_night_time(at(22, 59, FRI), SETTINGS)
    assert monitor.is_night_time(at(23, 0, FRI), SETTINGS)


def test_a_window_to_24_lasts_until_midnight():
    settings = {"ALLOWED_HOURS": ["0:00", "24:00"], "ALLOWED_HOURS_OVERRIDES": {}}
    assert not monitor.is_night_time(at(0, 0), settings)
    assert not monitor.is_night_time(at(23, 59), settings)


def test_the_window_can_begin_and_end_mid_hour():
    settings = {"ALLOWED_HOURS": ["6:30", "20:10"], "ALLOWED_HOURS_OVERRIDES": {}}
    assert monitor.is_night_time(at(6, 29), settings)
    assert not monitor.is_night_time(at(6, 30), settings)
    assert not monitor.is_night_time(at(20, 9), settings)
    assert monitor.is_night_time(at(20, 10), settings)


def test_null_is_no_night():
    settings = {"ALLOWED_HOURS": None, "ALLOWED_HOURS_OVERRIDES": {"fri": ["8:00", "23:00"]}}
    assert not monitor.is_night_time(at(0, 0), settings)
    assert not monitor.is_night_time(at(23, 59), settings)
    assert monitor.is_night_time(at(23, 0, FRI), settings)  # Friday keeps its own window
    settings = {"ALLOWED_HOURS": ["6:00", "21:00"], "ALLOWED_HOURS_OVERRIDES": {"fri": None}}
    assert monitor.is_night_time(at(23, 0), settings)
    assert not monitor.is_night_time(at(23, 0, FRI), settings)
