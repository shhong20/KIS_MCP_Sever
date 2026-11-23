"""Safe one-shot KIS portfolio snapshot for a weekday systemd user timer.

Use only after the market closes; never backfill or place an order.
"""
from __future__ import annotations
import json
import sys
from .config import Settings
from .server import make_service
from .snapshots import capture_snapshot

def main() -> int:
    try:
        settings = Settings.from_env()
        _, _, export = make_service(settings)
        result = capture_snapshot(settings, export)
        print(json.dumps({
            "decision": "KIS_SNAPSHOT_OK",
            "date": result["date"],
            "created": result["created"],
            "broker_calls_skipped": result["broker_calls_skipped"],
            "account_data_redacted": True,
            "orders_submitted": False,
        }))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(json.dumps({
            "decision": "KIS_SNAPSHOT_FAILED",
            "failure_kind": "BROKER_OR_STORAGE_VALIDATION",
            "account_data_redacted": True,
            "orders_submitted": False,
        }), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
