"""Private immutable KIS daily valuation snapshots (not investment returns)."""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import date, datetime, timezone
from hashlib import sha256
from hmac import new as hmac_new
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from .config import Settings

KST = ZoneInfo("Asia/Seoul")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.]{1,24}$")


def _day(value: str) -> date:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError("Invalid snapshot day")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Invalid snapshot day")
    return parsed


def _private_dir(path: Path, *, create: bool) -> bool:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(mode) or mode & 0o077:
        raise ValueError("Snapshot directory must be a private real directory")
    return True


def _account_dir(settings: Settings, root: Path | None = None, *, create: bool) -> Path | None:
    base = root if root is not None else Path.home() / ".local" / "share" / "kis-mcp" / "snapshots"
    # A keyed account namespace avoids mixing accounts without exposing account numbers.
    account_key = f"{settings.environment}:{settings.cano}:{settings.product_code}".encode()
    fingerprint = hmac_new(settings.app_secret.encode(), account_key, sha256).hexdigest()[:24]
    if not _private_dir(base, create=create):
        return None
    directory = base / fingerprint
    if not _private_dir(directory, create=create):
        return None
    return directory


def _read(path: Path) -> dict:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError("Snapshot file permissions or type invalid")
    row = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(row, dict) or row.get("schema_version") != 1
            or row.get("date", "") + ".json" != path.name
            or not isinstance(row.get("securities_value_krw"), int)
            or row["securities_value_krw"] < 0
            or not isinstance(row.get("positions"), list)):
        raise ValueError("Snapshot content invalid")
    return row


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Incomplete or invalid KIS valuation")
    return value


def _make_snapshot(data: dict, day: str, captured_at: str) -> dict:
    if (not isinstance(data, dict) or data.get("ok") is not True
            or data.get("complete") is not True
            or data.get("broker") != "KIS"
            or data.get("currency") != "KRW"
            or data.get("positions_match_securities_summary") is not True):
        raise ValueError("KIS balance not completely reconciled")
    positions = []
    seen = set()
    for row in data.get("holdings", []):
        if not isinstance(row, dict) or row.get("market") != "KR":
            raise ValueError("Unsupported or missing KIS holding")
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not SYMBOL_RE.fullmatch(symbol) or symbol in seen:
            raise ValueError("Invalid or duplicate KIS holding")
        seen.add(symbol)
        positions.append({
            "market": "KR", "symbol": symbol,
            "name": str(row.get("name", ""))[:160],
            "quantity": _nonnegative_int(row.get("quantity")),
            "market_value_krw": _nonnegative_int(row.get("market_value_krw")),
        })
    if len(positions) != data.get("holdings_count"):
        raise ValueError("KIS holdings count mismatch")
    securities = _nonnegative_int(data.get("securities_krw_broker_reported"))
    if sum(row["market_value_krw"] for row in positions) != securities:
        raise ValueError("KIS securities totals mismatch")
    cash = _nonnegative_int(data.get("broker_reported_cash_krw"))
    broker_total = _nonnegative_int(data.get("broker_reported_total_assets_krw"))
    return {
        "schema_version": 1, "broker": "KIS", "date": day,
        "captured_at": captured_at, "timezone": "Asia/Seoul",
        "scope": "KR_securities_and_reported_cash_not_verified_full_NAV",
        "securities_value_krw": securities,
        "reported_cash_krw": cash, "reported_total_assets_krw": broker_total,
        "reported_total_matches_cash_plus_securities": securities + cash == broker_total,
        "cash_order_buyable_verified": False, "full_nav_verified": False,
        "positions": sorted(positions, key=lambda p: p["symbol"]),
    }


