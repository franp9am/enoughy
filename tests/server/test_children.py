"""A parent adds a child on the page and gets the token for the setup."""
import db


def test_adding_a_child_shows_it_with_its_token(anna_logged_in):
    answer = anna_logged_in.post("/children", data={"name": "Tom"})
    assert answer.status_code == 200  # followed the redirect back to /children
    assert "Tom" in answer.text
    token = db.connect().execute("SELECT token FROM children").fetchone()["token"]
    assert len(token) == 32
    assert token in answer.text


def test_a_second_child_of_the_same_name_is_refused(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    answer = anna_logged_in.post("/children", data={"name": "Tom"})
    assert answer.status_code == 400


def test_a_nameless_child_is_refused(anna_logged_in):
    answer = anna_logged_in.post("/children", data={"name": "  "})
    assert answer.status_code == 400


def test_adding_a_child_needs_a_login(client):
    answer = client.post("/children", data={"name": "Tom"}, follow_redirects=False)
    assert answer.headers["location"] == "/login"


def test_the_dashboard_shows_the_child_but_not_the_token(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    token = db.connect().execute("SELECT token FROM children").fetchone()["token"]
    page = anna_logged_in.get("/")
    assert "Tom" in page.text
    assert token not in page.text
