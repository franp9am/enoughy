"""update.ps1, launcher.ps1 and run_latest.py end to end, the setup's two
folders, under Program Files and ProgramData, mirrored in tmp_path. The updater
runs against a release served from a local HTTP server; the launcher runs with
a stub monitor.py that writes down each start, and with a stub update.ps1 or
the real one. Windows only, since both are PowerShell and the crypto is .NET."""
import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the launcher is Windows only")

REPO = Path(__file__).resolve().parent.parent
SHA256_PKCS1 = "[Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1"


def powershell(script: str, **env: str) -> str:
    """Runs the script; `env` reaches it as $env:NAME, since -Command would
    glue further arguments onto the script text."""
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, check=True, env={**os.environ, **env},
    ).stdout


PASSWORD = "test password"
X509 = "Security.Cryptography.X509Certificates"


@pytest.fixture(scope="module")
def keys(tmp_path_factory) -> dict:
    """A throwaway certificate: the private half in a PFX under PASSWORD signs
    releases, the public half as a .cer goes next to the updater."""
    d = tmp_path_factory.mktemp("keys")
    pfx, cer = d / "release_key.pfx", d / "release_key.cer"
    powershell(
        "$rsa = [Security.Cryptography.RSA]::Create(2048); "
        f"$req = New-Object {X509}.CertificateRequest('CN=test', $rsa, {SHA256_PKCS1}); "
        "$cert = $req.CreateSelfSigned((Get-Date), (Get-Date).AddYears(1)); "
        f"[IO.File]::WriteAllBytes($env:PFX, $cert.Export([{X509}.X509ContentType]::Pfx, $env:PASSWORD)); "
        f"[IO.File]::WriteAllBytes($env:CER, $cert.Export([{X509}.X509ContentType]::Cert))",
        PFX=str(pfx), CER=str(cer), PASSWORD=PASSWORD,
    )
    return {"pfx": pfx, "cer": cer}


def sign(zip_path: Path, pfx: Path) -> None:
    powershell(
        f"$cert = New-Object {X509}.X509Certificate2($env:PFX, $env:PASSWORD, [{X509}.X509KeyStorageFlags]::EphemeralKeySet); "
        f"$key = [{X509}.RSACertificateExtensions]::GetRSAPrivateKey($cert); "
        f"[IO.File]::WriteAllBytes($env:ZIP + '.sig', $key.SignData([IO.File]::ReadAllBytes($env:ZIP), {SHA256_PKCS1}))",
        PFX=str(pfx), PASSWORD=PASSWORD, ZIP=str(zip_path),
    )


def make_release(served_dir: Path, version: str, keys: dict, monitor: str = "# new monitor\n", updater: bool = True) -> Path:
    """The layout release.ps1 builds: flat, a release folder's content, with
    the key and the updater, here the real one with a line added, since the
    next update in a test runs it."""
    zip_path = served_dir / "enoughy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("VERSION", version)
        z.writestr("monitor.py", monitor)
        z.writestr("config.py", "# new\n")
        z.writestr("remaining_time_widget.py", "# new widget\n")
        if updater:
            z.writestr("update.ps1", (REPO / "monitor" / "update.ps1").read_text() + "# new updater\n")
        z.write(keys["cer"], "release_key.cer")
    sign(zip_path, keys["pfx"])
    return zip_path


PROGRAM = Path("Program Files") / "enoughy"  # the code: launcher, starter, Python and the release folders
STATE = Path("ProgramData") / "Enoughy"  # the data, UPDATE_MODE and FETCHED


@pytest.fixture
def machine(tmp_path, keys):
    """What the setup leaves behind, its two folders under tmp_path. The
    private Python is a junction to the one running the tests."""
    program, state = tmp_path / PROGRAM, tmp_path / STATE
    release = program / "v0.5.0"
    release.mkdir(parents=True)
    (state / "data").mkdir(parents=True)
    import _winapi
    _winapi.CreateJunction(sys.base_prefix, str(program / "python"))
    shutil.copy(REPO / "monitor" / "launcher.ps1", program)
    shutil.copy(REPO / "monitor" / "run_latest.py", program)
    (state / "UPDATE_MODE").write_text("auto")
    shutil.copy(REPO / "monitor" / "update.ps1", release)
    shutil.copy(keys["cer"], release / "release_key.cer")
    (release / "VERSION").write_text("0.5.0")
    (release / "monitor.py").write_text("# old monitor\n")
    (release / "config.py").write_text("# old\n")
    return tmp_path


