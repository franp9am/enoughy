# Screen time limit for a child's Windows PC

A daily screen-time limit, a range of allowed hours, and a way to grant extra time.
No cloud account, remote control is optional, can be fully offline.

Simpler to set up than Microsoft Family Safety, simple rules -- no kid surveillance.


## Parts

* `monitor.py` -- runs as SYSTEM from boot, counts the child's session time, shuts the
  machine down when the limit is used up or the allowed hours end. A tick only counts,
  and a shutdown only happens, while the child is logged in with the screen unlocked;
  a locked machine is left alone until somebody unlocks it.
* `config.py` -- what is fixed at install: paths, intervals, the version (read from `VERSION`). `settings.py` --
  what the parent changes: the settings' schema, their validation, the settings file.
  Both next to the monitor in a folder the child cannot read.
  A child is a Windows account, and what the monitor keeps for them is under
  `data\<account>\` there, with what the child may touch under
  `C:\ProgramData\ScreenTimeShared\<account>\`. One child per install for now; the
  layout is ready for more.
* `remaining_time_widget.py` -- a small always-on-top "time left" box in the child's
  session. Cosmetic; the child may hide it with Ctrl+Alt+H or kill it.
* `server/` -- optional web page for the parent, to grant time remotely and see usage.

## Setup on the child's machine

1. Give the child a **non-admin** Windows account.
2. Open PowerShell (type `powershell` in the Start menu; no admin needed) and paste:

   ```powershell
   irm https://raw.githubusercontent.com/franp9am/enoughy/main/bootstrap.ps1 | iex
   ```

   This fetches the latest release, one zip, into a temp folder and starts the installer, which
   re-launches itself as admin and asks which local account is the child's, optionally
   for the child token and URL of the parent's server, and where the "Extra time"
   shortcut goes, probably `C:\Users\<child>\Desktop`.
   Then it downloads its own Python from python.org into `C:\ProgramData\ScreenTimePython`
   (about 13 MB, checked against hashes pinned in the script), copies the monitor into
   `C:\ProgramData\ScreenTime` and locks
   that folder, puts the widget in the shared `C:\ProgramData\ScreenTimeShared`, and
   registers the two scheduled tasks.
3. Reboot. The monitor runs from boot, the widget appears when the child logs in.

A fresh install generates the secret for signing extra-time codes and prints it at the
end -- the parent's machine needs the same one, in `data/secret.txt` next to
`grant_extra_time_offline.py` or in `CHILD_SECRET`. It stays in
`C:\ProgramData\ScreenTime\data\<child>\secret.txt`, which an administrator can read or
replace (reboot afterwards); a reinstall keeps it.

To remove everything, open PowerShell **as administrator** (right-click it in the Start
menu) and paste:

```powershell
irm https://raw.githubusercontent.com/franp9am/enoughy/main/uninstall.ps1 | iex
```

Prefer to see the files first? Download `enoughy.zip` from a release, extract it, and double-click
`install.cmd` or `uninstall.cmd` (the latter takes `-KeepData` to keep the usage history).
The `.cmd` files only hand the matching `.ps1` to PowerShell with `-ExecutionPolicy Bypass`,
which is what lets them run on a machine whose default policy refuses scripts; they change
no setting. The pasted lines need no such help: the policy governs script files, not text.

Upgrading by copying the scripts over is not enough: the monitor refuses to start without
a child folder under `data\`, which only the installer creates. Run the installer again;
over an install older than 0.5 it moves the child's files from `data\` itself into that
folder.

Releasing is in `RELEASING.md`. The URLs above point at `main`, so they stay the same
across releases.

### Safety

The installer does **not** do these, and without them the setup is bypassable:

* password-protect the BIOS, so the machine cannot be booted from another device;
* encrypt the disk with BitLocker, so the drive cannot be read in another machine.

## Settings

The six settings the monitor obeys live in `data/<child>/settings.json`, next to the
monitor where the child cannot read them: `DAILY_LIMIT_SECONDS`, `CARRYOVER` (unused time
rolls over to the next day), `MAX_CARRYOVER_SECONDS`, `ALLOWED_HOURS`, and a different
limit or hours on some weekdays in `DAILY_LIMIT_OVERRIDES` and `ALLOWED_HOURS_OVERRIDES`.
Example:

```json
{
  "DAILY_LIMIT_SECONDS": 3600,
  "CARRYOVER": true,
  "MAX_CARRYOVER_SECONDS": 18000,
  "ALLOWED_HOURS": [6, 21],
  "DAILY_LIMIT_OVERRIDES": {"mon": 1800, "sat": 7200},
  "ALLOWED_HOURS_OVERRIDES": {"fri": [6, 23], "sat": [8, 23]}
}
```

One hour a day, but half an hour on Mondays and two on Saturdays, usable from 6:00 until
21:00 -- the night starts at 21:00 and ends at 6:00 -- except until 23:00 on Fridays and
Saturdays, when it also starts later; with unused time carried over, but never more than
five hours of it. A `MAX_CARRYOVER_SECONDS` of `null` carries everything over, with no
cap. Five minutes before the night the child sees a message; for the time running out
there is none, the widget turns red instead.

`ALLOWED_HOURS` names two moments, when the day starts and when the night starts: `[6, 21]`
allows 6:00 up to 21:00, and at 21:00 the machine shuts down. The second number is the
hour of the shutdown, not the last hour allowed -- `[6, 22]` keeps the machine up until
22:00 -- and `[0, 24]` is no night at all. The two overrides take the days `mon` to `sun`,
each with its own limit in seconds or its own `[day starts, night starts]`; `{}` means
every day is the same. When the machine was off for some days, carryover credits each of
them its own limit.

Edit that file, or let the parent's server set them. Delete it and
the monitor falls back to the defaults in `settings.py`, writing the file again at its
next start.

`settings.py` holds, in its `SETTINGS` dict, the `default` and `allowed` values for the six
above. Those defaults seed `settings.json` on a machine that has none and stand in for any
value in it that is missing or out of range, so a mangled file cannot leave the machine
unrestricted. Read settings through `settings_in_force()`, never straight from `SETTINGS`.
`config.py` holds the rest -- paths, the check interval, the shutdown grace periods.

## Extra time

Two ways, and either works on its own.

**A grant from the server**, if one is set up: the parent enters minutes on the web page
and the monitor picks them up on its next sync, within about a minute. Negative grants
work too, and never outlive the day.

A grant carries no date and never expires: it is applied on the day the machine next
syncs, not the day it was made, so one entered while the PC is off lands whenever the
child next turns it on. For a negative grant that also bounds the damage -- it can take
at most that one day's limit and carryover, and the remainder is dropped rather than
carried into the next day, so -20 h and -6 h cost the same single day.

**A signed code**, for when there is no server. The parent runs
`grant_extra_time_offline.py` and gets `<date>:<seconds>:<signature>`, e.g.
`2026-07-23:3600:a184` for an extra hour. The child pastes it into
`C:\ProgramData\ScreenTimeShared\<child>\extra_time.txt` (the "Extra time" shortcut the
install put on the desktop). The date is only a nonce, not an expiry -- a code stays valid
forever, but each one can be redeemed exactly once.

`grant_extra_time_offline.py` imports nothing else from the project, so copying that
one file to the parent's machine is enough, as long as its `SIGNATURE_CHARS` matches
`config.py` and both machines hold the same secret.

## Optional: the parent's server

FastAPI + SQLite, one page listing the family's children with their usage and a box to
grant time. It never enforces anything -- if it is down, the monitor keeps counting and
shutting down as usual, and grants queue until the machine syncs again.

```
cd server
uv sync
uv run python add_parent.py <login> <family>   # prints the htpasswd line to run next
uv run python add_child.py <family> <name>     # prints the child token for install.ps1
uv run uvicorn app:app --host 127.0.0.1
```

Authentication lives entirely in the reverse proxy in front of it: the proxy checks the
password and passes the verified login to the app in an `X-Remote-User` header, which
decides whose children the page shows. So the app must never be reachable except through
the proxy -- keep it on `127.0.0.1` -- and the proxy must blank that header on anything it
does not authenticate, or a client could name any parent it likes.

The server stays compatible with every monitor version still installed. A child's
machine is only updated by a visit, and even once auto-update ships some machines will
lag a rollout or stay on manual mode, so the window never closes. The server accepts an
old report and sends back only what that version understands.

## Python dependencies

None on the child's machine, and no Python needs to be installed there: the installer
unpacks a private copy of a pinned python.org release for the monitor and the widget,
leaving any Python the parent has alone. Nothing is registered with Windows, so it does
not show up in Apps & Features; `uninstall.cmd` deletes it. To move to a newer release,
change `$PythonVersion` and the four SHA-256 hashes at the top of the Python block in
`install.ps1` and run the installer again. The server has its own dependencies, in
`server/pyproject.toml`.

## Tests

The tests use pytest, which is not installed anywhere in the project; `uv` fetches it
into its own cache for the run. From the repository root:

    uv run --with pytest python -m pytest tests -q

`python -m pytest` rather than plain `pytest`, so the repository root is on the import
path and the tests can `import monitor`.

They cover the monitor's logic and, in `tests/test_main_loop.py`, whole scenarios on a
fake machine. Untested on purpose: `os_tooling` (needs real Windows sessions), `main()`
and the widget's Tk part.

## License

Copyright (c) 2026 Peter Franek. MIT License -- see `LICENSE`.
Use it, change it, sell it; just keep the copyright notice.
