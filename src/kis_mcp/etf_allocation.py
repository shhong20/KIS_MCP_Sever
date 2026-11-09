"""Read-only allocation simulator for an ETF-only target sleeve, never a broker order."""
from __future__ import annotations
from .normalize import as_integer

TARGETS = (
    ("379800", "KODEX 미국S&P500", 40),
    ("161510", "PLUS 고배당주", 20),
    ("458730", "TIGER 미국배당다우존스", 15),
    ("241180", "TIGER 일본니케이225", 10),
    ("214980", "KODEX 단기채권PLUS", 10),
    ("411060", "ACE KRX금현물", 5),
)
TOTAL_WEIGHT = sum(x[2] for x in TARGETS)
assert TOTAL_WEIGHT == 100

def allocate_etf_sleeve(balance: dict, quotes_krw: dict, contribution_krw: int, *, cash_ceiling_krw: int | None = None) -> dict:
    """Compute a model basket from caller-provided whole-share quotes.

    ISA holdings are not proof of executable buying power. All prices are
    caller-provided, unverified, and never sent as orders.
    """
    if not isinstance(balance, dict) or not balance.get("ok") or not balance.get("complete"):
        return {"ok": False, "reason": "KIS live holdings must be complete"}
    if balance.get("positions_match_securities_summary") is not True:
        return {"ok": False, "reason": "KIS securities positions not reconciled"}
    if not isinstance(quotes_krw, dict) or set(quotes_krw) != {t[0] for t in TARGETS}:
        return {"ok": False, "reason": "Quotes required for all six target ETFs"}
    if type(contribution_krw) is not int or not (0 <= contribution_krw <= 100_000_000):
        return {"ok": False, "reason": "Invalid contribution"}
    if cash_ceiling_krw is not None and (type(cash_ceiling_krw) is not int or cash_ceiling_krw < 0):
        return {"ok": False, "reason": "Invalid buying power ceiling"}
    quotes = {}
    for ticker, _, _ in TARGETS:
        price = quotes_krw[ticker]
        if type(price) is not int or not (100 <= price <= 10_000_000):
            return {"ok": False, "reason": "Invalid quote input"}
        quotes[ticker] = price
    available = min(contribution_krw, cash_ceiling_krw) if cash_ceiling_krw is not None else contribution_krw
    current = {ticker:0 for ticker,_,_ in TARGETS}
    quantities={ticker:0 for ticker,_,_ in TARGETS}
    holdings = balance.get("holdings")
    if not isinstance(holdings, list):
        return {"ok": False, "reason": "Invalid holdings"}
    non_target = 0
    for pos in holdings:
        if not isinstance(pos,dict):
            return {"ok":False,"reason":"Invalid holdings row"}
        val=as_integer(pos.get("market_value_krw"))
        qty=as_integer(pos.get("quantity"))
        if val is None or val < 0 or qty is None or qty < 0:
            return {"ok":False,"reason":"Incomplete holdings valuation"}
        if pos.get("market") == "KR" and pos.get("symbol") in current:
            t=pos["symbol"]
            current[t]+=val
            quantities[t]+=qty
        else:
            non_target+=val
    sleevesum=sum(current.values())
    future_base=sleevesum+available
    spent=0
    buys={ticker:0 for ticker,_,_ in TARGETS}
    # Choose an affordable purchase that maximally reduces target deficit,
    # subject to no over-allocation relative to the target at the start.
    while True:
        candidates=[]
        for ticker,name,weight in TARGETS:
            price=quotes[ticker]
            target=future_base*weight/100
            projected=current[ticker]+buys[ticker]*price
            deficit=target-projected
            if price <= available-spent and deficit >= price:
                candidates.append((deficit/price,deficit,ticker))
        if not candidates:
            break
        _,_,chosen=max(candidates,key=lambda x:(x[0],x[1],x[2]))
        buys[chosen]+=1
        spent+=quotes[chosen]
    items=[{
        "symbol":ticker,"name":name,"target_weight_pct":weight,
        "current_quantity":quantities[ticker],"current_sleeve_value_krw":current[ticker],
        "illustrative_quote_krw":quotes[ticker],"suggested_quantity":buys[ticker],
        "suggested_notional_krw":buys[ticker]*quotes[ticker],
        "projected_sleeve_weight_pct":round(100*(current[ticker]+buys[ticker]*quotes[ticker])/(sleevesum+spent),2) if sleevesum+spent else None,
    } for ticker,name,weight in TARGETS]
    return {
        "ok":True,"mode":"READ_ONLY_SIMULATION",
        "target_applies_to":"ETF sleeve only; not total broker portfolio",
        "cash_limit_source":"caller_supplied_no_margin_ceiling" if cash_ceiling_krw is not None else "caller_supplied_budget_only",
        "budget_krw":available,"suggested_total_krw":spent,"unallocated_krw":available-spent,
        "non_target_KIS_securities_krw":non_target,"current_target_etf_securities_krw":sleevesum,
        "items":items,"orders_submitted":False,"prices_verified_live":False,
        "warnings":[
            "Quotes are supplied by the caller and may be stale; recheck every instrument's executable buying power.",
            "This ETF-sleeve target excludes existing KIS non-target stocks, NH holdings, and full portfolio risk.",
            "No broker order is placed or authorized by this simulation.",
        ]
    }