def capture_snapshot(
    settings: Settings, load_export: Callable[[], dict], *,
    day: str | None = None, root: Path | None = None,
    captured_at: str | None = None,
) -> dict:
    day = day or datetime.now(KST).date().isoformat()
    _day(day)
    if day > datetime.now(KST).date().isoformat():
        raise ValueError("Future snapshot day is not allowed")
    directory = _account_dir(settings, root, create=True)
    if directory is None:
        raise ValueError("Snapshot directory missing")
    target = directory / (day + ".json")
    try:
        prior = _read(target)
    except FileNotFoundError:
        prior = None
    if prior is not None:
        return {"ok": True, "created": False, "date": day,
                "securities_value_krw": prior["securities_value_krw"],
                "broker_calls_skipped": True}
    data = load_export()
    snapshot = _make_snapshot(
        data, day, captured_at or datetime.now(timezone.utc).isoformat()
    )
    tmp = directory / (".capture-" + uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(snapshot, out, ensure_ascii=False, separators=(",", ":"))
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(tmp, target)
            created = True
        except FileExistsError:
            created = False
    finally:
        tmp.unlink(missing_ok=True)
    recorded = _read(target)
    return {"ok": True, "created": created, "date": day,
            "securities_value_krw": recorded["securities_value_krw"],
            "broker_calls_skipped": False}


def snapshot_history(settings: Settings, month: str = "", *, root: Path | None = None) -> dict:
    if month and not MONTH_RE.fullmatch(month):
        raise ValueError("Month must be YYYY-MM")
    directory = _account_dir(settings, root, create=False)
    snapshots = []
    if directory is not None:
        for file in sorted(directory.glob("????-??-??.json")):
            if month and not file.name.startswith(month + "-"):
                continue
            _day(file.name[:-5])
            snapshots.append(_read(file))
    series = []
    previous = None
    for snapshot in snapshots:
        value = snapshot["securities_value_krw"]
        delta = value - previous["securities_value_krw"] if previous else None
        old_positions = {p["symbol"]: p for p in previous["positions"]} if previous else {}
        new_positions = {p["symbol"]: p for p in snapshot["positions"]}
        same_quantities = previous is not None and (
            old_positions.keys() == new_positions.keys()
            and all(old_positions[k]["quantity"] == new_positions[k]["quantity"] for k in old_positions)
        )
        stable_contributions = sorted(
            ({"symbol": symbol,
              "valuation_change_krw": pos["market_value_krw"] - old_positions[symbol]["market_value_krw"]}
             for symbol, pos in new_positions.items()
             if symbol in old_positions
             and pos["quantity"] == old_positions[symbol]["quantity"]
             and pos["quantity"] > 0),
            key=lambda x: abs(x["valuation_change_krw"]), reverse=True,
        ) if previous else []
        changed_symbols = sorted(
            symbol for symbol in old_positions.keys() | new_positions.keys()
            if symbol not in old_positions or symbol not in new_positions
            or old_positions[symbol]["quantity"] != new_positions[symbol]["quantity"]
        ) if previous else []
        contributions = stable_contributions[:5] if same_quantities else []
        securities_sum = sum(p["market_value_krw"] for p in snapshot["positions"])
        # A discrepancy between displayed cash, securities and Xavier total can result
        # from settlement timing. Preserve it as unverified broker evidence;
        # only a securities/position mismatch invalidates the snapshot history.
        if securities_sum != value or (previous and
            sum(p["market_value_krw"] for p in previous["positions"]) != previous["securities_value_krw"]):
            raise ValueError("Stored securities position total does not reconcile")
        current_arithmetic_matches = (
            snapshot["reported_cash_krw"] + value == snapshot["reported_total_assets_krw"]
            and snapshot.get("reported_total_matches_cash_plus_securities") is True
        )
        previous_arithmetic_matches = previous is None or (
            previous["reported_cash_krw"] + previous["securities_value_krw"]
            == previous["reported_total_assets_krw"]
            and previous.get("reported_total_matches_cash_plus_securities") is True
        )
        calendar_gap = (_day(snapshot["date"]) - _day(previous["date"])).days if previous else None
        blockers = ["EXTERNAL_CASH_FLOW_LEDGER_NOT_VERIFIED", "FULL_NAV_AND_SETTLEMENT_NOT_VERIFIED"]
        if previous is None:
            blockers.append("NO_PRIOR_OBSERVATION")
        elif calendar_gap != 1:
            blockers.append("OBSERVATION_NOT_NEXT_CALENDAR_DAY")
        if changed_symbols:
            blockers.append("POSITION_QUANTITY_CHANGED_OR_MISSING")
        if not current_arithmetic_matches or not previous_arithmetic_matches:
            blockers.append("BROKER_TOTAL_ARITHMETIC_UNVERIFIED_SETTLEMENT_PENDING")
        observation_on_weekend = _day(snapshot["date"]).weekday() >= 5
        if observation_on_weekend:
            blockers.append("WEEKEND_OBSERVATION_NOT_MARKET_RETURN")
        series.append({
            "date": snapshot["date"], "captured_at": snapshot["captured_at"],
            "securities_value_krw": value,
            "observation_on_weekend": observation_on_weekend,
            "exchange_session_calendar_verified": False,
            "reported_cash_krw": snapshot["reported_cash_krw"],
            "broker_reported_total_assets_krw": snapshot["reported_total_assets_krw"],
            "previous_observation_date": previous["date"] if previous else None,
            "calendar_gap_days": (_day(snapshot["date"]) - _day(previous["date"])).days if previous else None,
            "securities_valuation_change_krw": delta,
            "securities_valuation_change_pct": round(delta / previous["securities_value_krw"] * 100, 2)
                if previous and previous["securities_value_krw"] > 0 else None,
            "same_position_quantities": same_quantities,
            "top_position_value_changes": contributions,
            "top_unchanged_quantity_contributors": stable_contributions[:5],
            "unchanged_quantity_attributed_change_krw": (
                sum(x["valuation_change_krw"] for x in stable_contributions)
                if previous else None
            ),
            "quantity_changed_or_added_or_removed_symbols": changed_symbols,
            "reported_cash_change_krw": (
                snapshot["reported_cash_krw"] - previous["reported_cash_krw"]
                if previous else None
            ),
            "broker_reported_total_assets_change_krw": (
                snapshot["reported_total_assets_krw"] - previous["reported_total_assets_krw"]
                if previous else None
            ),
            "reported_totals_internal_arithmetic_matches": current_arithmetic_matches,
            "reported_total_minus_cash_and_securities_krw": (
                snapshot["reported_total_assets_krw"] - snapshot["reported_cash_krw"] - value
            ),
            "actual_investment_profit_krw": None,
            "actual_investment_return_pct": None,
            "return_blockers": blockers,
            "full_nav_verified": False,
        })
        previous = snapshot
    return {
        "broker": "KIS", "observations": len(series),
        "first_date": series[0]["date"] if series else None,
        "last_date": series[-1]["date"] if series else None,
        "series": series,
        "return_calculation_available": False,
        "calculation_kind": "SECURITIES_VALUATION_CHANGE_NOT_INVESTMENT_RETURN",
        "warning": "Changes are between stored observation dates, not necessarily consecutive trading days. Trade, cash flow, dividends and account NAV are not independently reconciled. US market and currency timelines can differ.",
    }
