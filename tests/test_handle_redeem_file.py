import datetime
import hashlib
import hmac

import pytest

import monitor
from config import MAX_REDEEM_FILE_BYTES, SIGNATURE_CHARS

SECRET = b"\x01\x02\x03\x04"
OTHER_SECRET = b"\x05\x06\x07\x08"
TODAY = datetime.date(2026, 9, 14)


def sign(payload: str, secret=SECRET) -> str:
    """What grant_extra_time_offline.py does on the parent's machine."""
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:SIGNATURE_CHARS]


def code(date="2026-09-14", seconds=600, secret=SECRET) -> str:
    payload = f"{date}:{seconds}"
    return f"{payload}:{sign(payload, secret)}"


@pytest.fixture
def redeem_file(tmp_path):
    return tmp_path / "extra_time.txt"


def handle(redeem_file, content, secret=SECRET):
    redeem_file.write_text(content, encoding="utf-8")
    return monitor.handle_redeem_file(redeem_file, secret, TODAY)


def test_without_a_secret_nothing_is_accepted(redeem_file):
    result = handle(redeem_file, code(), secret=b"")
    assert result["status"] == "cannot load secret"
    assert result["extra_time_sec"] == 0


def test_a_missing_file_is_created_empty_for_the_child_to_use(redeem_file):
    result = monitor.handle_redeem_file(redeem_file, SECRET, TODAY)
    assert result["status"] == "no_file"
    assert redeem_file.is_file() and redeem_file.read_text() == ""


def test_an_empty_file_is_not_a_code(redeem_file):
    assert handle(redeem_file, "  \n")["status"] == "empty file"


def test_an_oversized_file_is_not_even_read(redeem_file):
    result = handle(redeem_file, "x" * (MAX_REDEEM_FILE_BYTES + 1))
    assert result["status"] == "file too large"


def test_a_malformed_code_is_rejected(redeem_file):
    assert handle(redeem_file, "2026-09-14:600")["status"] == "invalid format"
    assert handle(redeem_file, "2026-09-14:600:abcd:extra")["status"] == "invalid format"
    assert handle(redeem_file, "2026-09-14:ten minutes:abcd")["status"] == "invalid format"


def test_a_valid_code_yields_its_seconds(redeem_file):
    result = handle(redeem_file, code(seconds=600))
    assert result == {"status": "valid", "redeem_code": code(seconds=600), "extra_time_sec": 600}


def test_surrounding_whitespace_is_fine(redeem_file):
    assert handle(redeem_file, f"\n {code()} \n")["status"] == "valid"


def test_a_tampered_amount_fails_the_signature(redeem_file):
    date, _, sig = code(seconds=600).split(":")
    result = handle(redeem_file, f"{date}:6000:{sig}")
    assert result["status"] == "invalid signature"
    assert result["extra_time_sec"] == 0


def test_a_code_signed_with_another_secret_is_rejected(redeem_file):
    assert handle(redeem_file, code(secret=OTHER_SECRET))["status"] == "invalid signature"


def test_variant_spellings_of_the_amount_normalize_to_one_code(redeem_file):
    # int() accepts these, so the ledger must see them as the same code
    date, _, sig = code(seconds=600).split(":")
    for variant in ("0600", "+600", " 600"):
        result = handle(redeem_file, f"{date}:{variant}:{sig}")
        assert result["status"] == "valid"
        assert result["redeem_code"] == code(seconds=600)


# --- the date: a nonce, or with CHECK_DATE_IN_REDEEM_CODES the one day the code is good ---


def test_by_default_a_code_from_another_day_is_valid(redeem_file):
    assert handle(redeem_file, code(date="2026-09-01"))["status"] == "valid"


def test_with_the_check_on_a_code_is_good_on_its_day_only(redeem_file, monkeypatch):
    monkeypatch.setattr(monitor, "CHECK_DATE_IN_REDEEM_CODES", True)
    assert handle(redeem_file, code(date="2026-09-14"))["status"] == "valid"
    assert handle(redeem_file, code(date="2026-09-13"))["status"] == "wrong date"
    assert handle(redeem_file, code(date="2026-09-15"))["status"] == "wrong date"


