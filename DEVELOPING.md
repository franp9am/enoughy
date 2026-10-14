# Developing

For whoever changes the code, runs the server or makes a release.

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
* A code (`60:ab12`, `nn:ab12`) carries no date: the signature is of today's date and
  the code, so it is good on the day it was made only. The monitor empties
  `extra_time.txt` at every check, so a code is judged once; the day's json lists the
  codes it granted.
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
uv run uvicorn app:app --host 127.0.0.1
```

A parent registers at `/register` and adds children on the page, which shows the token
for the setup; `add_parent.py` and `add_child.py` do the same from the command line.
With `ENOUGHY_INVITE` set in the service's environment, `/register` opens only from a
link that carries it, `/register?invitation=<value>`; unset, registration is open.
No email is collected, so there is no password recovery: a parent who lost theirs
writes to the maintainer and proves the family with a child's token, the only thing
both they and the server know, and `set_password.py <login>` sets a new one. A parent logs in at `/login` with the
password stored as a bcrypt hash;
a row in `sessions` and a `session` cookie keep them logged in for 90 days or until
`/logout` deletes the row. The cookie is marked `Secure`, so the site must be https;
browsers make an exception for `127.0.0.1`, which is how the server runs locally. The
reverse proxy in front only forwards.

Live it is https://enoughy.com, also answering as enoughy.cz, www of both and the
older marwin.pfranek.cz, one certificate for all five: the clone in `~/enoughy`, the
database `server/data/enoughy.sqlite`, the systemd unit `enoughy`, nginx proxying to
port 8000 with rate limits. A cookie belongs to one host name, so each name is its own
login. A deploy is `git pull` and `sudo systemctl restart enoughy`; the unit runs
`uv run`, which installs a new dependency by itself. A new column goes into the live
database by hand with `ALTER TABLE` before the restart, since `CREATE TABLE IF NOT
EXISTS` never touches an existing table.

The dashboard lists the children whose machine has synced at least once. `/codes`
makes offline extra-time codes with the same signing as `parent/extra_time.html`, under
a key the server derives from the family's secret and the child's name (`child_key`),
which is why a child's name never changes. The install must hold that same key in
`secret.txt`: the setup code will put it there; until then by hand, for a family whose
`secret` was set by hand too.

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

    uv run --project server pytest -q

The server's environment runs the whole suite, since the server tests drive the
app in-process and need its packages; the monitor tests need none.

Untested on purpose: `os_tooling` (needs real Windows sessions), `main()` and the
widget's Tk part.

## Releasing

A release is a signed zip of what a child's machine runs, which every installed
launcher fetches at boot, and the setup exe for a fresh install.

Needs: the private key at `~\.enoughy\release_key.pfx`, `gh` logged in, `iscc` on the
PATH, SimplySign Desktop connected, a clean tree on `main`, pushed.

From a PowerShell in the repo folder:

    powershell -ExecutionPolicy Bypass -File .\release.ps1 0.9.0 "What changed"

It writes the version into `monitor/VERSION`, the only place it is written, and
commits and pushes that. `-NoSign` leaves the setup exe unsigned.

An update leaves the launcher and Python alone; only running the setup again changes
them.

Never tag by hand: a tag without a release behind it is invisible to the launcher.
A release is never moved; a fix is a new version. To take one back before anyone
has it:

    gh release delete v0.6.0 --yes --cleanup-tag
