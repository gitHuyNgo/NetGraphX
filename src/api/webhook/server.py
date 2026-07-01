"""
webhook/server.py
-----------------
Lightweight Flask server that receives NetBox webhook signals and uses a
configurable debounce timer before triggering the full topology sync pipeline.

Endpoints
---------
POST /webhook/netbox
    Receives a NetBox change notification.
    Validates X-NetBox-Key header against WEBHOOK_SECRET (if set).
    Records the change in the shared state file.

POST /webhook/done
    Immediately triggers a topology sync (used by the Streamlit "Done" button).
    Also validates X-NetBox-Key if WEBHOOK_SECRET is set.

GET /webhook/status
    Returns JSON status of the current webhook/sync state.
    Used by the Streamlit UI to poll for pending changes.

The debounce logic runs in a daemon background thread: every 30 seconds it
checks whether `WEBHOOK_DEBOUNCE_MINUTES` have elapsed since the last recorded
change. If so, and there is a pending change, it fires the sync pipeline.
"""

import hashlib
import hmac
import subprocess
import sys
import threading
import time
import asyncio
from datetime import datetime, timezone

# Fix for WinError 10054 spam in Flask/Werkzeug on Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from flask import Flask, jsonify, request

from config.settings import webhook_config
from src.api.webhook import state as wh_state

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _secret_valid(req) -> bool:
    """
    Returns True if the request carries a valid secret header OR if no secret
    is configured (open mode — only recommended for dev/internal networks).
    """
    secret = webhook_config.WEBHOOK_SECRET
    if not secret:
        # No secret configured → accept all requests (log a warning)
        app.logger.warning(
            "WEBHOOK_SECRET is not set. Accepting all incoming webhook requests."
        )
        return True
    provided = req.headers.get("X-NetBox-Key", "")
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(provided, secret)


def _run_sync_pipeline() -> None:
    """
    Spawns the main sync pipeline as a subprocess so it runs in its own
    Python environment and does not block the Flask request thread.
    """
    app.logger.info("[Webhook] Triggering topology sync pipeline...")
    try:
        result = subprocess.run(
            [sys.executable, "main.py", "--run-engine"],
            capture_output=True,
            text=True,
            timeout=900,  # 15-minute hard limit
        )
        if result.returncode == 0:
            app.logger.info("[Webhook] Sync pipeline completed successfully.")
            wh_state.acknowledge()
        else:
            app.logger.error(
                f"[Webhook] Sync pipeline exited with code {result.returncode}.\n"
                f"STDERR: {result.stderr[:500]}"
            )
    except subprocess.TimeoutExpired:
        app.logger.error("[Webhook] Sync pipeline timed out after 5 minutes.")
    except Exception as exc:
        app.logger.error(f"[Webhook] Sync pipeline error: {exc}")


# ---------------------------------------------------------------------------
# Debounce Background Thread
# ---------------------------------------------------------------------------

def _debounce_worker() -> None:
    """
    Runs as a daemon thread. Polls every 30 seconds.
    If a pending change exists and WEBHOOK_DEBOUNCE_MINUTES have elapsed
    since the last change, fires the sync pipeline automatically.
    """
    check_interval_seconds = 30  # internal polling granularity (not user-facing)
    debounce_seconds = webhook_config.WEBHOOK_DEBOUNCE_MINUTES * 60

    app.logger.info(
        f"[Debounce] Worker started. Auto-sync after "
        f"{webhook_config.WEBHOOK_DEBOUNCE_MINUTES} minutes of inactivity."
    )

    while True:
        time.sleep(check_interval_seconds)

        if not wh_state.get_pending():
            continue

        last_change_str = wh_state.get_last_change_utc()
        if not last_change_str:
            continue

        try:
            last_change = datetime.fromisoformat(last_change_str)
            elapsed = (datetime.now(timezone.utc) - last_change).total_seconds()
        except (ValueError, TypeError):
            continue

        if elapsed >= debounce_seconds:
            app.logger.info(
                f"[Debounce] {elapsed:.0f}s elapsed since last change "
                f"(threshold: {debounce_seconds}s). Triggering auto-sync."
            )
            # Run sync in its own thread to not block the debounce loop
            sync_thread = threading.Thread(
                target=_run_sync_pipeline, daemon=True, name="sync-pipeline"
            )
            sync_thread.start()


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@app.route("/webhook/netbox", methods=["POST"])
def receive_netbox_webhook():
    """Receive a NetBox change notification and record it for debounced processing."""
    if not _secret_valid(request):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    event_type = payload.get("event", "unknown")

    wh_state.record_change(event_type=event_type, source="netbox")

    debounce_min = webhook_config.WEBHOOK_DEBOUNCE_MINUTES
    app.logger.info(
        f"[Webhook] Received event '{event_type}'. "
        f"Auto-sync in {debounce_min} min if no further changes."
    )
    return jsonify({
        "status": "recorded",
        "event": event_type,
        "auto_sync_after_minutes": debounce_min,
        "message": (
            f"Change recorded. Sync will trigger automatically after "
            f"{debounce_min} minutes of inactivity, or immediately when "
            f"'Done' is clicked in the dashboard."
        ),
    }), 200


@app.route("/webhook/done", methods=["POST"])
def trigger_done():
    """
    Immediately triggers topology sync (bypasses debounce timer).
    Called by the Streamlit UI 'Done' button.
    """
    if not _secret_valid(request):
        return jsonify({"error": "Unauthorized"}), 401

    force = request.args.get("force", "false").lower() == "true"
    if not wh_state.get_pending() and not force:
        return jsonify({
            "status": "no_pending_changes",
            "message": "No pending changes detected. Sync skipped.",
        }), 200

    app.logger.info("[Webhook] Manual 'Done' trigger received. Starting immediate sync.")
    sync_thread = threading.Thread(
        target=_run_sync_pipeline, daemon=True, name="sync-pipeline-manual"
    )
    sync_thread.start()

    return jsonify({
        "status": "sync_triggered",
        "message": "Topology sync has been triggered manually.",
    }), 202


@app.route("/webhook/status", methods=["GET"])
def get_status():
    """Return the current webhook state (used by Streamlit UI polling)."""
    return jsonify(wh_state.get_status()), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def start_server():
    """Start the Flask webhook server with the debounce background thread."""
    debounce_thread = threading.Thread(
        target=_debounce_worker,
        daemon=True,
        name="debounce-worker",
    )
    debounce_thread.start()

    port = webhook_config.WEBHOOK_PORT
    app.logger.info(f"[Webhook] Server starting on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    start_server()
