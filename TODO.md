# TODO

First is in order and serves one goal. Later is roughly ordered; a new item
goes there unless it hurts a current user or blocks the goal.

## First

The goal: a stranger registers and installs without the maintainer touching
the database.

* server: real login, a session cookie and a login form in place of
  BasicAuth.
* server: registration on the site. A parent creates the account and the
  family, with a password or an emailed login link.
* server + installer: one setup code instead of token and secret; the
  parent's only credential is the login:
  * The parent adds a child on the page. The server makes the token and the
    secret and shows a short code, single use and short-lived.
  * The parent types the code into the installer, which fetches the token
    and the secret. The monitor does not change, and the login password is
    never typed on the child's computer.
  * Offline extra-time codes: the page makes them on the server; a phone
    app later keeps the secret and makes them itself.
  * The price: the server knows the secret. Small, since it already grants
    any time to a syncing child without it.
  * Maybe later: the same signed exe served under a name that carries the
    code, read by the installer to fill the field.
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
* product: fully offline mode, with no account, for a computer that never
  syncs. `parent/extra_time.html` already makes the codes in the browser
  from the secret in its address after `#`; left is the secret's direction.
  * The page generates the secret and the parent types it into the
    installer's setup code field. Longer than a setup code, so the
    installer writes it to `secret.txt` and never contacts the server.
  * The typed secret checks itself: some of its characters are a checksum
    of the rest, so the installer refuses a typo. Length and format to be
    decided; long enough that the child cannot guess it from valid codes.
  * Maybe later: the installer makes the secret and shows the link as a QR
    code, so nothing is typed.

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
