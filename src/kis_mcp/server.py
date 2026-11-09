"""MCP protocol adapter for the fail-closed read-only KIS client."""
from __future__ import annotations
from .config import Settings
from .client import KISClient, KISError
from .normalize import normalize_balance
from .reconcile import reconcile_portfolios, ReconciliationError
from .buyability import query_buyable
from .etf_allocation import allocate_etf_sleeve
from .cross_broker_allocation import combined_exposure
import json

def make_service(settings: Settings):
    client = KISClient(settings)
    def status() -> dict:
        return settings.public_status()
    def balance() -> dict:
        try:
            return client.domestic_balance()
        except KISError as exc:
            return {"ok": False, "reason": str(exc), "account_label_user_declared": settings.account_label,
                    "isa_eligibility_verified": False}
    def export() -> dict:
        data = balance()
        if not data.get("complete"):
            return {"ok": False, "reason": data.get("reason", "Not verified")}
        return normalize_balance(data, settings)
    return status, balance, export

def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise RuntimeError("Install project dependencies: pip install -e .") from None

    settings = Settings.from_env()
    client = KISClient(settings)
    status, balance, export = make_service(settings)
    app = FastMCP("kis-readonly")
    app.tool(name="kis_connection_status", description="KIS API configuration status, no secrets")(status)
    app.tool(name="kis_domestic_balance", description="Read-only domestic holdings and cash summary; ISA eligibility not guaranteed")(balance)
    app.tool(name="kis_portfolio_export", description="Normalized redacted holdings for cross-broker analysis")(export)
    def compare_namuh_snapshot(namuh_overview_json: str, namuh_audit_status: str = "UNVERIFIED") -> dict:
        """Compare caller-supplied NH overview with live KIS; never treat NH input as verified."""
        if not isinstance(namuh_overview_json, str) or len(namuh_overview_json) > 150_000:
            return {"ok": False, "reason": "Invalid NH payload size"}
        try:
            nh = json.loads(namuh_overview_json)
            isa = export()
            if not isa.get("ok"):
                return {"ok": False, "reason": "KIS live balance unavailable"}
            result = reconcile_portfolios(nh, isa, nh_audit_status=str(namuh_audit_status)[:60])
            return {"ok": True, **result}
        except (json.JSONDecodeError, ReconciliationError, TypeError, ValueError):
            return {"ok": False, "reason": "NH snapshot invalid or cannot reconcile"}
    app.tool(name="kis_compare_namuh_snapshot", description="Compare caller-provided NH securities with live ISA; never estimates full NAV or validates NH origin")(compare_namuh_snapshot)
    def buyability(symbol: str, limit_price_krw: int) -> dict:
        try:
            return query_buyable(client, symbol, limit_price_krw)
        except KISError as exc:
            return {"ok": False, "reason": str(exc)}
    app.tool(name="kis_domestic_buying_power", description="Read-only, no-margin cash buying power by symbol and limit price; NEVER places an order")(buyability)
    def plan_etf_contribution(quotes_json: str, budget_krw: int, no_margin_ceiling_krw: int | None = None) -> dict:
        if not isinstance(quotes_json,str) or len(quotes_json)>10000:
            return {"ok":False,"reason":"Invalid quote payload"}
        try:
            quotes=json.loads(quotes_json)
        except (ValueError,TypeError):
            return {"ok":False,"reason":"Quotes must be JSON object"}
        return allocate_etf_sleeve(export(),quotes,budget_krw,cash_ceiling_krw=no_margin_ceiling_krw)
    app.tool(name="kis_plan_etf_contribution",description="READ-ONLY ETF target-weight contribution simulation, caller-supplied quotes, no orders")(plan_etf_contribution)
    def cross_broker_allocation(namuh_overview_json: str, monthly_contribution_krw: int = 150000, etf_lookthrough_json: str = "", namuh_audit_status: str = "UNVERIFIED") -> dict:
        if not isinstance(namuh_overview_json,str) or len(namuh_overview_json)>150000:
            return {"ok":False,"reason":"Invalid NH payload size"}
        if not isinstance(etf_lookthrough_json,str) or len(etf_lookthrough_json)>300000:
            return {"ok":False,"reason":"Invalid ETF mapping size"}
        try:
            nh=json.loads(namuh_overview_json)
            mapping=json.loads(etf_lookthrough_json) if etf_lookthrough_json else None
            isa=export()
            if not isa.get("ok"):
                return {"ok":False,"reason":"KIS balance unavailable"}
            return combined_exposure(nh,isa,audit_status=str(namuh_audit_status)[:60],lookthrough=mapping,monthly_investment_krw=monthly_contribution_krw)
        except (json.JSONDecodeError, ReconciliationError, TypeError, ValueError):
            return {"ok":False,"reason":"Invalid snapshots or ETF mappings"}
    app.tool(name="kis_cross_broker_allocation", description="READ-ONLY NH+KIS securities exposures and ETF target shortfalls; caller supplied NH snapshot and optional ETF holdings; no orders")(cross_broker_allocation)
    app.run(transport="stdio")
