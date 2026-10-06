import json

import monitor

DEFAULTS = {
    "time_spent_sec": 0,
    "ticks": [],
    "last_tick": None,
    "carryover_sec": 0,
    "granted_sec": 0,
    "no_night": False,
    "event_log": [],
}


def test_missing_file_gives_defaults(tmp_path):
    assert monitor.load_data(tmp_path / "2026-09-14.json") == DEFAULTS


def test_unparseable_file_gives_defaults(tmp_path):
    f = tmp_path / "2026-09-14.json"
    f.write_text("{not json", encoding="utf-8")
    assert monitor.load_data(f) == DEFAULTS


def test_json_that_is_not_a_dict_gives_defaults(tmp_path):
    f = tmp_path / "2026-09-14.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    assert monitor.load_data(f) == DEFAULTS


def test_missing_keys_are_filled_in_and_present_ones_kept(tmp_path):
    f = tmp_path / "2026-09-14.json"
    f.write_text(json.dumps({"time_spent_sec": 1234}), encoding="utf-8")
    assert monitor.load_data(f) == {**DEFAULTS, "time_spent_sec": 1234}

