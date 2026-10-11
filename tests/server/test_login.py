"""A parent is whoever knows a parent's password, and stays one by the cookie."""
import pytest

import add_parent
import app
import db


def test_right_password_names_the_parent(client):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", "novak", password="correct horse")
    parent = app.parent_for_login(connection, "anna", "correct horse")
    assert parent is not None
    assert parent.login == "anna"


def test_wrong_password_names_nobody(client):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", "novak", password="correct horse")
    assert app.parent_for_login(connection, "anna", "wrong") is None


def test_right_password_under_another_login_names_nobody(client):
    connection = db.connect()
    add_parent.add_parent(connection, "anna", "novak", password="correct horse")
    assert app.parent_for_login(connection, "petr", "correct horse") is None


def test_parent_with_no_password_yet_cannot_log_in(client):
    connection = db.connect()
    add_parent.family_id(connection, "novak")
    connection.execute("INSERT INTO parents (login, family_id, password_hash) VALUES ('anna', 1, '')")
    connection.commit()
    assert app.parent_for_login(connection, "anna", "") is None
    assert app.parent_for_login(connection, "anna", "anything") is None


def test_empty_password_is_refused(client):
    connection = db.connect()
    with pytest.raises(ValueError):
        add_parent.add_parent(connection, "anna", "novak", password="")


@pytest.fixture
def anna(client):
    """Anna, with a password and a child, not yet logged in."""
    connection = db.connect()
    add_parent.add_parent(connection, "anna", "novak", password="correct horse")
    connection.execute(
        "INSERT INTO children (family_id, name, token) VALUES (1, 'Tom', 'tom-token')"
    )
    connection.commit()
    connection.close()


def test_without_login_the_page_sends_to_the_form(client, anna):
    answer = client.get("/", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/login"


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
    client.get("/logout")
    answer = client.get("/", follow_redirects=False)
    assert answer.headers["location"] == "/login"


def test_made_up_cookie_is_no_login(client, anna):
    client.cookies.set("session", "a-value-the-server-never-issued")
    answer = client.get("/", follow_redirects=False)
    assert answer.headers["location"] == "/login"
