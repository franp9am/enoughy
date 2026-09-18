"""Talks to the parent's server: reports today's totals, receives time grants
and settings.

Nothing here enforces anything -- the monitor keeps counting and shutting the
machine down whether the server answers or not.
"""

import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from config import MONITOR_VERSION, SYNC_TIMEOUT_SECONDS


@dataclass
class DailyStatus:
    """What the parent's page shows about today; sent on every sync."""

    date: str
    time_spent_sec: int
    carryover_sec: int
    granted_sec: int
    remaining_sec: int
    last_tick: Optional[str]
    settings: dict  # in force
    # {"id": <change id>, "taken": <bool>} for the last change the server delivered
    settings_change_outcome: Optional[dict] = None


@dataclass
class Grant:
    id: int
    seconds: int


@dataclass
class SettingsChange:
    id: int
    settings: dict  # every setting the server wants in force, by settings.SETTINGS name


@dataclass
class SyncAnswer:
    pending_grants: List[Grant]
    settings_change: Optional[SettingsChange]


def load_server_url(server_url_file: Path) -> str:
    """The parent's server; empty means run offline."""
    try:
        with open(server_url_file, "r", encoding="utf-8") as f:
            return f.read().strip().rstrip("/")
    except Exception:
        return ""


def load_child_token(child_token_file: Path) -> str:
    """Identifies which child this monitor reports for; empty means not set up."""
    try:
        with open(child_token_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def load_applied_grant_ids(applied_grants_file: Path) -> List[int]:
    """Grants already added to the data file but not yet confirmed by the server."""
    try:
        with open(applied_grants_file, "r", encoding="utf-8") as f:
            return [int(grant_id) for grant_id in json.load(f)]
    except Exception:
        return []


def save_applied_grant_ids(grant_ids, applied_grants_file: Path) -> None:
    tmp_file = applied_grants_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(sorted(grant_ids), f)
    os.replace(tmp_file, applied_grants_file)  # make the write atomic


def load_settings_change_outcome(outcome_file: Path) -> Optional[dict]:
    try:
        with open(outcome_file, "r", encoding="utf-8") as f:
            outcome = json.load(f)
        return outcome if isinstance(outcome, dict) else None
    except Exception:
        return None


def save_settings_change_outcome(change_id: int, taken: bool, outcome_file: Path) -> None:
    tmp_file = outcome_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump({"id": change_id, "taken": taken}, f)
    os.replace(tmp_file, outcome_file)  # make the write atomic


def send_status(
    status: DailyStatus, applied_grant_ids: List[int], server_url: str, token: str
) -> SyncAnswer:
    """Send today's totals plus the grant ids already applied (which acknowledges
    them), and return what the server answers.

    Raises on any network, HTTP or protocol problem -- the caller decides.
    """
    payload = asdict(status)
    payload["applied_grant_ids"] = applied_grant_ids
    payload["monitor_version"] = MONITOR_VERSION
    request = urllib.request.Request(
        server_url + "/api/sync",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=SYNC_TIMEOUT_SECONDS) as response:
        answer = json.load(response)
    change = answer.get("settings_change")
    return SyncAnswer(
        pending_grants=[
            Grant(id=int(grant["id"]), seconds=int(grant["seconds"]))
            for grant in answer["pending_grants"]
        ],
        settings_change=(
            SettingsChange(id=int(change["id"]), settings=dict(change["settings"]))
            if isinstance(change, dict)
            else None
        ),
    )
