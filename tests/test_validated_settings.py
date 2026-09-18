import json

import pytest

import settings

HOUR = 60 * 60

# what a machine already runs with; deliberately not the defaults, so a test can
# tell "kept the fallback" from "reset to defaults"
IN_FORCE = {
    "DAILY_LIMIT_SECONDS": 2 * HOUR,
    "CARRYOVER": False,
    "MAX_CARRYOVER_SECONDS": 3 * HOUR,
    "ALLOWED_HOURS": [8, 20],
    "DAILY_LIMIT_OVERRIDES": {"sat": 3 * HOUR},
    "ALLOWED_HOURS_OVERRIDES": {"fri": [8, 22]},
}


def validated(change):
    return settings.validated_settings(change, IN_FORCE)


def test_a_full_valid_change_is_taken_as_is():
    change = {**IN_FORCE, "DAILY_LIMIT_SECONDS": HOUR, "CARRYOVER": True}
    assert validated(change) == change


def test_a_partial_change_is_filled_from_what_is_in_force_not_the_defaults():
    assert validated({"DAILY_LIMIT_SECONDS": HOUR}) == {**IN_FORCE, "DAILY_LIMIT_SECONDS": HOUR}


def test_without_a_fallback_the_defaults_fill_the_gaps():
    assert settings.validated_settings({"CARRYOVER": False}) == {
        **settings.default_settings(),
        "CARRYOVER": False,
    }


def test_one_bad_value_rejects_the_whole_change():
    change = {"DAILY_LIMIT_SECONDS": HOUR, "ALLOWED_HOURS": [6, 25]}  # no such hour
    assert validated(change) == IN_FORCE


def test_an_unknown_setting_rejects_the_whole_change():
    assert validated({"DAILY_LIMIT_SECONDS": HOUR, "BEDTIME": 21}) == IN_FORCE


def test_a_window_is_two_hours_at_least_one_apart():
    assert validated({"ALLOWED_HOURS": [0, 24]})["ALLOWED_HOURS"] == [0, 24]  # the whole day
    assert validated({"ALLOWED_HOURS": [12, 13]})["ALLOWED_HOURS"] == [12, 13]
    for window in ([21, 6], [12, 12], [6], [6, 12, 18], [-1, 12], [6, "21"], (6, 21), "6-21"):
        assert validated({"ALLOWED_HOURS": window}) == IN_FORCE, window


def test_a_weekday_window_is_checked_like_the_general_one():
    change = {"ALLOWED_HOURS_OVERRIDES": {"fri": [6, 24], "sat": [12, 13]}}
    assert validated(change) == {**IN_FORCE, **change}
    assert validated({"ALLOWED_HOURS_OVERRIDES": {}}) == {**IN_FORCE, "ALLOWED_HOURS_OVERRIDES": {}}
    assert validated({"ALLOWED_HOURS_OVERRIDES": {"fri": [21, 6]}}) == IN_FORCE
    assert validated({"ALLOWED_HOURS_OVERRIDES": {"friday": [6, 21]}}) == IN_FORCE
    assert validated({"ALLOWED_HOURS_OVERRIDES": {"fri": 21}}) == IN_FORCE


def test_none_is_accepted_only_where_nullable():
    assert validated({"MAX_CARRYOVER_SECONDS": None})["MAX_CARRYOVER_SECONDS"] is None
    assert validated({"DAILY_LIMIT_SECONDS": None}) == IN_FORCE


def test_a_bool_is_not_an_int_and_an_int_is_not_a_bool():
    assert validated({"DAILY_LIMIT_SECONDS": True}) == IN_FORCE
    assert validated({"CARRYOVER": 1}) == IN_FORCE


def test_limits_outside_a_day_are_rejected():
    assert validated({"DAILY_LIMIT_SECONDS": 0})["DAILY_LIMIT_SECONDS"] == 0  # no screen time
    assert validated({"DAILY_LIMIT_SECONDS": 24 * HOUR})["DAILY_LIMIT_SECONDS"] == 24 * HOUR
    assert validated({"DAILY_LIMIT_SECONDS": 24 * HOUR + 1}) == IN_FORCE
    assert validated({"DAILY_LIMIT_SECONDS": -1}) == IN_FORCE


