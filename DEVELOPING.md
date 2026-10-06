# Developing

For whoever changes the code or runs the server. Releasing is in `RELEASING.md`.

## Parts

* `monitor/` -- runs as SYSTEM from boot, counts the child's session time and shuts the
  machine down. It counts, and shuts down, only while the child is logged in with the
  screen unlocked. `settings.py` is what the parent changes, `config.py` what is fixed.
* `widget/` -- the "time left" box, cosmetic: the child may hide or kill it. Next to it
  `enter_code.py`, the dialog behind the "Extra time" shortcut.
* `parent/` -- `extra_time.html`, the page that makes the offline codes. A copy is served
  at https://pfranek.cz/enoughy-extra-time.html, for now; upload it again when the file
  changes. Its `SIGNATURE_CHARS` must match `config.py`.
* `server/` -- the optional web page for the parent.
* `installer/` -- the Inno Setup script and `build-python.ps1`, which fetches the Python
  the setup bundles.

On the child's machine the monitor is in `C:\ProgramData\Enoughy`, which the child
cannot read, with a folder per child account under `data\`. What the child may touch
is in `C:\ProgramData\EnoughyShared`.

## Rules the README leaves out

* Read settings through `settings_in_force()`, never straight from `SETTINGS`: a value
  that is missing or out of range falls back to its default.
* A grant carries no date: it is applied on the day the machine next syncs. A negative
  one takes at most that day's limit and carryover; the rest is dropped.
* The date in an extra-time code is only a nonce, unless `CHECK_DATE_IN_REDEEM_CODES` in
  `config.py` is on. The date in a no-night code is always checked.
* The shutdown waits three minutes after "time up" and after "Night time"; more time,
  or a later night, arriving in them calls it off.
* The secret for the codes is in `data\<child>\secret.txt`. An administrator can
  replace it; reboot afterwards.

## The parent's server

FastAPI + SQLite. It never enforces anything: if it is down, the monitor keeps counting
and grants queue until the next sync.

```
cd server
uv sync
uv run python add_parent.py <login> <family>   # prints the htpasswd line to run next
uv run python add_child.py <family> <name>     # prints the child token for the setup
uv run uvicorn app:app --host 127.0.0.1
```

Authentication lives entirely in the reverse proxy in front of it, which checks the
password and passes the login in an `X-Remote-User` header. So keep the app on
`127.0.0.1`, and the proxy must blank that header on anything it does not authenticate,
or a client could name any parent it likes.

The server stays compatible with every monitor version still installed: it accepts an
old report and sends back only what that version understands.

## Updates and old installs

`UPDATE_MODE` in `C:\ProgramData\Enoughy` is `auto`, which fetches releases at boot and
is the default with a server token, or `manual`, the default offline. A reinstall keeps
it.

Copying files over is no upgrade: the monitor refuses to start without a child folder
under `data\`, which only the setup creates. For an install older than 0.5,
`install.ps1` from the v0.7.0 release moves the child's files there; the setup does not.

## Tests

    uv run --with pytest python -m pytest tests -q

Untested on purpose: `os_tooling` (needs real Windows sessions), `main()` and the
widget's Tk part.
