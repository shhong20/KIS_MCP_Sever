"""Normalize KIS domestic holdings for cross-broker analysis without double-counting."""
from __future__ import annotations
from .config import Settings

def as_integer(value: object) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    return int(raw) if raw and raw.lstrip("-").isdigit() else None

def normalize_balance(data: dict, settings: Settings) -> dict:
    if not data.get("complete") or not isinstance(data.get("summary"), dict):
        return {"ok": False, "reason": "Incomplete balance summary"}
    summary = data["summary"]
    cash = as_integer(summary.get("dnca_tot_amt"))
    securities = as_integer(summary.get("scts_evlu_amt"))
    total = as_integer(summary.get("tot_evlu_amt"))
    positions = []
    for p in data.get("holdings", []):
        quantity = as_integer(p.get("hldg_qty"))
        value = as_integer(p.get("evlu_amt"))
        if not p.get("pdno") or quantity is None or value is None:
            return {"ok": False, "reason": "Incomplete position data"}
        positions.append({
            "broker": "KIS", "market": "KR", "currency": "KRW",
            "symbol": p["pdno"], "name": p.get("prdt_name", ""),
            "quantity": quantity, "market_value_krw": value,
        })
    if cash is None or securities is None or total is None:
        return {"ok": False, "reason": "Incomplete cash or asset totals"}
    subtotal = sum(p["market_value_krw"] for p in positions)
    return {
        "ok": True, "complete": True, "broker": "KIS",
        "account_type": "ISA" if settings.isa_user_confirmed else "unverified",
        "account_type_source": "user_confirmed" if settings.isa_user_confirmed else "unverified",
        "isa_api_eligibility_verified": False, "currency": "KRW",
        "holdings": positions, "holdings_count": len(positions),
        "securities_krw_broker_reported": securities,
        "securities_krw_rows": subtotal,
        "broker_reported_cash_krw": cash,
        "broker_reported_total_assets_krw": total,
        "positions_match_securities_summary": subtotal == securities,
        "sum_position_plus_cash_equals_broker_total": subtotal + cash == total,
        "cash_is_order_buyable": False, "cash_is_settled_verified": False,
        "warning": "Cash, securities and total assets are not additive. ISA status was confirmed by the account holder, not independently by API.",
    }
