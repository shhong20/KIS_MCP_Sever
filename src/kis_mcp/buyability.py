"""Read-only KIS domestic per-security buyability (no margin/credit)."""
from __future__ import annotations
from .client import KISClient, KISError, BUYABLE_PATH
from .normalize import as_integer

def query_buyable(client: KISClient, symbol: str, limit_price_krw: int) -> dict:
    if not isinstance(symbol, str) or len(symbol) != 6 or not symbol.isdigit():
        raise KISError("Security symbol must be six decimal digits")
    if type(limit_price_krw) is not int or not (1 <= limit_price_krw <= 100_000_000):
        raise KISError("Limit price must be positive integer KRW")
    settings=client.config
    payload,_ = client._request(
        BUYABLE_PATH, method="GET",
        headers={
            "authorization": "Bearer " + client._token(),
            "appkey": settings.app_key, "appsecret": settings.app_secret,
            "tr_id": "TTTC8908R" if settings.environment == "real" else "VTTC8908R",
            "custtype": "P", "content-type": "application/json",
        },
        params={
            "CANO":settings.cano,"ACNT_PRDT_CD":settings.product_code,
            "PDNO":symbol,"ORD_UNPR":str(limit_price_krw),
            "ORD_DVSN":"00", "CMA_EVLU_AMT_ICLD_YN":"N","OVRS_ICLD_YN":"N",
        }
    )
    if payload.get("rt_cd") != "0":
        return {"ok":False,"broker":"KIS","symbol":symbol,
                "broker_error_code":str(payload.get("msg_cd",""))[:32],
                "reason":"KIS rejected buyability inquiry; account scope or service constraints may apply"}
    obj=payload.get("output")
    if not isinstance(obj,dict):
        raise KISError("KIS buyability response has no output object")
    fields=("ord_psbl_cash","nrcvb_buy_amt","nrcvb_buy_qty","max_buy_amt","max_buy_qty","psbl_qty_calc_unpr")
    data={k:as_integer(obj.get(k)) for k in fields}
    if data["nrcvb_buy_amt"] is None or data["nrcvb_buy_qty"] is None:
        raise KISError("KIS no-margin buy amount/quantity unavailable")
    return {
        "ok":True,"broker":"KIS","currency":"KRW","symbol":symbol,
        "order_type":"limit_price","order_price_krw":limit_price_krw,
        "no_margin_buy_amount_krw":data["nrcvb_buy_amt"],
        "no_margin_buy_quantity":data["nrcvb_buy_qty"],
        "broker_reported_orderable_cash_krw":data["ord_psbl_cash"],
        "max_buy_amount_with_possible_margin_krw":data["max_buy_amt"],
        "not_an_order":True,
        "warning":"Buyability is symbol/price/time-specific; no margin used in recommended amount. No order placed.",
    }
