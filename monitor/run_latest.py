"""run_latest.py <script> [arguments] -- runs a script from the latest release
folder, v<version> beside this file. The widget task and the "Extra time"
shortcuts start through it, as the monitor does through launcher.ps1, so they
run what the last update brought. No release replaces this file."""
import runpy
import sys
from pathlib import Path


def version(folder: Path) -> list:
    try:
        return [int(number) for number in folder.name[1:].split(".")]
    except ValueError:
        return []  # no release: it sorts lowest


# the updater renames a folder to its version only once it is whole
release = max((folder for folder in Path(__file__).parent.glob("v*") if folder.is_dir()), key=version)
sys.argv = [str(release / sys.argv[1])] + sys.argv[2:]
sys.path.insert(0, str(release))  # as when the script is started itself: it imports what is beside it
runpy.run_path(sys.argv[0], run_name="__main__")
