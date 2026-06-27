"""
webhook/state.py
----------------
File-backed shared state for the debounced NetBox webhook pipeline.

The state file is a simple JSON document read/written with a threading lock
so both the Flask webhook receiver and the Streamlit UI can safely access it.
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from config.settings import webhook_config

_lock = threading.Lock()
_STATE_FILE: str = webhook_config.WEBHOOK_STATE_FILE


def _read_state() -> dict:
    """Read the JSON state file, returning an empty dict if it doesn't exist."""
    if not os.path.exists(_STATE_FILE):
        return {}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state(state: dict) -> None:
    """Atomically write the JSON state file."""
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def record_change(event_type: str = "unknown", source: str = "netbox") -> None:
    """
    Record a pending topology change from NetBox.

    Parameters
    ----------
    event_type : str
        The NetBox event type string (e.g. "dcim.cable.created").
    source : str
        Who triggered the change (defaults to "netbox").
    """
    with _lock:
        state = _read_state()
        state["pending"] = True
        state["last_change_utc"] = datetime.now(timezone.utc).isoformat()
        state["last_event_type"] = event_type
        state["last_source"] = source
        state["acknowledged"] = False
        _write_state(state)


def acknowledge() -> None:
    """Mark the pending change as processed (sync has run)."""
    with _lock:
        state = _read_state()
        state["pending"] = False
        state["acknowledged"] = True
        state["last_sync_utc"] = datetime.now(timezone.utc).isoformat()
        _write_state(state)


def get_pending() -> bool:
    """Return True if there is at least one unprocessed change pending."""
    with _lock:
        state = _read_state()
        return bool(state.get("pending", False))


def get_last_change_utc() -> Optional[str]:
    """Return the ISO-8601 UTC timestamp of the last recorded change, or None."""
    with _lock:
        return _read_state().get("last_change_utc")


def get_last_sync_utc() -> Optional[str]:
    """Return the ISO-8601 UTC timestamp of the last completed sync, or None."""
    with _lock:
        return _read_state().get("last_sync_utc")


def get_status() -> dict:
    """Return a full status snapshot for display in the Streamlit UI."""
    with _lock:
        state = _read_state()
        return {
            "pending": state.get("pending", False),
            "acknowledged": state.get("acknowledged", True),
            "last_change_utc": state.get("last_change_utc"),
            "last_sync_utc": state.get("last_sync_utc"),
            "last_event_type": state.get("last_event_type"),
            "last_source": state.get("last_source"),
        }
