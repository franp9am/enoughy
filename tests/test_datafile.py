import datetime
import json

import monitor

NOW = datetime.datetime(2026, 9, 14, 8, 0, 0)  # Monday morning
HOUR = 60 * 60


def settings(**overrides):
    return {
        "DAILY_LIMIT_SECONDS": HOUR,
        "MAX_CARRYOVER_SECONDS": 5 * HOUR,
        "DAILY_LIMIT_OVERRIDES": {},
        **overrides,
    }


def write_past_day(tmp_path, spent, granted=0, days_ago=1):
    day = (NOW - datetime.timedelta(days=days_ago)).date()
    data = {"time_spent_sec": spent, "carryover_sec": 0, "granted_sec": granted}
    (tmp_path / f"{day.isoformat()}.json").write_text(json.dumps(data), encoding="utf-8")


def test_an_existing_file_is_loaded_and_left_alone(tmp_path):
    write_past_day(tmp_path, spent=0)  # would carry a full hour, if it were applied
    f = monitor.get_datafile(NOW, tmp_path)
    # today's file written by hand, as an earlier tick would have left it
    f.write_text(json.dumps({"time_spent_sec": 500, "carryover_sec": 0}), encoding="utf-8")
    before = f.read_text(encoding="utf-8")

    data = monitor.ensure_datafile(f, NOW, settings())

    assert data["time_spent_sec"] == 500
    assert data["carryover_sec"] == 0
    assert f.read_text(encoding="utf-8") == before


def test_a_new_day_gets_the_carryover_and_a_log_line(tmp_path):
    write_past_day(tmp_path, spent=HOUR - 900)
    f = monitor.get_datafile(NOW, tmp_path)

    data = monitor.ensure_datafile(f, NOW, settings())

    assert data["carryover_sec"] == 900
    assert data["event_log"] == ["carryover 900 sec from previous day 2026-09-14 08:00:00"]
    assert json.loads(f.read_text(encoding="utf-8")) == data  # written, not just returned


def test_a_cap_of_zero_is_no_carryover_and_starts_the_day_from_zero(tmp_path):
    write_past_day(tmp_path, spent=0)
    f = monitor.get_datafile(NOW, tmp_path)

    data = monitor.ensure_datafile(f, NOW, settings(MAX_CARRYOVER_SECONDS=0))

    assert data["carryover_sec"] == 0
    assert data["event_log"] == []
    assert f.is_file()


def test_nothing_to_carry_writes_no_log_line(tmp_path):
    write_past_day(tmp_path, spent=HOUR)
    f = monitor.get_datafile(NOW, tmp_path)

    data = monitor.ensure_datafile(f, NOW, settings())

    assert data["carryover_sec"] == 0
    assert data["event_log"] == []
    assert f.is_file()


def test_overspending_the_limit_carries_nothing_and_no_debt(tmp_path):
    write_past_day(tmp_path, spent=HOUR + 2000)  # the shutdown grace period ran over
    f = monitor.get_datafile(NOW, tmp_path)

    data = monitor.ensure_datafile(f, NOW, settings())

    assert data["carryover_sec"] == 0
    assert data["event_log"] == []


def test_a_grant_fully_used_up_carries_nothing(tmp_path):
    write_past_day(tmp_path, spent=HOUR + 1800, granted=1800)
    f = monitor.get_datafile(NOW, tmp_path)

    data = monitor.ensure_datafile(f, NOW, settings())

    assert data["carryover_sec"] == 0
    assert data["event_log"] == []


def test_the_unused_part_of_a_grant_carries_over(tmp_path):
    write_past_day(tmp_path, spent=HOUR + 600, granted=1800)
    f = monitor.get_datafile(NOW, tmp_path)

    data = monitor.ensure_datafile(f, NOW, settings())

    assert data["carryover_sec"] == 1200
    assert len(data["event_log"]) == 1


def test_a_missing_day_after_an_overspent_one_carries_exactly_the_missing_days_limit(tmp_path):
    write_past_day(tmp_path, spent=HOUR + 2000, days_ago=2)  # then yesterday the machine was off
    f = monitor.get_datafile(NOW, tmp_path)

    data = monitor.ensure_datafile(f, NOW, settings())

    assert data["carryover_sec"] == HOUR
    assert len(data["event_log"]) == 1
