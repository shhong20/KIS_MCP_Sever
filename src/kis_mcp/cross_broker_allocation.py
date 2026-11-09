"""Read-only cross-broker asset-class exposure with conservative ETF look-through.

Never infer issuer exposures from ETF name. Only caller-supplied dated and
explicitly sourced constituent mappings are eligible for conditional estimates.
No live issuer data is fetched here; provenance is not independently authenticated.
"""
from __future__ import annotations
from .reconcile import reconcile_portfolios, ReconciliationError, SEMICONDUCTOR_SYMBOLS
from .normalize import as_integer
from .etf_allocation import TARGETS

KNOWN_ETFS = {("KR", symbol) for symbol, _, _ in TARGETS}
TARGET_WEIGHTS = {symbol:weight for symbol, _, weight in TARGETS}
REGION_FOR_DIRECT = {"KR":"Korea","US":"United States"}
# These direct names are well-defined; everything else is classified as
# 'non_semiconductor_direct_or_unclassified', not assumed to be free of exposure.
# User-supplied look-through cannot be called broker-verified.

def combined_exposure(nh:dict, kis:dict, *, audit_status:str="UNVERIFIED",
                      lookthrough:dict|None=None, monthly_investment_krw:int=0,
                      mapping_origin:str="caller_supplied")->dict:
    if mapping_origin not in ("caller_supplied", "issuer_cached_partial"):
        raise ReconciliationError("Invalid ETF mapping provenance")
    combined=reconcile_portfolios(nh,kis,nh_audit_status=audit_status)
    total=combined["combined_securities_krw"]
    if type(monthly_investment_krw) is not int or not 0<=monthly_investment_krw<=100_000_000:
        raise ReconciliationError("Invalid monthly contribution")
    positions=combined["aggregated"]
    direct_semiconductor=0
    direct_nonsemi=0
    etf_value=0
    etfs=[]
    by_region={"KR":0,"US":0}
    for p in positions:
        value=p["market_value_krw"]
        if p["market"]=="KR" and ("KR",p["symbol"]) in KNOWN_ETFS:
            etf_value+=value
            etfs.append({"symbol":p["symbol"],"value_krw":value,"broker_sources":p["sources"]})
        else:
            direct_nonsemi+=value
            by_region[p["market"]]+=value
            if (p["market"],p["symbol"]) in SEMICONDUCTOR_SYMBOLS:
                direct_semiconductor+=value
    classified_etf_value=0
    mapped_semiconductor=0
    mapped_regions={}
    mapped_breakdown=[]
    # We only allow 0..100% mapping for explicit underlying instruments. A
    # mapping may omit other weights, which remain explicitly unknown.
    by_etf={}
    if lookthrough is not None:
        if not isinstance(lookthrough,dict) or set(lookthrough)-{"funds"}:
            raise ReconciliationError("Invalid look-through envelope")
        supplied=lookthrough.get("funds")
        if not isinstance(supplied,list) or len(supplied)>50:
            raise ReconciliationError("Invalid fund mapping list")
        for row in supplied:
            if not isinstance(row,dict) or set(row)-{"symbol","as_of","source_url","holdings"}:
                raise ReconciliationError("Invalid ETF mapping row")
            symbol=row.get("symbol")
            if not isinstance(symbol,str) or ("KR",symbol) not in KNOWN_ETFS or symbol in by_etf:
                raise ReconciliationError("Unknown or duplicated ETF mapping")
            date=row.get("as_of");url=row.get("source_url");holdings=row.get("holdings")
            if not isinstance(date,str) or len(date)!=10 or date[4]!="-" or date[7]!="-":
                raise ReconciliationError("ETF mapping requires as-of date")
            if not isinstance(url,str) or not url.startswith(("https://","http://")) or len(url)>500:
                raise ReconciliationError("ETF mapping requires source URL")
            if not isinstance(holdings,list) or not 1<=len(holdings)<=300:
                raise ReconciliationError("Invalid holdings mapping")
            seen=set()
            mapped_bp=0
            semi_bp=0
            region_bp={}
            for h in holdings:
                if not isinstance(h,dict) or set(h)-{"market","symbol","weight_bps","region"}:
                    raise ReconciliationError("Invalid underlying holding")
                market=h.get("market");issuer=h.get("symbol");region=h.get("region")
                bp=h.get("weight_bps")
                if market not in ("KR","US","OTHER") or not isinstance(issuer,str) or not 1<=len(issuer)<=24:
                    raise ReconciliationError("Invalid underlying identifier")
                if region not in ("KR","US","Japan","Europe","Other"):
                    raise ReconciliationError("Invalid underlying region")
                if type(bp) is not int or not 0<bp<=10000:
                    raise ReconciliationError("Invalid constituent weight")
                key=(market,issuer)
                if key in seen:raise ReconciliationError("Duplicate underlying")
                seen.add(key);mapped_bp+=bp
                region_bp[region]=region_bp.get(region,0)+bp
                if (market,issuer) in SEMICONDUCTOR_SYMBOLS:semi_bp+=bp
            if mapped_bp>10000:raise ReconciliationError("ETF weights exceed 100%")
            by_etf[symbol]={"as_of":date,"source_url":url,"mapped_bps":mapped_bp,
                            "semi_bps":semi_bp,"region_bps":region_bp}
    for p in etfs:
        info=by_etf.get(p["symbol"])
        if info is None:
            mapped_breakdown.append({"symbol":p["symbol"],"value_krw":p["value_krw"],
                                     "mapped_krw":0,"unknown_krw":p["value_krw"],
                                     "status":"UNMAPPED"})
            continue
        value=p["value_krw"]
        classified_etf_value+=value*info["mapped_bps"]//10000
        mapped_semiconductor+=value*info["semi_bps"]//10000
        for region,bp in info["region_bps"].items():
            mapped_regions[region]=mapped_regions.get(region,0)+value*bp//10000
        mapped_breakdown.append({"symbol":p["symbol"],"value_krw":value,
                                 "mapped_krw":value*info["mapped_bps"]//10000,
                                 "unknown_krw":value-value*info["mapped_bps"]//10000,
                                 "status":("OFFICIAL_ISSUER_CACHE_PARTIAL_NOT_ATTESTED" if mapping_origin=="issuer_cached_partial"
                                           else "CALLER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"),
                                 "as_of":info["as_of"],"source_url":info["source_url"]})
    unknown_etf=max(0,etf_value-classified_etf_value)
    # The lower bound counts direct named semiconductors plus the explicitly
    # matched ETFs; unknown securities could have additional exposure.
    semi_lower=direct_semiconductor+mapped_semiconductor
    semi_upper=min(total,semi_lower+unknown_etf+(direct_nonsemi-direct_semiconductor))
    sleeve={x[0]:0 for x in TARGETS}
    for p in positions:
        if (p["market"],p["symbol"]) in KNOWN_ETFS:
            sleeve[p["symbol"]]+=p["market_value_krw"]
    sleeve_total=sum(sleeve.values())
    future_base=sleeve_total+monthly_investment_krw
    priorities=sorted(({"symbol":s,"name":name,"weight_pct":weight,
                       "current_krw":sleeve[s],
                       "target_after_contribution_krw":round(future_base*weight/100),
                       "shortfall_krw":max(0,round(future_base*weight/100)-sleeve[s])}
                      for s,name,weight in TARGETS),
                      key=lambda x:(-x["shortfall_krw"],-x["weight_pct"],x["symbol"]))
    return {
        "ok":True,"mode":"CROSS_BROKER_READ_ONLY",
        "provenance":("NH caller-supplied snapshot; KIS live read-only; ETF mapping official issuer partial cache"
                       if mapping_origin=="issuer_cached_partial" else
                       "NH caller-supplied snapshot; KIS live read-only; optional ETF mapping caller-supplied"),
        "nh_accounting_status":audit_status,
        "combined_securities_krw":total,
        "verified_combined_net_assets_krw":None,
        "direct_named_semiconductor_krw":direct_semiconductor,
        "direct_named_semiconductor_pct":round(direct_semiconductor*100/total,2) if total else None,
        "mapped_etf_semiconductor_krw_conditional":mapped_semiconductor,
        "semiconductor_exposure_lower_bound_krw_conditional":semi_lower,
        "semiconductor_exposure_upper_bound_krw_conservative":semi_upper,
        "unmapped_etf_exposure_krw":unknown_etf,
        "etf_total_value_krw":etf_value,
        "direct_region_value_krw":by_region,
        "caller_mapped_etf_region_value_krw_conditional":mapped_regions,
        "unclassified_direct_value_krw":direct_nonsemi-direct_semiconductor,
        "etf_lookthrough":mapped_breakdown,
        "target_etf_sleeve_current_krw":sleeve_total,
        "monthly_contribution_krw":monthly_investment_krw,
        "monthly_etf_target_shortfalls":priorities,
        "symbol_provenance":combined["aggregated"],
        "cross_broker_duplicates":combined["duplicate_cross_broker_symbols"],
        "orders_submitted":False,
        "warnings":[
            "Securities-only values exclude cash, margin, unsettled amounts and liabilities; not a combined NAV.",
            "Only selected direct named semiconductor stocks are counted as verified direct exposure; all other companies are unclassified for sector.",
            "ETF holdings mapping is optional caller-supplied evidence and cannot be authenticated by this tool.",
            "The conditional semiconductor lower bound assumes supplied ETF holdings are accurate; unknown exposures remain unknown.",
            "ETF targets apply only to specified ETF sleeve, not entire portfolio; no price, orderability, fees or tax checks.",
        ],
    }
