# Releasing

For the maintainer. A release is one signed zip on GitHub holding everything a
child's machine receives: the monitor files, the widget, the launcher, the
installer. A fresh install downloads it and runs the installer from it; every
installed launcher fetches it at boot and takes the monitor files out of it.

Needs: the private key at `~\.enoughy\release_key.pfx` (release_key.cer in the
repo is its public half), `gh` logged in, a clean tree on `main`, pushed.

1. Write the new version in `VERSION`. Commit, push.
2. From a PowerShell in the repo folder:

       powershell -ExecutionPolicy Bypass -File .\release.ps1 "What changed, in a sentence for the parent."

   It tags the commit `v<version>` with the notes, pushes the tag, signs the zip and
   publishes the release with it. It refuses a version that is released already.

A fresh install and an update both take the latest release, so publishing it is
the whole release. What an update leaves alone, since only a reinstall changes it:
the launcher, the installer, Python.

Never tag by hand: a tag without a release behind it is invisible to the launcher,
and the script refuses a name that exists.

A release is never moved; a fix is a new version. To take one back before anyone
has it:

    gh release delete v0.6.0 --yes --cleanup-tag

which removes the release and the tag, remote and local.

`VERSION` is the only place the version is written. `config.py` reads it for the
monitor's reports, the installer copies it next to the launcher, `release.ps1`
tags from it and ships it in the zip, and the launcher compares the shipped one
with the installed one.

