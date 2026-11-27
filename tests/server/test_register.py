"""A stranger registers and is logged in, without the maintainer touching anything."""
from datetime import timedelta

import pytest

import add_child
import add_parent
import app
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
    assert "Password too long, at most 64 characters." in answer.text


def test_a_password_of_too_many_bytes_is_too_long(client, register):
    answer = register("anna", "žluťoučký kůň úpěl ďábelské ódy " * 2)  # 64 characters, 90 bytes
    assert answer.status_code == 400
    assert "Password too long." in answer.text


def test_a_login_of_64_characters_is_the_longest(client, register):
    answer = register("a" * 65, "correct horse")
    assert answer.status_code == 400
    assert "Login too long, at most 64 characters." in answer.text
    assert "session" not in client.cookies
    assert register("a" * 64, "correct horse").url.path == "/parent"


def test_a_login_that_is_a_familys_name_is_taken(client, register):
    """Or a stranger would walk into the family and find its children."""
    connection = db.connect()
    add_parent.add_parent(connection, "petr", password="correct horse", family_name="novakovi")
    family = connection.execute("SELECT id FROM families WHERE name = 'novakovi'").fetchone()["id"]
    add_child.add_child(connection, family, "Honzik")
    answer = register("novakovi", "battery staple")
    assert answer.status_code == 400
    assert "novakovi is taken" in answer.text
    assert "session" not in client.cookies
    assert connection.execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 1


def test_a_taken_login_leaves_no_family_behind(client, register):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse", family_name="novakovi")
    assert register("anna", "battery staple").status_code == 400
    assert [row["name"] for row in connection.execute("SELECT name FROM families")] == ["novakovi"]


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


def test_past_the_days_count_the_form_closes_until_a_day_has_passed(client, register, monkeypatch):
    monkeypatch.setattr(app, "REGISTRATIONS_PER_DAY", 2)
    assert register("anna", "correct horse").url.path == "/parent"
    assert register("bara", "battery staple").url.path == "/parent"
    client.cookies.clear()
    closed = client.get("/register")
    assert closed.status_code == 503
    assert "paused" in closed.text
    assert 'name="login"' not in closed.text
    refused = register("cyril", "zelena kocka")
    assert refused.status_code == 503
    assert "session" not in client.cookies
    assert client.post("/login", data={"login": "anna", "password": "correct horse"}).status_code == 200  # only the form is shut
    client.cookies.clear()
    app.registered_at[0] -= timedelta(days=1, seconds=1)  # anna's registration is a day old now
    assert client.get("/register").status_code == 200
    assert register("cyril", "zelena kocka").url.path == "/parent"


def test_a_refused_registration_does_not_count(client, register, monkeypatch):
    monkeypatch.setattr(app, "REGISTRATIONS_PER_DAY", 1)
    assert register("anna", "short").status_code == 400
    assert register("anna", "correct horse", again="correct house").status_code == 400
    assert register("anna", "correct horse").url.path == "/parent"


def test_a_robot_that_fills_the_hidden_field_is_refused(client, register, monkeypatch):
    monkeypatch.setattr(app, "REGISTRATIONS_PER_DAY", 1)
    assert 'name="website"' in client.get("/register").text
    answer = register("anna", "correct horse", website="https://example.com")
    assert answer.status_code == 400
    assert "did not go through" in answer.text
    assert "session" not in client.cookies
    assert db.connect().execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 0
    assert register("anna", "correct horse", website="").url.path == "/parent"  # and it did not count