def on(machine: Path) -> dict:
    """The environment of a process on that machine: its own ProgramData,
    which is where the updater looks for the state folder."""
    return {**os.environ, "PROGRAMDATA": str(machine / "ProgramData")}


@pytest.fixture
def server(tmp_path):
    """Serves tmp_path/served like releases/latest/download/ does."""
    served = tmp_path / "served"
    served.mkdir()
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(served), **kw)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"dir": served, "url": f"http://127.0.0.1:{httpd.server_port}"}
    httpd.shutdown()


def releases(machine: Path) -> list:
    return sorted(p.name for p in (machine / PROGRAM).glob("v*.*.*"))


def latest_release(machine: Path) -> Path:
    return max((machine / PROGRAM).glob("v*.*.*"), key=lambda p: [int(n) for n in p.name[1:].split(".")])


def run_update(machine: Path, url: str) -> dict:
    """One run of the updater as the launcher makes it, from the latest release
    folder, against the local server; what the launcher would run afterwards."""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(latest_release(machine) / "update.ps1"), "-Url", url],
        capture_output=True, text=True, timeout=120, env=on(machine),
    )
    release = latest_release(machine)
    log = machine / STATE / "data" / "crash.log"
    return {
        "releases": releases(machine),
        "version": (release / "VERSION").read_text(),
        "monitor": (release / "monitor.py").read_text(),
        "config": (release / "config.py").read_text(),
        "updater_updated": (release / "update.ps1").read_text().endswith("# new updater\n"),
        "log": log.read_text() if log.exists() else "",
        "fetched": (machine / STATE / "FETCHED").exists(),
        "left": sorted(p.name for p in (machine / PROGRAM).iterdir() if p.name in ("update.tmp", "enoughy.zip", "enoughy.zip.sig")),
    }


def test_a_newer_release_is_installed(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys)
    result = run_update(machine, server["url"])
    assert result["releases"] == ["v0.5.0", "v0.6.0"]  # the monitor still runs from the old one
    assert result["version"] == "0.6.0"
    assert result["monitor"] == "# new monitor\n"
    assert result["config"] == "# new\n"
    assert (machine / PROGRAM / "v0.6.0" / "remaining_time_widget.py").read_text() == "# new widget\n"  # in the release, like the rest
    assert result["updater_updated"]
    assert "update: updated 0.5.0 to 0.6.0" in result["log"]
    assert result["left"] == []


def test_the_updater_a_release_brought_removes_the_releases_before_it(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys)
    run_update(machine, server["url"])
    assert run_update(machine, server["url"])["releases"] == ["v0.6.0"]


def test_it_fetches_once_a_day_and_the_updater_a_release_brought_installs_the_next(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys)
    run_update(machine, server["url"])
    make_release(server["dir"], "0.7.0", keys)
    assert run_update(machine, server["url"])["version"] == "0.6.0"
    (machine / STATE / "FETCHED").write_text("2020-01-01")  # the day is over
    result = run_update(machine, server["url"])
    assert "update: updated 0.6.0 to 0.7.0" in result["log"]


def test_a_tampered_zip_is_never_unpacked(machine, server, keys):
    zip_path = make_release(server["dir"], "0.6.0", keys)
    data = bytearray(zip_path.read_bytes())
    data[-1] ^= 1
    zip_path.write_bytes(data)
    result = run_update(machine, server["url"])
    assert "update.tmp" not in result["left"]
    assert result["releases"] == ["v0.5.0"]
    assert result["monitor"] == "# old monitor\n"
    assert not result["updater_updated"]
    result = run_update(machine, server["url"])
    assert result["log"].count("the downloaded zip does not match its signature") == 1  # logged once, then it waits a day


