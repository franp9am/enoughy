# Releasing

For the maintainer. A release is one signed zip on GitHub holding what a child's
machine runs: the monitor files, the widget, the launcher. Every installed launcher
fetches it at boot and takes the monitor files and the widget out of it. Next to it
goes the setup exe, which a fresh install downloads.

Needs: the private key at `~\.enoughy\release_key.pfx` (`monitor/release_key.cer`
is its public half), `gh` logged in, a clean tree on `main`, pushed.

1. Write the new version in `monitor/VERSION`. Commit, push.
2. From a PowerShell in the repo folder:

       powershell -ExecutionPolicy Bypass -File .\release.ps1 "What changed, in a sentence for the parent."

   It tags the commit `v<version>` with the notes, pushes the tag, signs the zip and
   publishes the release with it. It refuses a version that is released already.
3. The setup exe, until `release.ps1` builds and uploads it: from the same commit,
   `installer\build-python.ps1` once per Python version, then `iscc installer\installer.iss`
   (Inno Setup 6, a per-user install under `AppData\Local\Programs`), then

       gh release upload v<version> installer\dist\enoughy-setup.exe

A fresh install and an update both take the latest release, so publishing it is
the whole release. What an update leaves alone, since only running the setup again
changes it: the launcher and Python.

Never tag by hand: a tag without a release behind it is invisible to the launcher,
and the script refuses a name that exists.

A release is never moved; a fix is a new version. To take one back before anyone
has it:

    gh release delete v0.6.0 --yes --cleanup-tag

which removes the release and the tag, remote and local.

`monitor/VERSION` is the only place the version is written. `config.py` reads it for the
monitor's reports, the setup copies it next to the launcher and shows it in Apps &
Features, `release.ps1` tags from it and ships it in the zip, and the launcher compares
the shipped one with the installed one.

