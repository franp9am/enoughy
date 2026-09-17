# TODO

Ordered by importance within each section.

## Client / monitor

* Auto-update is built (`launcher.ps1`, `release.ps1`, the installer wiring)
  but no release exists yet. Left: `gh` on the release machine, the first
  release, one reinstall on each machine installed before it, and the README
  and `bootstrap.ps1`, which still describe the old task. Migrations live in
  the monitor's start; the launcher only copies files.
* Per-weekday override for the allowed hours, like `DAILY_LIMIT_OVERRIDES` does
  for the limit, e.g. later on Friday and Saturday.
* Send recent `event_log` lines (or at least the last caught exception) with each
  sync, so debugging works from the server page without machine access.
* Time zone is changeable by a standard user, which rolls `datetime.now()` into
  a new date and a fresh daily limit.
* The same atomic write (temp file + `os.replace`) is copied all over; it wants
  one shared home.
* Split `config.py` into config and settings. Config is what is fixed at install:
  paths, intervals, the version, the update mode. Settings are what the parent
  changes from the server: schema, validation, the file, `get_config` renamed to
  say what it returns. The installer's file list in `install.ps1` must name the
  new module.
* Several children on one machine. The per-child layout is there since 0.5.
  Left: the installer adding a child next to the ones there (one widget task
  each, the monitor task kept); `icacls` locking each child's shared folder to
  that account. The pre-0.5 layout move goes once no such machine remains.
* Install and uninstall exe, no powershell, certificate, test easy install

## Server-side

* Test the server against the report of each released monitor version, since
  it has to stay compatible with every one still installed (see the README).
* `settings_in_words` hardcodes the five setting names, while the rest of the
  settings path takes names and types from whatever the child reports. A
  renamed, missing or malformed setting is a 500 on both `/` and `/settings` for
  that child. Render the compact line only when the known names fit, else fall
  back to plain `name=value`.
* Settings UI: a widget per setting, keyed by name (durations, hour picker,
  weekday sliders over `DAILY_LIMIT_OVERRIDES`); unknown names fall back to the
  JSON box. The client stays the validator. A name's meaning never changes,
  new meaning means new name; a server test checks every widget name exists
  in the client's `SETTINGS`.
* Real login: replace BasicAuth with a session cookie and a login form.
* Server logging.
* One-step release. Today it is three edits: `MONITOR_VERSION` in `config.py`,
  `$Ref` in `bootstrap.ps1`, then the tag. Let the tag be the only source:
  `bootstrap.ps1` asks the GitHub API for the latest release instead of carrying
  a pin, and the monitor reads its version from a file written at release time.
  `release.ps1` already zips, signs and uploads; it refuses a tag that config.py
  does not agree with until then.
* Simplify installation: family, parent and child creation in the DB and the
  corresponding logins, with less effort from the maintainer.

## Product, once mature

* A general description of what this is, in Czech and English, for the site
  and the top of the README.
* A parent's manual: creating an account, adding children, installing on the
  child's machine. The README covers the install for now.

## Someday / maybe

* Full client rewrite in C# with a signed exe installer; the monitor becomes
  a Windows service then.
* The parent's page warns when a machine has not reported for a day.
* Restricted internet, instead of shutdown when the quota ends or as a second
  mode: a firewall rule scoped to the child's account that allows a whitelist
  and nothing else. Maybe Wikipedia alone, maybe limited ChatGPT or Claude.
