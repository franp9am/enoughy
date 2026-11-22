# TODO

* monitor: drop the rule that the window is at least an hour, in
  `is_hours_window`. It guarded against a mistake that locked the machine before
  a correction could arrive; now any setting is changed or called off from the
  server, so the page's own check, night after day, is enough. Goes with a
  monitor release; until then a shorter window comes back refused.
* server: a second parent joins the family by an invite link from the first
  parent's page; a name typed at registration cannot tell them from a
  stranger.
* server: a parent changes their own password on the page; until then
  `set_password.py` by the maintainer, after proof by a child's token.
* server: test the server against the report of each released monitor
  version, since it has to stay compatible with every one still installed
  (see `DEVELOPING.md`). Due before the first stranger installs.
* server and monitor: a "No night today" button on the dashboard, sent through
  the sync like a grant and pinned to the parent's date, so one delivered
  after midnight expires instead of lifting the next night. A separate key in
  the sync answer, which old monitors ignore; a 0-second grant would show them
  "0 min". The monitor reports `no_night` in its status: missing hides the
  button (too old), true shows "Tonight: no night" whatever lifted it, a code
  included. Unconfirmed, it sits in "Waiting for the next sync"; past its day
  it drops out quietly. Monitor release and server deploy go together.

## Someday / maybe

* monitor: a window whose night starts before its day starts, `["5:00", "1:00"]`,
  is a day that runs past midnight; the daily limit still resets at 0:00. Two
  edits, `is_night_time` and the hour-apart rule; the name stays, an old monitor
  refuses it and the page says so. The settings page can already send the pair.
* installer: take one child off a machine that has several; the uninstaller
  is all or nothing. By hand, untested: delete `data\<child>` and the task
  `EnoughyWidget-<child>`, then reboot. Once tried on the VM, into the
  manual as a power-user line.
* Something with time zones, to be decided: a child may change the zone to
  leave the night or get a fresh limit.
* Full client rewrite in C# with a signed exe installer; the monitor becomes
  a Windows service then.
* Restricted internet, instead of shutdown when the quota ends or as a second
  mode: a firewall rule scoped to the child's account that allows a whitelist
  and nothing else. Maybe Wikipedia alone, maybe limited ChatGPT or Claude.
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
