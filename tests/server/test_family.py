"""A parent removes their whole family from the server, confirmed with the password."""
import db

TABLES = ("families", "parents", "sessions", "children", "status", "grants", "settings_changes", "setup_codes")
REPORT = {"date": "2026-10-12", "time_spent_sec": 600, "carryover_sec": 0, "granted_sec": 0,
          "remaining_sec": 3000, "last_tick": None, "applied_grant_ids": []}


def rows(table: str) -> int:
    return db.connect().execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def monitor_of_the_only_child() -> dict:
    token = db.connect().execute("SELECT token FROM children").fetchone()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_the_page_names_the_family_that_would_go(anna_logged_in):
    page = anna_logged_in.get("/parent").text
    assert "Remove family from server" in page
    popup = " ".join(page.split("<dialog")[1].split())
    assert "The family <strong>anna</strong>, with all its parents and children, will be gone" in popup
    assert 'getElementById("remove-family").showModal()' not in page  # the popup waits for the button


def test_the_right_password_removes_every_trace_and_logs_out(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    monitor = monitor_of_the_only_child()
    assert anna_logged_in.post("/api/sync", json=REPORT, headers=monitor).status_code == 200
    anna_logged_in.post("/grants", data={"child_id": 1, "minutes": 10})
    answer = anna_logged_in.post("/family/delete", data={"password": "correct horse"})
    assert 'href="https://testserver/register"' in answer.text  # logged out, so the front page
    for table in TABLES:
        assert rows(table) == 0, table
    assert anna_logged_in.post("/api/sync", json=REPORT, headers=monitor).status_code == 401
    login = anna_logged_in.post("/login", data={"login": "anna", "password": "correct horse"})
    assert login.status_code == 401


def test_a_wrong_password_removes_nothing_and_says_so(anna_logged_in):
    anna_logged_in.post("/children", data={"name": "Tom"})
    answer = anna_logged_in.post("/family/delete", data={"password": "wrong horse"})
    assert answer.url.path == "/parent"  # back on the page, still logged in
    assert "That is not your password" in answer.text
    assert 'getElementById("remove-family").showModal()' in answer.text  # the popup is open again
    assert rows("families") == rows("parents") == rows("children") == 1
    assert anna_logged_in.get("/parent").status_code == 200  # still logged in


def test_the_other_families_stay(anna_logged_in, client):
    anna_logged_in.post("/children", data={"name": "Tom"})
    client.get("/logout")
    client.post("/register", data={"login": "bob", "password": "battery staple", "password_again": "battery staple"})
    client.post("/children", data={"name": "Eva"})
    client.post("/family/delete", data={"password": "battery staple"})
    connection = db.connect()
    assert [row["login"] for row in connection.execute("SELECT login FROM parents")] == ["anna"]
    assert [row["name"] for row in connection.execute("SELECT name FROM children")] == ["Tom"]
    assert rows("families") == 1


def test_removing_a_family_needs_a_login(client):
    answer = client.post("/family/delete", data={"password": "correct horse"}, follow_redirects=False)
    assert answer.headers["location"] == "/login"
