"""Run the parent's server locally, without nginx.

Every request arrives as if the proxy had authenticated the parent "peter"
(or whoever DEV_PARENT names). From this folder:

    uv run --with tzdata uvicorn dev:app --reload

then open http://127.0.0.1:8000. The database is server/data/child_control.sqlite
unless CHILD_CONTROL_DB says otherwise. --with tzdata is for Windows, which has
no time zone database of its own.

Never deploy this: it is the exact hole DEVELOPING.md warns about.
"""
import os

from app import app as real_app

LOGIN = os.environ.get("DEV_PARENT", "peter")


async def app(scope, receive, send):
    if scope["type"] == "http":
        headers = [(k, v) for k, v in scope["headers"] if k != b"x-remote-user"]
        scope = {**scope, "headers": headers + [(b"x-remote-user", LOGIN.encode())]}
    await real_app(scope, receive, send)
