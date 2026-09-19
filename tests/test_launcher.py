"""launcher.ps1 end to end: a release served from a local HTTP server, the
folders under ProgramData mirrored in tmp_path, and a stub monitor.py that
writes a marker file so the test can see which one started. Windows only,
since the launcher is PowerShell and the crypto is .NET."""
import http.server
import os
import shutil
import subprocess
import sys
import threading
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
    releases, the public half as a .cer goes next to the launcher."""
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


def make_release(served_dir: Path, version: str, pfx: Path) -> Path:
    """The layout release.ps1 builds: flat, with the installer alongside, which
    an update must leave where it is."""
    zip_path = served_dir / "enoughy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("VERSION", version)
        z.writestr("monitor.py", "from pathlib import Path\nPath(__file__).with_name('started.txt').write_text('new')\n")
        z.writestr("config.py", "# new\n")
        z.writestr("remaining_time_widget.py", "# new widget\n")
        z.writestr("launcher.ps1", "# new launcher\n")
        z.writestr("install.ps1", "# new installer\n")
    sign(zip_path, pfx)
    return zip_path


@pytest.fixture
def machine(tmp_path, keys):
    """What install.ps1 leaves behind, under tmp_path instead of ProgramData.
    The private Python is a junction to the one running the tests."""
    monitor_dir = tmp_path / "Enoughy"
    (monitor_dir / "data").mkdir(parents=True)
    (tmp_path / "EnoughyShared").mkdir()
    import _winapi
    _winapi.CreateJunction(sys.base_prefix, str(tmp_path / "EnoughyPython"))
    shutil.copy(REPO / "launcher.ps1", monitor_dir)
    shutil.copy(keys["cer"], monitor_dir / "release_key.cer")
    (monitor_dir / "UPDATE_MODE").write_text("auto")
    (monitor_dir / "VERSION").write_text("0.5.0")
    (monitor_dir / "monitor.py").write_text(
        "from pathlib import Path\nPath(__file__).with_name('started.txt').write_text('old')\n"
    )
    (monitor_dir / "config.py").write_text("# old\n")
    (tmp_path / "EnoughyShared" / "remaining_time_widget.py").write_text("# old widget\n")
    return tmp_path


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


def run_launcher(machine: Path, url: str) -> dict:
    """One boot: the launcher with no network wait, against the local server."""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(machine / "Enoughy" / "launcher.ps1"), "-Url", url, "-Wait", "0"],
        capture_output=True, text=True, check=True, timeout=120,
    )
    monitor_dir = machine / "Enoughy"
    log = monitor_dir / "data" / "crash.log"
    return {
        "started": (monitor_dir / "started.txt").read_text(),
        "version": (monitor_dir / "VERSION").read_text(),
        "config": (monitor_dir / "config.py").read_text(),
        "widget": (machine / "EnoughyShared" / "remaining_time_widget.py").read_text(),
        "launcher_kept": (monitor_dir / "launcher.ps1").read_text() == (REPO / "launcher.ps1").read_text(),
        "installer_absent": not (monitor_dir / "install.ps1").exists(),
        "log": log.read_text() if log.exists() else "",
        "staged": (monitor_dir / "update").exists(),
    }


def test_a_newer_release_is_staged_at_one_boot_and_installed_at_the_next(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys["pfx"])
    result = run_launcher(machine, server["url"])
    assert result["started"] == "old"
    assert result["version"] == "0.5.0"
    assert result["staged"]
    assert result["log"] == ""
    result = run_launcher(machine, server["url"])
    assert result["started"] == "new"
    assert result["version"] == "0.6.0"
    assert result["config"] == "# new\n"
    assert result["widget"] == "# new widget\n"
    assert result["launcher_kept"] and result["installer_absent"]  # only a reinstall changes those
    assert "updated 0.5.0 to 0.6.0" in result["log"]


def test_a_tampered_zip_is_never_staged(machine, server, keys):
    zip_path = make_release(server["dir"], "0.6.0", keys["pfx"])
    data = bytearray(zip_path.read_bytes())
    data[-1] ^= 1
    zip_path.write_bytes(data)
    result = run_launcher(machine, server["url"])
    assert not result["staged"]
    assert "signature" in result["log"]
    result = run_launcher(machine, server["url"])
    assert result["started"] == "old"
    assert result["version"] == "0.5.0"
    assert result["config"] == "# old\n"
    assert result["widget"] == "# old widget\n"


def test_the_same_or_an_older_release_is_staged_but_not_installed(machine, server, keys):
    make_release(server["dir"], "0.4.9", keys["pfx"])
    run_launcher(machine, server["url"])
    result = run_launcher(machine, server["url"])
    assert result["started"] == "old"
    assert result["version"] == "0.5.0"
    assert result["log"] == ""


def test_manual_mode_never_fetches(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys["pfx"])
    (machine / "Enoughy" / "UPDATE_MODE").write_text("manual")
    result = run_launcher(machine, server["url"])
    assert result["started"] == "old"
    assert not result["staged"]


def test_manual_mode_still_installs_what_is_already_staged(machine, server, keys):
    """Switching to manual stops the download, not the copy: the release staged
    at the last auto boot still lands, and no later one follows it."""
    make_release(server["dir"], "0.6.0", keys["pfx"])
    run_launcher(machine, server["url"])   # auto: staged, not yet installed
    (machine / "Enoughy" / "UPDATE_MODE").write_text("manual")
    result = run_launcher(machine, server["url"])
    assert result["version"] == "0.6.0"
    assert "updated 0.5.0 to 0.6.0" in result["log"]
    make_release(server["dir"], "0.7.0", keys["pfx"])
    result = run_launcher(machine, server["url"])
    result = run_launcher(machine, server["url"])
    assert result["version"] == "0.6.0"   # 0.7.0 was never fetched


def test_the_monitor_starts_even_when_the_log_cannot_be_written(machine, server, keys):
    monitor_dir = machine / "Enoughy"
    (monitor_dir / "update").mkdir()  # staged but empty, so the install fails and wants to log
    log = monitor_dir / "data" / "crash.log"
    log.write_text("")
    log.chmod(0o444)
    result = run_launcher(machine, server["url"])
    assert result["started"] == "old"


def test_the_monitor_starts_even_when_the_staged_folder_cannot_be_deleted(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys["pfx"])
    staged = machine / "Enoughy" / "update"
    staged.mkdir(parents=True)
    (staged / "VERSION").write_text("0.4.0")
    with open(staged / "held.py", "w"):  # an open handle, as a virus scanner would have
        result = run_launcher(machine, server["url"])
    assert result["started"] == "old"
    assert "launcher" in result["log"]
    result = run_launcher(machine, server["url"])  # the handle is gone: staged now, installed a boot later
    result = run_launcher(machine, server["url"])
    assert result["version"] == "0.6.0"


def test_a_half_unpacked_release_is_never_installed_and_does_not_block_the_next(machine, server, keys):
    make_release(server["dir"], "0.6.0", keys["pfx"])
    half = machine / "Enoughy" / "update.new"  # the power went while unpacking
    half.mkdir(parents=True)
    (half / "VERSION").write_text("0.9.0")
    result = run_launcher(machine, server["url"])
    assert result["version"] == "0.5.0"
    result = run_launcher(machine, server["url"])
    assert result["version"] == "0.6.0"
