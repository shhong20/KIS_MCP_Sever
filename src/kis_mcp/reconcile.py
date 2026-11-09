"""Strict, read-only reconciliation of NH securities and KIS ISA holdings.

NH data is explicitly provided by the caller, NOT independently authenticated by this
server. No credentials/account identifiers are accepted and no cash is double-counted.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any
from .normalize import as_integer

class ReconciliationError(ValueError):
    pass

def _krw(value: Any, label: str) -> int:
    amount = as_integer(value)
    if amount is None or amount < 0:
        raise ReconciliationError(f"{label}: expected non-negative integer KRW")
    return amount

def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 18 or not value.isascii():
        raise ReconciliationError("Invalid security symbol")
    if not all(ch.isalnum() or ch in ".-" for ch in value):
        raise ReconciliationError("Invalid security symbol")
    return value.upper()

def _position(row: dict, broker: str) -> dict:
    if not isinstance(row, dict):
        raise ReconciliationError("Invalid position row")
    market = row.get("market")
    if market not in ("KR", "US"):
        raise ReconciliationError("Unsupported market")
    symbol = _symbol(row.get("symbol"))
    quantity = _krw(row.get("quantity"), "quantity")
    amount = _krw(row.get("market_value_krw"), "market_value_krw")
    return {"broker": broker, "market": market, "symbol": symbol, "quantity": quantity,
            "market_value_krw": amount}

SEMICONDUCTOR_SYMBOLS = {
    ("KR","000660"), ("KR","005930"), ("US","TSM"), ("US","INTC")
}

def reconcile_portfolios(nh: dict, kis: dict, *, nh_audit_status: str = "UNVERIFIED") -> dict:
    """Reconcile *securities only*; never assert unified NAV from mixed snapshot APIs.

    NH value and KIS value may come from different times. The source of NH input
    remains caller supplied, so this output must not claim independent verification.
    """
    if not isinstance(nh, dict) or not isinstance(kis, dict):
        raise ReconciliationError("Snapshot payload must be objects")
    if nh.get("scope") != "domestic_KR_and_overseas_US_securities_only":
        raise ReconciliationError("Unsupported NH scope")
    if not kis.get("ok") or not kis.get("complete") or kis.get("broker") != "KIS":
        raise ReconciliationError("KIS snapshot incomplete")
    if kis.get("currency") != "KRW":
        raise ReconciliationError("Unsupported KIS reporting currency")
    if kis.get("positions_match_securities_summary") is not True:
        raise ReconciliationError("KIS positions do not reconcile to securities summary")
    nh_rows = nh.get("positions")
    kis_rows = kis.get("holdings")
    if not isinstance(nh_rows, list) or not isinstance(kis_rows, list) or len(nh_rows)>200 or len(kis_rows)>200:
        raise ReconciliationError("Invalid positions collection")
    if any(p.get("broker") != "KIS" for p in kis_rows if isinstance(p, dict)):
        raise ReconciliationError("Unexpected KIS source")
    nh_positions = [_position(p, "NH") for p in nh_rows]
    kis_positions = [_position(p, "KIS") for p in kis_rows]
    nh_value = sum(p["market_value_krw"] for p in nh_positions)
    kis_value = sum(p["market_value_krw"] for p in kis_positions)
    if nh_value != _krw(nh.get("market_value_krw"), "NH total"):
        raise ReconciliationError("NH securities total does not match holding rows")
    if kis_value != _krw(kis.get("securities_krw_rows"), "KIS securities rows"):
        raise ReconciliationError("KIS securities total does not match holding rows")
    if kis_value != _krw(kis.get("securities_krw_broker_reported"), "KIS securities broker"):
        raise ReconciliationError("KIS broker securities total mismatch")
    positions = nh_positions + kis_positions
    grouped: dict[tuple[str,str],dict] = defaultdict(lambda: {"quantity":0,"market_value_krw":0,"sources":[]})
    for p in positions:
        record=grouped[(p["market"],p["symbol"])]
        record["quantity"]+=p["quantity"]
        record["market_value_krw"]+=p["market_value_krw"]
        record["sources"].append({"broker":p["broker"],"quantity":p["quantity"],"market_value_krw":p["market_value_krw"]})
    aggregated=[{"market":market,"symbol":symbol,**vals} for (market,symbol),vals in sorted(grouped.items())]
    total = nh_value + kis_value
    semi = sum(p["market_value_krw"] for p in aggregated if (p["market"],p["symbol"]) in SEMICONDUCTOR_SYMBOLS)
    duplicates=[p for p in aggregated if len({s["broker"] for s in p["sources"]}) > 1]
    return {
        "complete_securities_only": True,
        "nh_input_provenance": "caller_supplied_not_authenticated",
        "kis_account_type": kis.get("account_type", "unverified"),
        "kis_account_type_source": kis.get("account_type_source","unverified"),
        "nh_securities_krw": nh_value,
        "kis_securities_krw": kis_value,
        "combined_securities_krw": total,
        "aggregated": aggregated,
        "duplicate_cross_broker_symbols": duplicates,
        "semiconductor_direct_value_krw": semi,
        "semiconductor_direct_weight_pct": round(100*semi/total,2) if total else None,
        "semi_scope": "direct SK Hynix Samsung Electronics TSMC Intel only; indirect holdings excluded",
        "nh_accounting_audit_status": nh_audit_status,
        "verified_combined_net_assets_krw": None,
        "verified_investment_return_pct": None,
        "cash_not_added": True,
        "note": "Values may be asynchronous; source-specific settled/buyable cash and non-additive broker totals excluded.",
    }
