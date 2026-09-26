"""What the setup leaves that the monitor cannot run without: a directory
per child, and the secret in it."""
import pytest

import monitor


def test_the_secret_is_hex_with_whitespace_around_it_allowed(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_text("0a0B0c\r\n", encoding="utf-8")
    assert monitor.load_secret(f) == b"\x0a\x0b\x0c"


def test_a_missing_or_unusable_secret_is_empty_so_no_code_is_accepted(tmp_path):
    f = tmp_path / "secret.txt"
    assert monitor.load_secret(f) == b""
    f.write_text("not hex", encoding="utf-8")
    assert monitor.load_secret(f) == b""
    f.write_text("abc", encoding="utf-8")  # odd number of digits
    assert monitor.load_secret(f) == b""
    f.write_text("", encoding="utf-8")
    assert monitor.load_secret(f) == b""


def test_every_directory_under_data_is_a_child_and_files_are_not(tmp_path):
    (tmp_path / "kid").mkdir()
    (tmp_path / "Anna").mkdir()
    (tmp_path / "crash.log").write_text("", encoding="utf-8")
    assert monitor.load_children(tmp_path) == ["Anna", "kid"]


def test_no_child_directory_is_an_error_not_a_default(tmp_path):
    with pytest.raises(ValueError):
        monitor.load_children(tmp_path / "never-made")
    with pytest.raises(ValueError):
        monitor.load_children(tmp_path)  # exists, empty
    (tmp_path / "crash.log").write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        monitor.load_children(tmp_path)
