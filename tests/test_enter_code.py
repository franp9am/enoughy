"""The "Extra time" dialog's one step without a window: handing the code over."""
import enter_code


def test_the_code_lands_in_the_childs_redeem_file_without_the_whitespace(tmp_path):
    (tmp_path / "kid").mkdir()
    assert enter_code.save_code(" 60:a184\n", tmp_path / "kid")
    assert (tmp_path / "kid" / "extra_time.txt").read_text() == "60:a184"


def test_a_new_code_replaces_the_one_before(tmp_path):
    (tmp_path / "kid").mkdir()
    enter_code.save_code("60:a184", tmp_path / "kid")
    enter_code.save_code("10:beef", tmp_path / "kid")
    assert (tmp_path / "kid" / "extra_time.txt").read_text() == "10:beef"


def test_an_account_the_setup_never_saw_gets_no_folder(tmp_path):
    assert not enter_code.save_code("60:a184", tmp_path / "parent")
    assert not (tmp_path / "parent").exists()


def test_the_shortcut_opens_this_dialog_with_the_windowless_python(tmp_path):
    shortcut = tmp_path / "Start Menu" / "Extra time.lnk"
    shortcut.parent.mkdir()
    enter_code.make_shortcut(shortcut)
    link = shortcut.read_bytes()
    assert "pythonw.exe".encode("utf-16-le") in link
    assert "enter_code.py".encode("utf-16-le") in link
