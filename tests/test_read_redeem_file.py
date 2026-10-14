import datetime
import hashlib
import hmac

import pytest

import monitor
import os_tooling
from config import MAX_REDEEM_FILE_BYTES, SIGNATURE_CHARS

SECRET = b"\x01\x02\x03\x04"
OTHER_SECRET = b"\x05\x06\x07\x08"
TODAY = datetime.date(2026, 9, 14)
NOW = datetime.datetime(2026, 9, 14, 8, 0, 0)
KID = "kid"


def sign(payload: str, secret=SECRET) -> str:
    """What extra_time.html does on the parent's machine."""
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:SIGNATURE_CHARS]


def code(minutes=10, date="2026-09-14", secret=SECRET) -> str:
    """What the child types: the minutes, and the signature of the date and minutes."""
    return f"{minutes}:{sign(f'{date}:{minutes}', secret)}"


def no_night_code(date="2026-09-14", secret=SECRET) -> str:
    return f"nn:{sign(f'{date}:nn', secret)}"


@pytest.fixture
def redeem_file(tmp_path, monkeypatch):
    """The child's file, where the monitor looks for it; the screen is muted."""
    monkeypatch.setattr(monitor, "SHARED_DIR", tmp_path)
    monkeypatch.setattr(os_tooling, "notify", lambda message, user: None)
    (tmp_path / KID).mkdir()
    return tmp_path / KID / "extra_time.txt"


@pytest.fixture
def day():
    """The day's data, which lists the codes it has granted."""
    return monitor.load_data("never-there.json")


def handle(redeem_file, content, secret=SECRET):
    redeem_file.write_text(content, encoding="utf-8")
    return monitor.read_redeem_file(redeem_file, secret, TODAY)


def redeem(redeem_file, day, content) -> int:
    """What the monitor does with the file: check the code, then the day's
    list; the seconds the day gained by it."""
    redeem_file.write_text(content, encoding="utf-8")
    before = day["granted_sec"]
    monitor.redeem_code(day, redeem_file.with_name("day.json"), NOW, KID, SECRET)
    return day["granted_sec"] - before


def test_without_a_secret_nothing_is_accepted(redeem_file):
    result = handle(redeem_file, code(), secret=b"")
    assert result["status"] == "cannot load secret"
    assert result["extra_time_sec"] == 0


def test_a_missing_file_is_created_empty_for_the_child_to_use(redeem_file):
    result = monitor.read_redeem_file(redeem_file, SECRET, TODAY)
    assert result["status"] == "no_file"
    assert redeem_file.is_file() and redeem_file.read_text() == ""


def test_an_empty_file_is_not_a_code(redeem_file):
    assert handle(redeem_file, "  \n")["status"] == "empty file"


def test_an_oversized_file_is_not_even_read(redeem_file):
    result = handle(redeem_file, "x" * (MAX_REDEEM_FILE_BYTES + 1))
    assert result["status"] == "file too large"


def test_a_malformed_code_is_rejected(redeem_file):
    assert handle(redeem_file, "600")["status"] == "invalid format"
    assert handle(redeem_file, "2026-09-14:60:abcd")["status"] == "invalid format"
    assert handle(redeem_file, "ten minutes:abcd")["status"] == "invalid format"


def test_a_valid_code_yields_its_minutes_in_seconds(redeem_file):
    result = handle(redeem_file, code(minutes=10))
    assert result == {
        "status": "valid",
        "redeem_code": code(minutes=10),
        "extra_time_sec": 600,
        "nonight": False,
    }


def test_surrounding_whitespace_is_fine(redeem_file):
    assert handle(redeem_file, f"\n {code()} \n")["status"] == "valid"


def test_a_tampered_amount_fails_the_signature(redeem_file):
    _, sig = code(minutes=10).split(":")
    result = handle(redeem_file, f"100:{sig}")
    assert result["status"] == "invalid signature"
    assert result["extra_time_sec"] == 0


def test_a_code_signed_with_another_secret_is_rejected(redeem_file):
    assert handle(redeem_file, code(secret=OTHER_SECRET))["status"] == "invalid signature"


