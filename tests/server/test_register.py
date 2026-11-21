"""A stranger registers and is logged in, without the maintainer touching anything."""
import pytest

import add_parent
import db


@pytest.fixture
def register(client):
    """Posts the form as the browser does, with the password typed twice."""
    def post(login, password, again=None, **more):
        data = {"login": login, "password": password, "password_again": password if again is None else again}
        return client.post("/register", data={**data, **more})
    return post


def test_registering_logs_the_parent_in(client, register):
    answer = register("anna", "correct horse")
    assert answer.status_code == 200
    assert answer.url.path == "/parent"  # the next step: add a child
    assert "session" in client.cookies
    assert "anna" in answer.text  # the name in the corner of the page


def test_a_taken_login_shows_the_form_again(client, register):
    add_parent.add_parent(db.connect(), "anna", password="correct horse")
    answer = register("anna", "battery staple")
    assert answer.status_code == 400
    assert "anna is taken" in answer.text
    assert "session" not in client.cookies


def test_a_short_password_shows_the_form_again(client, register):
    answer = register("anna", "short")
    assert answer.status_code == 400
    assert "at least 8 characters" in answer.text
    assert "session" not in client.cookies


@pytest.mark.parametrize("password", [
    "12345678", "aaaaaaaa", "qwertyuiop",  # a run, a repeat, a row of the keyboard
    "password1", "summer2024",  # English words with a number
    "anna1985", "annaanna1",  # her own login
    "heslo123", "maminka1", "pejsek2015", "honzik2012",  # the same in Czech, which zxcvbn alone lets through
])
def test_a_guessable_password_shows_the_form_again(client, register, password):
    answer = register("anna", password)
    assert answer.status_code == 400
    assert "Password too simple, robots would guess it.\nPlease try another one." in answer.text
    assert "session" not in client.cookies


@pytest.mark.parametrize("password", ["correct horse", "zelena kocka", "vlak do brna 8", "Tr0ub4dor&3", "xK9#mQ2v"])
def test_a_few_words_or_eight_random_characters_are_enough(register, password):
    assert register("anna", password).url.path == "/parent"


def test_a_password_longer_than_bcrypt_hashes_is_refused(client, register):
    answer = register("anna", "seven green apples " * 4)
    assert answer.status_code == 400
    assert "at most 72 characters" in answer.text


def test_two_different_passwords_show_the_form_again(client, register):
    answer = register("anna", "correct horse", again="correct house")
    assert answer.status_code == 400
    assert "The two passwords differ" in answer.text
    assert "session" not in client.cookies


def test_set_password_changes_it_and_logs_the_parent_out(anna_logged_in, monkeypatch):
    import set_password
    monkeypatch.setattr("sys.argv", ["set_password.py", "anna"])
    monkeypatch.setattr("getpass.getpass", lambda prompt: "a new password")
    set_password.main()
    assert anna_logged_in.get("/parent", follow_redirects=False).headers["location"] == "/login?next=%2Fparent"
    answer = anna_logged_in.post("/login", data={"login": "anna", "password": "a new password"})
    assert answer.status_code == 200


def test_with_an_invite_set_the_form_needs_the_link(client, monkeypatch):
    monkeypatch.setenv("ENOUGHY_INVITE", "friends-only")
    closed = client.get("/register")
    assert closed.status_code == 403
    assert 'name="login"' not in closed.text
    opened = client.get("/register?invitation=friends-only")
    assert opened.status_code == 200
    assert 'name="login"' in opened.text


def test_with_an_invite_set_registering_needs_it_too(client, register, monkeypatch):
    monkeypatch.setenv("ENOUGHY_INVITE", "friends-only")
    refused = register("anna", "correct horse")
    assert refused.status_code == 403
    assert "session" not in client.cookies
    accepted = register("anna", "correct horse", invitation="friends-only")
    assert accepted.status_code == 200
    assert "session" in client.cookies
