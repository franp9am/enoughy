"""The widget's pure helpers: the text in the corner and its colour."""
import remaining_time_widget as widget
from remaining_time_widget import COLOR_CRITICAL, COLOR_NORMAL, COLOR_WARNING


def test_whole_hours_show_no_minutes():
    assert widget.format_remaining(2 * 3600) == "2h"


def test_hours_and_minutes():
    assert widget.format_remaining(2 * 3600 + 58 * 60) == "2h 58m"


def test_under_an_hour_shows_minutes_only():
    assert widget.format_remaining(45 * 60) == "45 min"


def test_seconds_round_up_to_the_next_minute():
    assert widget.format_remaining(59) == "1 min"
    assert widget.format_remaining(61) == "2 min"


def test_nothing_left_and_negative_both_read_zero():
    assert widget.format_remaining(0) == "0 min"
    assert widget.format_remaining(-30) == "0 min"


def test_colour_turns_orange_then_red_as_time_runs_out():
    assert widget.color_for(widget.WARNING_SECONDS + 1) == COLOR_NORMAL
    assert widget.color_for(widget.WARNING_SECONDS) == COLOR_WARNING
    assert widget.color_for(widget.CRITICAL_SECONDS + 1) == COLOR_WARNING
    assert widget.color_for(widget.CRITICAL_SECONDS) == COLOR_CRITICAL
    assert widget.color_for(0) == COLOR_CRITICAL
