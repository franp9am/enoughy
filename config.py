"""Fixed at install: paths, intervals, the version. Settings are in settings.py."""
from pathlib import Path

MONITOR_VERSION = "0.6.0"  # bumped by hand; shown on the parent's page, nothing branches on it

# A child is a Windows account with `DATA_DIR/<child>/`, hidden from them, and
# `SHARED_DIR/<child>/`, writable by every local account, so nothing in it is
# trusted. The installer creates both; every directory in DATA_DIR is a child.
DATA_DIR = Path(__file__).parent / "data"
SHARED_DIR = Path(r"C:\ProgramData\ScreenTimeShared")
CRASH_LOG_FILE = DATA_DIR / "crash.log"  # the monitor's own, so not under any child

SYNC_TIMEOUT_SECONDS = 5  # a slow server must not stall the check loop

CHECK_INTERVAL_SECONDS = 60
SHUTDOWN_DELAY_SECONDS = 180  # grace period once the time is up
NIGHT_SHUTDOWN_DELAY_SECONDS = 120  # grace period outside the allowed hours
NIGHT_WARNING_SECONDS = 5 * 60  # the child is told this long before the night
STARTUP_DELAY_SECONDS = 40  # wait after boot before the first check
NETWORK_WARMUP_SECONDS = 20

SIGNATURE_CHARS = 4  # changing it invalidates codes already handed out
MAX_REDEEM_FILE_BYTES = 128