def test_valid_overrides_replace_the_ones_in_force():
    change = {"DAILY_LIMIT_OVERRIDES": {"mon": 0, "sun": 24 * HOUR}}
    assert validated(change) == {**IN_FORCE, **change}
    assert validated({"DAILY_LIMIT_OVERRIDES": {}}) == {**IN_FORCE, "DAILY_LIMIT_OVERRIDES": {}}


def test_overrides_need_real_weekdays_and_int_seconds():
    assert validated({"DAILY_LIMIT_OVERRIDES": {"monday": HOUR}}) == IN_FORCE
    assert validated({"DAILY_LIMIT_OVERRIDES": {"mon": "3600"}}) == IN_FORCE
    assert validated({"DAILY_LIMIT_OVERRIDES": {"mon": None}}) == IN_FORCE
    assert validated({"DAILY_LIMIT_OVERRIDES": [("mon", HOUR)]}) == IN_FORCE


def test_the_result_is_a_copy_and_the_fallback_stays_untouched():
    before = dict(IN_FORCE)
    result = validated({"DAILY_LIMIT_SECONDS": HOUR})
    result["CARRYOVER"] = True
    rejected = validated({"BEDTIME": 21})
    rejected["CARRYOVER"] = True
    assert IN_FORCE == before


# --- the settings file -----------------------------------------------------


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / "settings.json"


def test_without_a_file_the_defaults_are_in_force(settings_file):
    assert settings.settings_in_force(settings_file) == settings.default_settings()


def test_the_file_is_read_with_the_defaults_for_anything_it_lacks(settings_file):
    settings_file.write_text(json.dumps({"DAILY_LIMIT_SECONDS": 2 * HOUR}), encoding="utf-8")
    assert settings.settings_in_force(settings_file) == {**settings.default_settings(), "DAILY_LIMIT_SECONDS": 2 * HOUR}


def test_a_file_from_before_0_7_keeps_its_window_and_the_rest(settings_file):
    old = {"DAILY_LIMIT_SECONDS": 2 * HOUR, "EARLIEST_HOUR_INCLUDED": 8, "LATEST_HOUR_INCLUDED": 19}
    settings_file.write_text(json.dumps(old), encoding="utf-8")
    assert settings.settings_in_force(settings_file) == {
        **settings.default_settings(), "DAILY_LIMIT_SECONDS": 2 * HOUR, "ALLOWED_HOURS": [8, 20]
    }
    # an old window that was unusable, or half missing, is junk like any other
    for old_names in ({"EARLIEST_HOUR_INCLUDED": 19, "LATEST_HOUR_INCLUDED": 8}, {"LATEST_HOUR_INCLUDED": 19}):
        settings_file.write_text(json.dumps({"DAILY_LIMIT_SECONDS": 2 * HOUR, **old_names}), encoding="utf-8")
        assert settings.settings_in_force(settings_file) == settings.default_settings()


def test_an_unusable_file_means_the_defaults_not_a_crash(settings_file):
    for content in ("{not json", "[1, 2]", "", '{"DAILY_LIMIT_SECONDS": -1}'):
        settings_file.write_text(content, encoding="utf-8")
        assert settings.settings_in_force(settings_file) == settings.default_settings()


def test_ensure_writes_the_defaults_once_and_never_overwrites(settings_file):
    settings.ensure_settings_file(settings_file)
    assert json.loads(settings_file.read_text(encoding="utf-8")) == settings.default_settings()
    settings_file.write_text(json.dumps(IN_FORCE), encoding="utf-8")
    settings.ensure_settings_file(settings_file)
    assert settings.settings_in_force(settings_file) == IN_FORCE


def test_save_writes_what_is_taken_and_keeps_the_file_on_refusal(settings_file):
    settings.write_settings_file(IN_FORCE, settings_file)
    taken = settings.save_settings({"DAILY_LIMIT_SECONDS": HOUR}, settings_file)
    assert taken == {**IN_FORCE, "DAILY_LIMIT_SECONDS": HOUR}
    assert settings.settings_in_force(settings_file) == taken
    refused = settings.save_settings({"DAILY_LIMIT_SECONDS": -1}, settings_file)
    assert refused == taken
    assert settings.settings_in_force(settings_file) == taken
    assert not settings_file.with_suffix(".tmp").exists()
