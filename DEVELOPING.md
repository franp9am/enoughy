# Developing

For whoever changes the code, runs the server or makes a release.

## Parts

* `monitor/` -- runs as SYSTEM from boot, counts the child's session time and shuts the
  machine down. It counts, and shuts down, only while the child is logged in with the
  screen unlocked. `settings.py` is what the parent changes, `config.py` what is fixed.
* `widget/` -- the "time left" box, cosmetic: the child may hide or kill it. Next to it
  `enter_code.py`, the dialog behind the "Extra time" shortcut.
* `parent/` -- `extra_time.html`, the page that makes the offline codes. The server
  serves it at `/extra-time-codes`, without login. Its `SIGNATURE_CHARS` must match `config.py`.
* `server/` -- the parent's server, with the dashboard that gives dashboard mode its
  name. An install in offline mode never contacts one.
* `installer/` -- the Inno Setup script and `build-python.ps1`, which fetches the Python
  the setup bundles. `qrcodegen.py` is Project Nayuki's QR encoder, v1.8.0, vendored as it
  is; `qr_bmp.py` draws the codes page's QR with it on that Python, at the end of an install.

On the child's machine the code is in `C:\Program Files\enoughy`, which everyone reads
and only administrators and SYSTEM write: the launcher, the starter, Python, and a
release folder, `v<version>`, with the monitor, the widget and the dialog. The data is
in `C:\ProgramData\Enoughy`, which the child cannot read, a folder per child account
under `data\`. What the child may touch is their own folder in
`C:\ProgramData\EnoughyShared`.

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

A parent removes their whole family at the bottom of their page, after typing the
password again; `remove_family.py <login>` does the same for the maintainer.

A password has to take at least ten million guesses by the estimate of zxcvbn, at
`/register` and in `set_password.py` alike; no rules about its characters. zxcvbn
knows English words only, so `czech_words.txt` gives it the Czech ones: some 560
picked by hand, then the 10 000 most frequent in the public-domain sentences of
Mozilla Common Voice.

Live it is https://enoughy.com, also answering as enoughy.cz, www of both and the
older marwin.pfranek.cz, which also answers as www, one certificate for all six: the clone in `~/enoughy`, the
database `server/data/enoughy.sqlite`, the systemd unit `enoughy`, nginx proxying to
port 8000 with rate limits, which are also all that stands between a guesser and
`/login` or `/api/setup`. A cookie belongs to one host name, so each name is its own
login. A deploy is `git pull` and `sudo systemctl restart enoughy`; the unit runs
`uv run`, which installs a new dependency by itself. A new column goes into the live
database by hand with `ALTER TABLE` before the restart, since `CREATE TABLE IF NOT
EXISTS` never touches an existing table.

The dashboard lists the children whose machine has synced at least once. `/codes`
makes offline extra-time codes with the same signing as `parent/extra_time.html`, under
the child's `secret`, random and made with the child. The install must hold that same
key in `secret.txt`: the setup code will put it there; until then by hand, and a child
from before the column has it copied the other way, from the install into the row.

The server stays compatible with every monitor version still installed: it accepts an
old report and sends back only what that version understands.

## Updates and old installs

`UPDATE_MODE` in `C:\ProgramData\Enoughy` is `auto`, which fetches releases once a day and
is the default in dashboard mode, or `manual`, the default in offline mode. A reinstall keeps
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
machine fetches once a day, and the setup exe for a fresh install.

Needs: the private key at `~\.enoughy\release_key.pfx`, `gh` logged in, `iscc` on the
PATH, SimplySign Desktop connected, a clean tree on `main`, pushed.

From a PowerShell in the repo folder:

    powershell -ExecutionPolicy Bypass -File .\release.ps1 0.9.0 "What changed"

It writes the version into `monitor/VERSION`, the only place it is written, and
commits and pushes that. `-NoSign` leaves the setup exe unsigned.

On the machine `launcher.ps1`, the boot task, keeps the monitor running from the release
folder with the highest version and every ten minutes runs that folder's `update.ps1`,
which once a day fetches the latest release. A newer one it unpacks into `update.tmp`
and renames to `v<version>`: no file is copied and none of a running release written
over, so a folder with a version for a name is whole, whenever the power goes. The
launcher then restarts the monitor from the new folder, whose updater removes the older
ones at its first run. The widget task and the "Extra time" shortcuts go through
`run_latest.py`, the starter, which runs the widget or the dialog from the highest
folder too; a widget already running stays as it is until the child's next logon.

A release brings all of a release folder: the monitor, the widget, the dialog, the key
and `update.ps1`. Never the launcher or the starter: those, Python and the scheduled
tasks change only by running the setup again. A release whose `update.ps1` is broken
cuts its machines off until the setup is run there, so the launcher test installs a
second release with the updater the first one brought.

Installs up to 1.3.2 have everything under `C:\ProgramData`, the monitor's files in
`Enoughy` itself, and a launcher of their own. That goes on taking the monitor and the
widget out of each release, at boot; for the layout above, which came with 1.4.0, such
a machine needs the setup once more. That setup keeps the
children and their data, but its settings page shows the defaults, not the child's
values, since the old Python is not where it looks; and the old files stay, unused.

Never tag by hand: a tag without a release behind it is invisible to the updater.
A release is never moved; a fix is a new version. To take one back before anyone
has it:

    gh release delete v0.6.0 --yes --cleanup-tag
