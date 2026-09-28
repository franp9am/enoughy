"""
The "Extra time" dialog: the child pastes the code from the parent, and the
dialog puts it where the monitor looks, <shared>/<account>/extra_time.txt.
One copy next to the child folders serves every account of the machine.

Its shortcut is in the Start menu of each child and of nobody else: the widget
makes it when it starts, which is at the child's logon.
"""

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

SHARED_DIR = Path(__file__).parent
TITLE = "Extra time"
# Inside the profile and never moved by OneDrive, so the uninstaller finds it too.
START_MENU_SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Extra time.lnk"


def make_shortcut(shortcut: Path):
    """A shortcut to this dialog, written again at every logon, so one that was
    deleted or points to an older install mends itself. Windows has no simpler
    way to write one than its scripting object."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")  # no console window
    script = f"""
        $link = (New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}')
        $link.TargetPath = '{pythonw}'
        $link.Arguments = '"{Path(__file__).resolve()}"'
        $link.Save()
    """
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def save_code(code: str, child_dir: Path) -> bool:
    """Hands the code to the monitor, which says so itself once it has added
    the time. False when the account is no child: the setup makes the folders."""
    if not child_dir.is_dir():
        return False
    (child_dir / "extra_time.txt").write_text(code.strip(), encoding="utf-8")
    return True


def main():
    root = tk.Tk()
    root.title(TITLE)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    tk.Label(root, text="Paste the code from your parent:").pack(padx=16, pady=(16, 4), anchor="w")
    entry = tk.Entry(root, width=40)
    entry.pack(padx=16)

    def submit(event=None):
        code = entry.get().strip()
        if code and not save_code(code, SHARED_DIR / os.getlogin()):
            messagebox.showwarning(
                TITLE,
                f"The account {os.getlogin()} has no time limit here, so a code has nothing to add to.",
                parent=root,
            )
        root.destroy()

    tk.Button(root, text="OK", width=10, command=submit).pack(pady=16)
    root.bind("<Return>", submit)
    root.bind("<Escape>", lambda event: root.destroy())
    root.eval("tk::PlaceWindow . center")
    entry.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
