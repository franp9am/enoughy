# Releasing

For the maintainer. A release is a signed zip of what a child's machine runs, which
every installed launcher fetches at boot, and the setup exe for a fresh install.

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
