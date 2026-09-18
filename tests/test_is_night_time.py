import datetime

import monitor

SETTINGS = {"ALLOWED_HOURS": [6, 21], "ALLOWED_HOURS_OVERRIDES": {"fri": [8, 23]}}
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
    settings = {"ALLOWED_HOURS": [0, 24], "ALLOWED_HOURS_OVERRIDES": {}}
    assert not monitor.is_night_time(at(0, 0), settings)
    assert not monitor.is_night_time(at(23, 59), settings)