def test_variant_spellings_of_the_minutes_normalize_to_one_code(redeem_file):
    # int() accepts these, so the day's list must see them as the same code
    sig = code(minutes=10).split(":")[1]
    for variant in ("010", "+10", " 10"):
        result = handle(redeem_file, f"{variant}:{sig}")
        assert result["status"] == "valid"
        assert result["redeem_code"] == code(minutes=10)


# --- the date: never typed, but signed, so a code is good on its day only ---


def test_a_code_made_on_another_day_fails_the_signature(redeem_file):
    assert handle(redeem_file, code(date="2026-09-14"))["status"] == "valid"
    assert handle(redeem_file, code(date="2026-09-13"))["status"] == "invalid signature"
    assert handle(redeem_file, code(date="2026-09-15"))["status"] == "invalid signature"


# --- the no-night code: no time in it ---


def test_a_no_night_code_for_today_is_valid_and_carries_no_time(redeem_file):
    result = handle(redeem_file, no_night_code())
    assert result == {"status": "valid", "redeem_code": no_night_code(), "extra_time_sec": 0, "nonight": True}


def test_a_no_night_code_made_on_another_day_fails_the_signature(redeem_file):
    assert handle(redeem_file, no_night_code(date="2026-09-13"))["status"] == "invalid signature"
    assert handle(redeem_file, no_night_code(date="2026-09-15"))["status"] == "invalid signature"


def test_a_no_night_code_signed_with_another_secret_is_rejected(redeem_file):
    assert handle(redeem_file, no_night_code(secret=OTHER_SECRET))["status"] == "invalid signature"


def test_a_no_night_code_grants_no_time_and_lifts_the_night(redeem_file, day):
    assert redeem(redeem_file, day, no_night_code()) == 0
    assert day["no_night"] is True
    assert day["redeemed_codes"] == [no_night_code()]


# --- the file: read once, then emptied, whatever the verdict ---


def test_a_code_is_taken_out_of_the_file_once_judged(redeem_file, day):
    assert redeem(redeem_file, day, code()) == 600
    assert redeem_file.read_text() == ""


def test_a_refused_code_is_taken_out_of_the_file_too(redeem_file, day):
    assert redeem(redeem_file, day, "nonsense") == 0
    assert redeem_file.read_text() == ""
    assert redeem(redeem_file, day, code(secret=OTHER_SECRET)) == 0
    assert redeem_file.read_text() == ""


def test_without_a_secret_the_code_waits_in_the_file(redeem_file, day):
    redeem_file.write_text(code(), encoding="utf-8")
    monitor.redeem_code(day, redeem_file.with_name("day.json"), NOW, KID, b"")
    assert redeem_file.read_text() == code()


# --- the day's list: a code works once ---


def test_a_fresh_code_is_granted_and_entered_in_the_days_list(redeem_file, day):
    assert redeem(redeem_file, day, code(minutes=10)) == 600
    assert day["redeemed_codes"] == [code(minutes=10)]


def test_the_same_code_is_refused_the_second_time(redeem_file, day):
    assert redeem(redeem_file, day, code(minutes=10)) == 600
    assert redeem(redeem_file, day, code(minutes=10)) == 0
    assert day["redeemed_codes"] == [code(minutes=10)]


def test_a_respelled_amount_does_not_get_around_the_list(redeem_file, day):
    sig = code(minutes=10).split(":")[1]
    assert redeem(redeem_file, day, f"10:{sig}") == 600
    assert redeem(redeem_file, day, f"010:{sig}") == 0


def test_a_code_for_another_amount_is_its_own_grant(redeem_file, day):
    assert redeem(redeem_file, day, code(minutes=10)) == 600
    assert redeem(redeem_file, day, code(minutes=20)) == 1200
    assert day["redeemed_codes"] == [code(minutes=10), code(minutes=20)]


def test_an_invalid_code_touches_neither_the_grant_nor_the_list(redeem_file, day):
    assert redeem(redeem_file, day, code(secret=OTHER_SECRET)) == 0
    assert day["redeemed_codes"] == []
