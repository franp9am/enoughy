"""The parent changes a child's settings. A setting with a widget is shown in
the parent's terms, minutes for a limit the monitor counts in seconds; one
without is the JSON the monitor sent, so a new setting works on day one. Each
widget reads and writes its own boxes only."""
import json
import re

import db
import views
from settings import SETTINGS, default_settings  # the monitor's, what a real report holds

REPORT = {
    "date": "2026-10-12", "time_spent_sec": 600, "carryover_sec": 0, "granted_sec": 0,
    "remaining_sec": 3000, "last_tick": None, "applied_grant_ids": [],
}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def tom_reporting(anna_logged_in, settings: dict) -> int:
    """Tom's monitor has synced once with these settings; his child_id."""
    anna_logged_in.post("/children", data={"name": "Tom"})
    child = db.connect().execute("SELECT id, token FROM children").fetchone()
    anna_logged_in.post(
        "/api/sync", json={**REPORT, "settings": settings},
        headers={"Authorization": f"Bearer {child['token']}"},
    )
    return child["id"]


def form_answers(child_id: int, minutes: str = "60", cap: str = "", day: str = "06:00", night: str = "21:00",
                 ticked=("unlimited_carryover",), limits=None, hours=None, **json_boxes) -> dict:
    """The whole form: the boxes, the ticked checkboxes, the two exception tables
    blank unless `limits` gives a weekday's minutes or `hours` its (day, night), and a
    JSON box per extra name given. `ticked` may name a weekday's no_night_<day>."""
    answers = {name: json.dumps(value) for name, value in json_boxes.items()}
    for weekday in WEEKDAYS:
        answers[f"limit_{weekday}"] = (limits or {}).get(weekday, "")
        answers[f"day_starts_{weekday}"], answers[f"night_starts_{weekday}"] = (hours or {}).get(weekday, ("", ""))
    return {**answers, "child_id": child_id, "DAILY_LIMIT_SECONDS": minutes, "MAX_CARRYOVER_SECONDS": cap,
            "day_starts": day, "night_starts": night, **{name: "on" for name in ticked}}


