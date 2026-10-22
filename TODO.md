# TODO

First is in order and serves one goal. Later is roughly ordered; a new item
goes there unless it hurts a current user or blocks the goal.

## First

The goal: a stranger registers and installs without the maintainer touching
the database.

* server: a parent deletes the family and everything under it from the
  page, since the server holds a child's usage by name.
* server: settings UI, a widget per setting, keyed by name (durations, hour
  picker, weekday sliders over `DAILY_LIMIT_OVERRIDES`); unknown names fall
  back to the JSON box, so a monitor reporting a new setting works on day
  one. The client stays the validator. A name's meaning never changes, new
  meaning means new name. First the widgets for what the current monitor
  reports; the server test that every widget name exists in the client's
  `SETTINGS` once there is a second name. Without this a parent meets the
  JSON box at the first change, which is where a nontechnical one stops.
* server: the same principle for `settings_in_words`, which hardcodes the
  five setting names: a renamed, missing or malformed setting is a 500 on
  both `/` and `/settings` for that child. Render the compact line only when
  the known names fit, else fall back to plain `name=value`.
* monitor: send the day's whole `event_log` and the last `crash.log` entry
  with each sync, so debugging works from the server page without machine
  access; cap the crash log at 1 MB (rename to `.old`) and read only its
  tail.

## Later

* server: a second parent joins the family by an invite link from the first
  parent's page; a name typed at registration cannot tell them from a
  stranger.
* server: a parent changes their own password on the page; until then
  `set_password.py` by the maintainer, after proof by a child's token.
* installer, admin accounts, left: an account named `parent` already there
  fails the install at "creating the administrator account"; hiding `parent`
  from the login screen is one registry key, not done. The uninstaller leaves
  accounts alone.
* product: a general description of what this is, in Czech and English, for
  the site and the top of the README.
* product: a parent's manual: creating an account, adding children,
  installing on the child's machine. The README covers the install for now.
* product: in that manual, an optional step that takes the right to change
  the time zone from standard users. `secpol.msc` on Pro; Home needs a try
  on the test VM.
* server: test the server against the report of each released monitor
  version, since it has to stay compatible with every one still installed
  (see `DEVELOPING.md`). Due before the first stranger installs.
* server: logging.
* monitor: a changed time zone, which a standard user may set, moves the
  clock out of the night and rolls the date into a fresh limit. When the
  Windows zone name changes, log an event for the parent's page.
* server: `/children` shows a QR code with the `/extra-time-codes` address for
  every child whose setup code was used, one scan for the parent's phone, as
  the installer shows it for a family without an account. Behind a button: a
  key on the screen is the risk. `/codes` stays for the account parent whose
  child's computer is offline right now; the first manual does not mention it.
* installer: the same signed exe served under a name that carries the setup
  code, read by the installer to fill the field.

* site: enoughy.com is the address since 2026-10-11; enoughy.cz, www and the
  old marwin.pfranek.cz answer too. Once the description exists, `/` shows it
  to a stranger and the overview to a parent, and the other names redirect the
  page paths only: installed monitors sync to marwin.pfranek.cz, and urllib
  turns a redirected POST into a GET.

## Someday / maybe

* Delay a time zone change, if the events show anyone using the trick: count
  by the old UTC offset for 24 hours, with night when either offset says so.
* Full client rewrite in C# with a signed exe installer; the monitor becomes
  a Windows service then.
* Restricted internet, instead of shutdown when the quota ends or as a second
  mode: a firewall rule scoped to the child's account that allows a whitelist
  and nothing else. Maybe Wikipedia alone, maybe limited ChatGPT or Claude.
* A carryover change from the server counts a day late: the day file, with
  its carryover, is created before the day's first sync.
* Several devices for one child, sharing one budget. Server-side only,
  through the existing grants: every device keeps counting and shutting down
  on its own, and the server turns one device's usage into a negative grant
  for its siblings, so all of them converge on the same remaining within a
  tick. Grants and settings changes become addressed to the child, delivered
  and answered per device; `children` splits into `children` and `devices`,
  which own the token and the status rows. No monitor or protocol change, so
  every installed version keeps working. Two devices on at once cost double,
  as an unlocked idle session does today. Offline mode cannot share anything:
  a second install there is a second child, which is also the answer to give
  until a customer asks for more. Not before the server is tested against a
  recorded 0.1.0 sync.