def test_a_release_without_an_updater_is_not_installed(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys, updater=False)  # as the releases up to 1.3.2 are: it would never be replaced
    result = run_update(machine, server["url"])
    assert result["releases"] == ["v0.5.0"]
    assert "the release brings no update.ps1" in result["log"]


def test_the_same_or_an_older_release_is_not_installed(machine, server, keys):
    make_release(server["dir"], "0.4.9", keys)
    result = run_update(machine, server["url"])
    assert result["version"] == "0.5.0"
    assert result["config"] == "# old\n"
    assert result["log"] == ""
    assert result["left"] == []


def test_manual_mode_never_fetches(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys)
    (machine / STATE / "UPDATE_MODE").write_text("manual")
    result = run_update(machine, server["url"])
    assert result["version"] == "0.5.0"
    assert not result["fetched"]


def test_without_a_release_to_reach_it_says_nothing_and_the_next_run_tries_again(machine, server, keys):
    result = run_update(machine, server["url"])  # nothing is served yet
    assert result["log"] == ""
    assert not result["fetched"]
    make_release(server["dir"], "0.6.0", keys)
    assert run_update(machine, server["url"])["version"] == "0.6.0"


def test_what_a_run_cut_off_left_unpacked_is_never_installed(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys)
    left = machine / PROGRAM / "update.tmp"  # the power went before the rename: no release yet, v0.5.0 runs on, whole
    left.mkdir()
    (left / "VERSION").write_text("0.9.0")
    (left / "extra.py").write_text("# never signed\n")
    result = run_update(machine, server["url"])
    assert result["releases"] == ["v0.5.0", "v0.6.0"]
    assert not (machine / PROGRAM / "v0.6.0" / "extra.py").exists()
    assert result["fetched"]
    assert result["left"] == []


STUB_MONITOR = (
    "import time\nfrom pathlib import Path\nhere = Path(__file__).parent\n"
    "with open(here.parent / 'starts.txt', 'a') as f: f.write(here.name + '\\n')\n"
)
BRINGS_0_6_0 = (  # what the updater does, in short: a newer release folder appears whole
    "if (-not (Test-Path \"$PSScriptRoot\\..\\v0.6.0\")) { Copy-Item $PSScriptRoot \"$PSScriptRoot\\..\\v0.6.0\" -Recurse }\n"
)
RELEASES_URL = "https://github.com/franp9am/enoughy/releases/latest/download"  # the updater's own default


def launcher_starts(machine: Path, monitor: str, updater: str, count: int, meanwhile=None, folders=("v0.5.0",), settle=3) -> list:
    """Runs the launcher, looping every second, with these two stubs in each of
    `folders` until the monitor has started `count` times and `settle` seconds
    more; returns the folders it started from. `meanwhile` is called once the
    launcher has had a few loops."""
    program = machine / PROGRAM
    for folder in folders:
        (program / folder).mkdir(exist_ok=True)
        (program / folder / "monitor.py").write_text(monitor)
        (program / folder / "update.ps1").write_text(updater)
    starts = program / "starts.txt"
    launcher = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(program / "launcher.ps1"), "-Every", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=on(machine),
    )
    try:
        if meanwhile:
            time.sleep(4)
            meanwhile()
        deadline = time.time() + 60
        while time.time() < deadline and not (starts.exists() and len(starts.read_text().split()) >= count):
            time.sleep(0.2)
        time.sleep(settle)  # a few more loops, to catch a start too many
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(launcher.pid)], capture_output=True)  # /T: the monitor too
    return starts.read_text().split() if starts.exists() else []


def test_the_launcher_restarts_the_monitor_from_the_release_the_updater_brought(machine):
    starts = launcher_starts(machine, STUB_MONITOR + "time.sleep(60)\n", BRINGS_0_6_0, count=2)
    assert starts == ["v0.5.0", "v0.6.0"]  # and no third: it is running and nothing changed


