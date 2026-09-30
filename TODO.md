# TODO

Ordered by importance within each section.

## Client / monitor

* Send the day's whole `event_log` and the last `crash.log` entry with each
  sync, so debugging works from the server page without machine access; cap
  the crash log at 1 MB (rename to `.old`) and read only its tail.
* A changed time zone, which a standard user may set, moves the clock out of the
  night and rolls the date into a fresh limit. Cheap first step: keep the UTC
  offset in the day file, and on a change log an event and charge the tick by
  the old offset, so the parent sees it on the page the same day.

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
* Simplify installation: family, parent and child creation in the DB and the
  corresponding logins, with less effort from the maintainer.

## Product, once mature

* A general description of what this is, in Czech and English, for the site
  and the top of the README.
* A parent's manual: creating an account, adding children, installing on the
  child's machine. The README covers the install for now.

## Someday / maybe

* Time on a base the child cannot move: account in UTC and treat the local
  offset as data, DST included. Nontrivial, and the trick is rare; the event
  above shows whether anyone uses it.
* Full client rewrite in C# with a signed exe installer; the monitor becomes
  a Windows service then.
* Restricted internet, instead of shutdown when the quota ends or as a second
  mode: a firewall rule scoped to the child's account that allows a whitelist
  and nothing else. Maybe Wikipedia alone, maybe limited ChatGPT or Claude.
* A carryover change from the server counts a day late: the day file, with
  its carryover, is created before the day's first sync.