def test_with_the_check_on_a_forged_date_is_still_an_invalid_signature(redeem_file, monkeypatch):
    monkeypatch.setattr(monitor, "CHECK_DATE_IN_REDEEM_CODES", True)
    _, seconds, sig = code(date="2026-09-13").split(":")
    assert handle(redeem_file, f"2026-09-14:{seconds}:{sig}")["status"] == "invalid signature"


def test_a_code_refused_for_its_date_is_not_used_up(redeem_file, tmp_path, monkeypatch):
    used_codes_file = tmp_path / "used_redeem_codes.txt"
    monkeypatch.setattr(monitor, "CHECK_DATE_IN_REDEEM_CODES", True)
    redeem_file.write_text(code(date="2026-09-13"), encoding="utf-8")
    assert monitor.redeem_unused_code(redeem_file, SECRET, used_codes_file, TODAY) == 0
    assert not used_codes_file.exists()
    monkeypatch.setattr(monitor, "CHECK_DATE_IN_REDEEM_CODES", False)
    assert monitor.redeem_unused_code(redeem_file, SECRET, used_codes_file, TODAY) == 600


# --- the ledger: a code works once, across days ---


@pytest.fixture
def used_codes_file(tmp_path):
    return tmp_path / "used_redeem_codes.txt"


def redeem(redeem_file, used_codes_file, content):
    redeem_file.write_text(content, encoding="utf-8")
    return monitor.redeem_unused_code(redeem_file, SECRET, used_codes_file, TODAY)


def test_a_fresh_code_is_granted_and_entered_in_the_ledger(redeem_file, used_codes_file):
    assert redeem(redeem_file, used_codes_file, code(seconds=600)) == 600
    assert used_codes_file.read_text(encoding="utf-8") == code(seconds=600) + "\n"


def test_the_ledger_grows_by_one_line_per_code(redeem_file, used_codes_file):
    redeem(redeem_file, used_codes_file, code(date="2026-09-14"))
    redeem(redeem_file, used_codes_file, code(date="2026-09-15"))
    assert used_codes_file.read_text(encoding="utf-8").splitlines() == [
        code(date="2026-09-14"),
        code(date="2026-09-15"),
    ]
    assert monitor.load_used_codes(used_codes_file) == {code(date="2026-09-14"), code(date="2026-09-15")}


def test_a_half_written_last_line_does_not_hide_the_codes_before_it(redeem_file, used_codes_file):
    used_codes_file.write_text(code(date="2026-09-14") + "\n2026-09-15:6", encoding="utf-8")
    assert redeem(redeem_file, used_codes_file, code(date="2026-09-14")) == 0
    assert redeem(redeem_file, used_codes_file, code(date="2026-09-15")) == 600


def test_the_same_code_is_refused_the_second_time(redeem_file, used_codes_file):
    assert redeem(redeem_file, used_codes_file, code(seconds=600)) == 600
    assert redeem(redeem_file, used_codes_file, code(seconds=600)) == 0


def test_a_respelled_amount_does_not_get_around_the_ledger(redeem_file, used_codes_file):
    date, _, sig = code(seconds=600).split(":")
    assert redeem(redeem_file, used_codes_file, f"{date}:600:{sig}") == 600
    assert redeem(redeem_file, used_codes_file, f"{date}:0600:{sig}") == 0


def test_a_different_code_for_the_same_amount_is_its_own_grant(redeem_file, used_codes_file):
    assert redeem(redeem_file, used_codes_file, code(date="2026-09-14", seconds=600)) == 600
    assert redeem(redeem_file, used_codes_file, code(date="2026-09-15", seconds=600)) == 600


def test_an_invalid_code_touches_neither_the_grant_nor_the_ledger(redeem_file, used_codes_file):
    assert redeem(redeem_file, used_codes_file, code(secret=OTHER_SECRET)) == 0
    assert not used_codes_file.exists()
