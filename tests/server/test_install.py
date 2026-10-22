"""enoughy.com/install is what a parent types on the child's computer."""
import app


def test_install_sends_the_browser_to_the_newest_release(client):
    answer = client.get("/install", follow_redirects=False)
    assert answer.status_code == 302
    assert answer.headers["location"] == app.INSTALLER_URL
    assert answer.headers["location"].endswith("/releases/latest/download/enoughy-setup.exe")
