# Screen time limit for a child's Windows PC

A daily screen-time limit, a range of allowed hours, and a way to grant extra time.
No cloud account, remote control is optional, can be fully offline.

Simpler to set up than Microsoft Family Safety, simple rules -- no kid surveillance.

## Setup on the child's machine

1. Give the child a **non-admin** Windows account.
2. Download `enoughy-setup.exe` from the latest release,
   https://github.com/franp9am/enoughy/releases/latest, and run it. It asks for
   administrator rights, which local account is the child's, and optionally for the
   child token and URL of the parent's server. Run it again and pick another account to
   add a second child.
3. Reboot. The monitor runs from boot, the widget with the time left appears when the
   child logs in.

A fresh install prints a secret at the end. It is only for the offline codes, see Extra
time; with a server, ignore it. A reinstall keeps it.

To remove everything, uninstall enoughy in Apps & Features. That removes the tasks,
the folders and the usage history.

### Optional: a stronger lock

For a child who knows computers, two more steps on the machine itself make the limit
hard to get around:

* a BIOS password, so the machine cannot be booted from another device;
* BitLocker disk encryption, so the drive cannot be read in another machine.

## Settings

Six settings, in `C:\ProgramData\Enoughy\data\<child>\settings.json`:

```json
{
  "DAILY_LIMIT_SECONDS": 3600,
  "CARRYOVER": true,
  "MAX_CARRYOVER_SECONDS": 18000,
  "ALLOWED_HOURS": ["6:00", "21:00"],
  "DAILY_LIMIT_OVERRIDES": {"mon": 1800, "sat": 7200},
  "ALLOWED_HOURS_OVERRIDES": {"fri": ["6:00", "23:00"], "sat": ["8:00", "23:00"]}
}
```

One hour a day, but half an hour on Mondays and two on Saturdays, usable from 6:00 until
21:00, except until 23:00 on Fridays and from 8:00 until 23:00 on Saturdays; unused time
is carried over to the next day, but never more than five hours of it.

* `ALLOWED_HOURS` is when the day starts and when the night starts. At the second time
  the machine shuts down: `["6:00", "22:00"]` keeps it up until 22:00. Any minute goes,
  as in `["6:30", "20:10"]`; `null` is no night at all.
* The two overrides take the days `mon` to `sun`; `{}` means every day is the same.
* A `MAX_CARRYOVER_SECONDS` of `null` carries everything over, with no cap.
* Five minutes before the night the child sees a message; before the time runs out
  there is none, the widget turns red instead.

Edit that file, or let the parent's server set the values. A value that is missing or
out of range falls back to its default, so a mangled file cannot leave the machine
unrestricted.

## Extra time

If you use the parent's server, grant the time there and ignore the offline codes
altogether. Without a server, the offline codes are how the child gets more time.

### With the server

The parent enters minutes on the web page and the monitor picks them up within about a
minute, or when the machine is next turned on. Negative minutes take time away, and
never outlive the day. For a longer evening, set a later night in the settings there.

### Offline codes

The parent makes a code on their own machine and the child types it in.

Once: open https://pfranek.cz/enoughy-extra-time.html on the parent's machine. The page
makes the codes in the browser and sends nothing anywhere. Add the child with the
secret from the install, then bookmark the page: name and secret are kept in its
address after `#`, and a second parent gets the same bookmark.

Then, each time, the page makes one of two codes:

* **Extra time:** pick the minutes and get a code such as `2026-07-23:3600:a184`. It
  never expires and works once. The same day and minutes always give the same code, so
  for a second one change the minutes or the day.
* **No night:** the machine stays up until midnight on that one date, and the daily
  limit still counts. It works any number of times that day, and on that day only.

The child opens "Extra time" -- from the desktop, or by typing "extra" in the Start
menu -- and pastes the code; the monitor picks it up within a minute and says so.

## License

Copyright (c) 2026 Peter Franek. GNU AGPL v3 or later -- see `LICENSE`.
Use it, change it, sell it; if you distribute a modified version or run
one as a service, publish its source under the same license.