def asked() -> dict:
    """The last change the parent asked for."""
    row = db.connect().execute("SELECT settings FROM settings_changes ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(row["settings"])


def test_every_widget_s_name_is_a_setting_the_monitor_has():
    assert set(views.WIDGETS) <= set(SETTINGS)


def test_the_limit_is_a_box_in_minutes(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {**default_settings(), "DAILY_LIMIT_SECONDS": 3600})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert re.search(r'name="DAILY_LIMIT_SECONDS" value="60"', page) and 'value="3600"' not in page
    assert "Minutes a day" in page
    anna_logged_in.post("/settings", data=form_answers(child_id, minutes="90"))
    assert asked()["DAILY_LIMIT_SECONDS"] == 5400


def test_minutes_that_are_not_a_number_are_refused(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, default_settings())
    answer = anna_logged_in.post("/settings", data=form_answers(child_id, minutes="an hour"))
    assert answer.status_code == 400
    assert db.connect().execute("SELECT count(*) FROM settings_changes").fetchone()[0] == 0


def test_the_cap_box_and_its_checkboxes_are_the_cap_with_zero_as_no_carryover(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {**default_settings(), "MAX_CARRYOVER_SECONDS": 5 * 3600})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert re.search(r'name="MAX_CARRYOVER_SECONDS" value="300"[^>]*>', page)
    assert not re.search(r'name="MAX_CARRYOVER_SECONDS"[^>]*readonly', page)
    assert not re.search(r'name="(no|unlimited)_carryover"[^>]*checked', page)
    anna_logged_in.post("/settings", data=form_answers(child_id, ticked=("unlimited_carryover",)))
    assert asked()["MAX_CARRYOVER_SECONDS"] is None
    anna_logged_in.post("/settings", data=form_answers(child_id, ticked=("no_carryover",)))
    assert asked()["MAX_CARRYOVER_SECONDS"] == 0
    anna_logged_in.post("/settings", data=form_answers(child_id, cap="120", ticked=()))
    assert asked()["MAX_CARRYOVER_SECONDS"] == 7200
    both = form_answers(child_id, ticked=("no_carryover", "unlimited_carryover"))
    assert anna_logged_in.post("/settings", data=both).status_code == 400


def test_a_cap_of_zero_ticks_no_carryover_and_freezes_the_box(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {**default_settings(), "MAX_CARRYOVER_SECONDS": 0})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert re.search(r'name="no_carryover"[^>]*checked', page)
    assert not re.search(r'name="unlimited_carryover"[^>]*checked', page)
    assert re.search(r'name="MAX_CARRYOVER_SECONDS" value="0"[^>]*readonly', page)
    assert "carryover" not in anna_logged_in.get("/", params={"child_id": child_id}).text.split("In force")[-1][:200]


def test_the_window_is_two_time_boxes_and_a_no_night_checkbox(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {**default_settings(), "ALLOWED_HOURS": ["6:00", "24:00"]})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert re.search(r'name="day_starts" value="06:00"[^>]*>', page)
    assert re.search(r'name="night_starts" value="23:59"[^>]*>', page)  # the box stops a minute before 24:00
    assert not re.search(r'name="(day|night)_starts"[^>]*readonly', page)
    assert not re.search(r'name="no_night"[^>]*checked', page)
    anna_logged_in.post("/settings", data=form_answers(child_id, day="07:30", night="22:00"))
    assert asked()["ALLOWED_HOURS"] == ["7:30", "22:00"]
    anna_logged_in.post("/settings", data=form_answers(child_id, ticked=("unlimited_carryover", "no_night")))
    assert asked()["ALLOWED_HOURS"] is None
    answer = anna_logged_in.post("/settings", data=form_answers(child_id, day="morning"))
    assert answer.status_code == 400


def test_no_night_ticks_its_checkbox_and_freezes_the_empty_boxes(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {**default_settings(), "ALLOWED_HOURS": None})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert re.search(r'name="no_night"[^>]*checked', page)
    assert re.search(r'name="day_starts" value=""[^>]*readonly', page)
    assert re.search(r'name="night_starts" value=""[^>]*readonly', page)


def test_limit_exceptions_are_a_box_per_weekday_blank_for_none(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {**default_settings(), "DAILY_LIMIT_SECONDS": 3600,
                                              "DAILY_LIMIT_OVERRIDES": {"sat": 7200}})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert re.search(r'name="limit_sat" value="120"', page)
    assert re.search(r'name="limit_mon" value=""\s+type', page)
    assert re.search(r'<details open>\s*<summary>Daily limit exceptions', page)
    assert 'name="DAILY_LIMIT_OVERRIDES"' not in page
    anna_logged_in.post("/settings", data=form_answers(child_id, limits={"sat": "90", "sun": "60"}))
    assert asked()["DAILY_LIMIT_OVERRIDES"] == {"sat": 5400, "sun": 3600}
    anna_logged_in.post("/settings", data=form_answers(child_id))
    assert asked()["DAILY_LIMIT_OVERRIDES"] == {}


def test_hours_exceptions_are_two_boxes_and_no_night_per_weekday_blank_for_none(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {**default_settings(),
                                              "ALLOWED_HOURS_OVERRIDES": {"fri": ["6:00", "23:00"], "sun": None}})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert re.search(r'name="night_starts_fri" value="23:00"', page)
    assert re.search(r'name="day_starts_mon" value=""[^>]*>', page) and not re.search(r'name="day_starts_mon"[^>]*readonly', page)
    assert re.search(r'name="day_starts_sun" value=""[^>]*readonly', page)
    assert re.search(r'name="no_night_sun"[^>]*checked', page) and not re.search(r'name="no_night_fri"[^>]*checked', page)
    assert re.search(r'<details open>\s*<summary>Daytime exceptions', page)
    assert 'name="ALLOWED_HOURS_OVERRIDES"' not in page
    answers = form_answers(child_id, hours={"fri": ("07:00", "22:30")}, ticked=("unlimited_carryover", "no_night_sat"))
    anna_logged_in.post("/settings", data=answers)
    assert asked()["ALLOWED_HOURS_OVERRIDES"] == {"fri": ["7:00", "22:30"], "sat": None}
    anna_logged_in.post("/settings", data=form_answers(child_id))
    assert asked()["ALLOWED_HOURS_OVERRIDES"] == {}
    one_time = form_answers(child_id, hours={"wed": ("06:00", "")})
    assert anna_logged_in.post("/settings", data=one_time).status_code == 400


def test_a_name_without_a_widget_is_a_json_box_after_the_widgets(anna_logged_in):
    child_id = tom_reporting(anna_logged_in, {"NEW_ONE": {"a": 1}, **default_settings()})
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert 'value="{&#34;a&#34;: 1}"' in page
    marks = ["Minutes a day", "Day starts", "Carryover cap", "Daily limit exceptions", "Daytime exceptions", "NEW_ONE"]
    assert [page.index(mark) for mark in marks] == sorted(page.index(mark) for mark in marks)
    anna_logged_in.post("/settings", data=form_answers(child_id, NEW_ONE=[1, 2]))
    assert asked()["NEW_ONE"] == [1, 2] and asked()["DAILY_LIMIT_SECONDS"] == 3600


def test_a_0_1_0_monitor_gets_the_widgets_it_has_names_for_and_json_for_the_rest(anna_logged_in):
    old = {"DAILY_LIMIT_SECONDS": 3600, "CARRYOVER": True, "MAX_CARRYOVER_SECONDS": 18000,
           "EARLIEST_HOUR_INCLUDED": 6, "LATEST_HOUR_INCLUDED": 20}
    child_id = tom_reporting(anna_logged_in, old)
    page = anna_logged_in.get("/settings", params={"child_id": child_id}).text
    assert "Minutes a day" in page and "Carryover cap" in page
    assert "Day starts" not in page and "<details" not in page
    assert re.search(r'name="CARRYOVER" value="true"', page)
    assert re.search(r'name="EARLIEST_HOUR_INCLUDED" value="6"', page)
    answers = {"child_id": child_id, "DAILY_LIMIT_SECONDS": "90", "MAX_CARRYOVER_SECONDS": "60", "CARRYOVER": "false",
               "EARLIEST_HOUR_INCLUDED": "7", "LATEST_HOUR_INCLUDED": "21"}
    assert anna_logged_in.post("/settings", data=answers).status_code == 200
    assert asked() == {"DAILY_LIMIT_SECONDS": 5400, "CARRYOVER": False, "MAX_CARRYOVER_SECONDS": 3600,
                       "EARLIEST_HOUR_INCLUDED": 7, "LATEST_HOUR_INCLUDED": 21}
