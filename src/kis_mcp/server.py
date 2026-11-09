"""MCP protocol adapter for the fail-closed read-only KIS client."""
from __future__ import annotations
from .config import Settings
from .client import KISClient, KISError

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
        return {
            "broker": "KIS",
            "currency": "KRW",
            "holdings": [
                {"symbol": p.get("pdno"), "name": p.get("prdt_name"),
                 "quantity": p.get("hldg_qty"), "value_krw": p.get("evlu_amt")}
                for p in data["holdings"]
            ],
            "cash_krw_broker_reported": data["summary"].get("dnca_tot_amt"),
            "cash_is_order_buyable": False,
            "isa_eligibility_verified": False,
            "complete": True,
            "warning": "Do not sum unverified cash, securities and margin. Verify ISA account eligibility.",
        }
    return status, balance, export

def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise RuntimeError("Install project dependencies: pip install -e .") from None

    settings = Settings.from_env()
    status, balance, export = make_service(settings)
    app = FastMCP("kis-readonly")
    app.tool(name="kis_connection_status", description="KIS API configuration status, no secrets")(status)
    app.tool(name="kis_domestic_balance", description="Read-only domestic holdings and cash summary; ISA eligibility not guaranteed")(balance)
    app.tool(name="kis_portfolio_export", description="Normalized redacted holdings for cross-broker analysis")(export)
    app.run(transport="stdio")
