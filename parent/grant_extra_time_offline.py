"""
Use this on parents machine to create a code with extra time for the child.
Standalone on purpose: copy this single file over, it imports nothing local.
"""

import argparse
import datetime
import hashlib
import hmac
import os
from pathlib import Path

SIGNATURE_CHARS = 4  # must equal SIGNATURE_CHARS in the child's config.py
SECRET_FILE = Path(__file__).parent / "data" / "secret.txt"

# The secret must equal the one on the child's machine; CHILD_SECRET wins over the file.
env_secret = os.environ.get("CHILD_SECRET", "").strip()
try:
    secret = bytes.fromhex(env_secret or SECRET_FILE.read_text(encoding="utf-8").strip())
except (OSError, ValueError):
    secret = b""
if not secret:
    raise ValueError(
        f"Write the shared secret (hex) to {SECRET_FILE}, or set the CHILD_SECRET "
        "env var, using the same secret as the child's machine"
    )


def get_code(extra_sec=3600, date=None):
    if not isinstance(extra_sec, int):
        raise ValueError("extra_sec should be an int")

    if date is None:
        date = datetime.date.today().isoformat()

    # The date is a nonce that keeps each code unique; it is part of the signed
    # payload and only checked against the calendar on redemption when the
    # child's config.py says CHECK_DATE_IN_REDEEM_CODES = True.
    payload = f"{date}:{extra_sec}"
    sign = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sign[:SIGNATURE_CHARS]}"


def get_no_night_code(date=None):
    """No night on that date; the daily limit still applies. Here the date is
    no nonce: the code is good on that day only, any number of times."""
    payload = f"{date or datetime.date.today().isoformat()}:nonight"
    sign = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sign[:SIGNATURE_CHARS]}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a code with extra seconds")
    parser.add_argument(
        "--extra_sec",
        "-e",
        type=int,
        default=3600,
        help="Extra seconds (default: 3600)",
    )
    parser.add_argument(
        "--date",
        "-d",
        type=str,
        default=None,
        help="Nonce date (default: today, e.g. 2026-07-23). "
        "Override to issue a second code of the same amount on the same day; "
        "with CHECK_DATE_IN_REDEEM_CODES on the child's side use another amount instead. "
        "With --no_night: the day without a night.",
    )
    parser.add_argument(
        "--no_night",
        "-n",
        action="store_true",
        help="A code for no night on the date instead of extra seconds",
    )

    args = parser.parse_args()

    if args.no_night:
        print(get_no_night_code(date=args.date))
    else:
        print(get_code(extra_sec=args.extra_sec, date=args.date))
