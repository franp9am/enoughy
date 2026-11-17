"""A release folder is made in two places, by the setup and by release.ps1's
zip, which update.ps1 unpacks; both must put the same files into it."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_the_setup_and_the_zip_put_the_same_files_into_a_release_folder():
    setup = re.findall(r'^Source: "[^"]*\\([^"\\]+)"; +DestDir: "\{#ReleaseDir\}"', (REPO / "installer" / "installer.iss").read_text(), re.M)
    staging = re.search(r'^Copy-Item (.*\n.*) "\$stage\\files"$', (REPO / "release.ps1").read_text(), re.M).group(1)
    zipped = re.findall(r'\\([^"\\]+)"', staging) + ["VERSION"]  # $VersionFile, the one named by a variable
    assert sorted(setup) == sorted(zipped)
    assert "monitor.py" in zipped and "enter_code.py" in zipped  # the patterns found something