def test_the_launcher_and_the_updater_together_bring_a_release_and_remove_the_one_before(machine, server, keys):
    monitor = STUB_MONITOR + "time.sleep(60)\n"
    make_release(server["dir"], "0.6.0", keys, monitor)
    updater = (REPO / "monitor" / "update.ps1").read_text()
    assert RELEASES_URL in updater  # or the next line leaves it fetching from GitHub
    starts = launcher_starts(machine, monitor, updater.replace(RELEASES_URL, server["url"]), count=2, settle=10)
    assert starts == ["v0.5.0", "v0.6.0"]
    assert releases(machine) == ["v0.6.0"]  # the new release's updater, at its first run


def test_the_launcher_runs_the_highest_version_and_no_folder_still_being_unpacked(machine):
    starts = launcher_starts(
        machine, STUB_MONITOR + "time.sleep(60)\n", "", count=1, folders=("v0.5.0", "v0.9.0", "v0.10.0", "update.tmp", "vfoo"),
    )
    assert starts == ["v0.10.0"]


def test_the_launcher_restarts_a_monitor_that_died_whatever_the_updater_does(machine):
    starts = launcher_starts(machine, STUB_MONITOR + "1/0\n", "this is { no powershell\n", count=3)
    assert starts[:3] == ["v0.5.0"] * 3


def test_the_launcher_restarts_a_monitor_that_was_killed(machine):
    def kill_the_monitor():
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object CommandLine -like $env:MONITOR | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            env={**os.environ, "MONITOR": f"*{machine / PROGRAM / 'v0.5.0' / 'monitor.py'}*"}, capture_output=True,
        )
    starts = launcher_starts(machine, STUB_MONITOR + "time.sleep(600)\n", "", count=2, meanwhile=kill_the_monitor)
    assert starts == ["v0.5.0", "v0.5.0"]


def test_the_launcher_starts_the_monitor_once_python_is_there(machine):
    import _winapi
    python = machine / PROGRAM / "python"
    os.rmdir(python)  # the junction only: as while a setup replaces Python
    starts = launcher_starts(
        machine, STUB_MONITOR + "time.sleep(60)\n", "", count=1,
        meanwhile=lambda: _winapi.CreateJunction(sys.base_prefix, str(python)),
    )
    assert starts == ["v0.5.0"]


def start(machine: Path, *arguments: str) -> str:
    """What the widget task and the shortcut do, here with the console Python,
    whose output can be read."""
    return subprocess.run(
        [sys.executable, str(machine / PROGRAM / "run_latest.py"), *arguments], capture_output=True, text=True, timeout=60,
    ).stdout


def test_the_starter_runs_the_script_of_the_highest_release_with_its_arguments(machine):
    for folder in ("v0.5.0", "v0.9.0", "v0.10.0", "update.tmp", "vfoo"):
        (machine / PROGRAM / folder).mkdir(exist_ok=True)
        (machine / PROGRAM / folder / "beside.py").write_text(f"NAME = {folder!r}\n")
        (machine / PROGRAM / folder / "script.py").write_text("import sys\nimport beside\nprint(__name__, beside.NAME, sys.argv[1:])\n")
    assert start(machine, "script.py", "a file.txt", "b") == "__main__ v0.10.0 ['a file.txt', 'b']\n"


def test_the_widget_and_the_dialog_of_a_release_load_through_the_starter(machine):
    release = machine / PROGRAM / "v0.5.0"
    shutil.copy(REPO / "widget" / "remaining_time_widget.py", release)
    shutil.copy(REPO / "widget" / "enter_code.py", release)
    (release / "probe.py").write_text(  # the widget without its window: what it imports, and from where
        "from pathlib import Path\nimport remaining_time_widget as widget\n"
        "print(Path(widget.__file__).parent.name, Path(widget.enter_code.__file__).parent.name, widget.enter_code.STARTER.is_file())\n"
    )
    assert start(machine, "probe.py") == "v0.5.0 v0.5.0 True\n"
