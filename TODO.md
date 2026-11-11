# TODO

* monitor: a window whose night starts before its day starts, `["5:00", "1:00"]`,
  is a day that runs past midnight; the daily limit still resets at 0:00. Two
  edits, `is_night_time` and the hour-apart rule; the name stays, an old monitor
  refuses it and the page says so. The settings page can already send the pair.
* monitor: drop the rule that the window is at least an hour, in
  `is_hours_window`. It guarded against a mistake that locked the machine before
  a correction could arrive; now any setting is changed or called off from the
  server, so the page's own check, night after day, is enough. Goes with a
  monitor release; until then a shorter window comes back refused.
* server: the settings page's times as two dropdowns, hours 0-24 and minutes
  in steps of 5, instead of a time box, which stops at 23:59. Hour 24 locks
  the minutes at 00. `as_clock_time` drops its 24:00-as-23:59 case, which
  today turns a monitor's 24:00 into 23:59 whenever the parent saves the page
  for any other setting. A minute off the steps, set by the installer, shows
  as an extra option so saving keeps it.
* server: a second parent joins the family by an invite link from the first
  parent's page; a name typed at registration cannot tell them from a
  stranger.
* server: a parent deletes their account. Removing the children already
  takes every trace of a child; what stays is a login and a hash, deleted
  by hand on request. Waits for the second parent, which decides whether a
  parent leaves a family or takes it down.
* server: a parent changes their own password on the page; until then
  `set_password.py` by the maintainer, after proof by a child's token.
* installer, admin accounts, left: an account named `parent` already there
  fails the install at "creating the administrator account"; hiding `parent`
  from the login screen is one registry key, not done. The uninstaller leaves
  accounts alone.
* product: a general description of what this is, in Czech and English, for
  the site and the top of the README.
* product: in that manual, an optional step that takes the right to change
  the time zone from standard users. `secpol.msc` on Pro; Home needs a try
  on the test VM.
* server: test the server against the report of each released monitor
  version, since it has to stay compatible with every one still installed
  (see `DEVELOPING.md`). Due before the first stranger installs.
* monitor: a changed time zone, which a standard user may set, moves the
  clock out of the night and rolls the date into a fresh limit. When the
  Windows zone name changes, log an event for the parent's page.
* server: `/children` shows a QR code with the `/extra-time-codes` address for
  every child whose setup code was used, one scan for the parent's phone, as
  the installer shows it for a family without an account. Behind a button: a
  key on the screen is the risk. `/codes` stays for the account parent whose
  child's computer is offline right now; the first manual does not mention it.
* server and monitor: a "No night today" button on the dashboard, sent through
  the sync like a grant and pinned to the parent's date, so one delivered
  after midnight expires instead of lifting the next night. A separate key in
  the sync answer, which old monitors ignore; a 0-second grant would show them
  "0 min". The monitor reports `no_night` in its status: missing hides the
  button (too old), true shows "Tonight: no night" whatever lifted it, a code
  included. Unconfirmed, it sits in "Waiting for the next sync"; past its day
  it drops out quietly. Monitor release and server deploy go together.
* launcher: fetch updates once a day, not once per boot: with Fast Startup
  a Start menu shutdown is a hibernate and the boot task does not fire. No
  service needed, the task's process survives: instead of waiting on the
  monitor, loop, and when a newer release is staged install it and restart
  the monitor, both while it is idle. Reaches installed machines by reinstall,
  the launcher is not in the update set.

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
