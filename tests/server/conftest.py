"""The parent's server, driven in-process: no uvicorn, no browser, and a
fresh database for every test."""
import os
import tempfile

# db.py reads this when it is imported and app.py creates the schema there at
# once; sending that to a temp folder keeps the import away from server/data.
os.environ["ENOUGHY_DB"] = os.path.join(tempfile.mkdtemp(), "import.sqlite")
os.environ.pop("ENOUGHY_INVITE", None)  # registration is open in the tests unless one sets it

import pytest
from fastapi.testclient import TestClient

import app
import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A browser talking to a server whose database is empty.

    Every test gets a new file in its own folder; no test deletes anything."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite")
    db.create_schema()
    # https, or the client would drop the session cookie, which is marked Secure
    return TestClient(app.app, base_url="https://testserver")


@pytest.fixture
def anna_logged_in(client):
    """Anna has just registered, so she is logged in and has no children yet."""
    client.post("/register", data={"login": "anna", "password": "correct horse", "password_again": "correct horse"})
    return client
