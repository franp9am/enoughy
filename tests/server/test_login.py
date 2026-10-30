"""A parent is whoever knows a parent's password, and stays one by the cookie."""
import pytest

import add_parent
import auth
import db


def test_right_password_names_the_parent(client):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    parent = auth.parent_from_credentials(connection, "anna", "correct horse")
    assert parent is not None
    assert parent.login == "anna"


def test_wrong_password_names_nobody(client):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    assert auth.parent_from_credentials(connection, "anna", "wrong") is None


def test_right_password_under_another_login_names_nobody(client):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    assert auth.parent_from_credentials(connection, "petr", "correct horse") is None


def test_parent_with_no_password_yet_cannot_log_in(client):
    connection = db.connect()
    add_parent.family_id(connection, "novak")
    connection.execute("INSERT INTO parents (login, family_id, password_hash) VALUES ('anna', 1, '')")
    connection.commit()
    assert auth.parent_from_credentials(connection, "anna", "") is None
    assert auth.parent_from_credentials(connection, "anna", "anything") is None


def test_short_password_is_refused(client):
    connection = db.connect()
    with pytest.raises(ValueError):
        add_parent.add_parent(connection, "anna", password="short")


def test_a_new_parent_gets_a_family_named_after_them(client):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    family = connection.execute(
        "SELECT families.name FROM parents JOIN families ON families.id = family_id"
        " WHERE login = 'anna'"
    ).fetchone()
    assert family["name"] == "anna"


@pytest.fixture
def anna(client):
    """Anna, with a password and a child whose machine has synced, not yet logged in."""
    connection = db.connect()
    add_parent.add_parent(connection, "anna", password="correct horse")
    connection.executescript("""
        INSERT INTO children (id, family_id, name, token) VALUES (1, 1, 'Tom', 'tom-token');
        INSERT INTO status (child_id, date, time_spent_sec, remaining_sec, updated_at)
            VALUES (1, '2026-10-11', 600, 3000, '2026-10-11T10:00:00+00:00');
    """)
    connection.close()


def test_without_login_the_front_page_is_about_enoughy(client, anna):
    answer = client.get("/", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/intro"
    answer = client.get("/intro")
    assert answer.status_code == 200
    assert 'href="https://testserver/register"' in answer.text
    assert "Tom" not in answer.text


def test_without_login_the_old_address_shows_the_form(client, anna):
    answer = client.get("https://marwin.pfranek.cz/", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/login"


def test_the_three_pages_behind_the_front_page_are_public(client, anna):
    for path, heading in (("/how", "How it works"), ("/why", "Why this one"), ("/setup", "Setting it up")):
        answer = client.get(path)
        assert answer.status_code == 200
        assert heading in answer.text
        assert 'href="https://testserver/intro">' in answer.text  # back to the front page


def test_without_login_a_parent_page_sends_to_the_form(client, anna):
    answer = client.get("/parent", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/login?next=%2Fparent"


def test_login_returns_to_the_page_asked_for(client, anna):
    sent_away = client.get("/parent", follow_redirects=False)
    assert sent_away.headers["location"] == "/login?next=%2Fparent"
    answer = client.post(
        "/login", data={"login": "anna", "password": "correct horse", "next": "/parent"},
        follow_redirects=False,
    )
    assert answer.headers["location"] == "/parent"


def test_login_never_sends_to_another_site(client, anna):
    answer = client.post(
        "/login", data={"login": "anna", "password": "correct horse", "next": "https://evil.example/"},
        follow_redirects=False,
    )
    assert answer.headers["location"] == "/"


def test_wrong_password_shows_the_form_again(client, anna):
    answer = client.post("/login", data={"login": "anna", "password": "wrong"})
    assert answer.status_code == 401
    assert "Wrong login or password" in answer.text
    assert "session" not in client.cookies


def test_login_shows_the_children(client, anna):
    answer = client.post("/login", data={"login": "anna", "password": "correct horse"})
    assert answer.status_code == 200  # the client followed the redirect to /
    assert "Tom" in answer.text
    assert "session" in client.cookies


def test_the_cookie_opens_the_page_on_later_visits(client, anna):
    client.post("/login", data={"login": "anna", "password": "correct horse"})
    answer = client.get("/")  # the client sends the cookie it was given
    assert answer.status_code == 200
    assert "Tom" in answer.text


def test_logout_ends_the_session(client, anna):
    client.post("/login", data={"login": "anna", "password": "correct horse"})
    assert client.get("/logout", follow_redirects=False).headers["location"] == "/"
    answer = client.get("/parent", follow_redirects=False)
    assert answer.headers["location"] == "/login?next=%2Fparent"


def test_made_up_cookie_is_no_login(client, anna):
    client.cookies.set("session", "a-value-the-server-never-issued")
    answer = client.get("/parent", follow_redirects=False)
    assert answer.headers["location"] == "/login?next=%2Fparent"


def test_a_parent_can_still_read_the_front_page_without_the_register_button(client, anna):
    client.post("/login", data={"login": "anna", "password": "correct horse"})
    answer = client.get("/intro")
    assert answer.status_code == 200
    assert 'href="https://testserver/register"' not in answer.text
    assert 'href="https://testserver/parent"' in answer.text  # the session pill
