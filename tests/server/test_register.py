"""A stranger registers and is logged in, without the maintainer touching anything."""
import add_parent
import db


def test_registering_logs_the_parent_in(client):
    answer = client.post("/register", data={"login": "anna", "password": "correct horse"})
    assert answer.status_code == 200  # followed the redirect to /
    assert "session" in client.cookies
    assert "anna" in answer.text  # the name in the corner of the page


def test_a_taken_login_shows_the_form_again(client):
    add_parent.add_parent(db.connect(), "anna", password="correct horse")
    answer = client.post("/register", data={"login": "anna", "password": "another one"})
    assert answer.status_code == 400
    assert "anna is taken" in answer.text
    assert "session" not in client.cookies


def test_a_short_password_shows_the_form_again(client):
    answer = client.post("/register", data={"login": "anna", "password": "short"})
    assert answer.status_code == 400
    assert "at least 8 characters" in answer.text
    assert "session" not in client.cookies


def test_set_password_changes_it_and_logs_the_parent_out(anna_logged_in, monkeypatch):
    import set_password
    monkeypatch.setattr("sys.argv", ["set_password.py", "anna"])
    monkeypatch.setattr("getpass.getpass", lambda prompt: "a new password")
    set_password.main()
    assert anna_logged_in.get("/", follow_redirects=False).headers["location"] == "/login"
    answer = anna_logged_in.post("/login", data={"login": "anna", "password": "a new password"})
    assert answer.status_code == 200
