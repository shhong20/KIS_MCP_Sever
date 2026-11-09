"""Official PLUS ETF constituent snapshot fetch and fail-closed parsing.

Only the pinned issuer product page is supported. Do not invent ETF compositions
for other targets; stale or missing official data never becomes live exposure.
"""
from __future__ import annotations
from datetime import date,datetime
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
from hashlib import sha256
from pathlib import Path
import json, os, re, tempfile

PLUS_URL = "https://www.plusetf.co.kr/product/detail?n=006273"
PLUS_SYMBOL = "161510"
STALE_AFTER_DAYS = 5

class ConstituentsError(ValueError):
    pass

class HoldingsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.body_depth = 0
        self.row_depth = 0
        self.cell_depth = 0
        self.cells = []
        self.rows = []
        self.buffer = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tbody" and attrs.get("id")=="pdfListBody":
            if self.in_body:raise ConstituentsError("Duplicate official holdings table")
            self.in_body = True
            self.body_depth=1
        elif self.in_body and tag=="tbody":
            self.body_depth+=1
        if not self.in_body:return
        if tag=="tr":
            self.row_depth+=1
            if self.row_depth==1:self.cells=[]
        if tag=="td" and self.row_depth==1:
            self.cell_depth+=1
            self.in_cell=True
            self.buffer=[]

    def handle_data(self, data):
        if self.in_body and self.in_cell:self.buffer.append(data)

    def handle_endtag(self, tag):
        if not self.in_body:return
        if tag=="td" and self.in_cell:
            self.cells.append("".join(self.buffer).strip())
            self.in_cell=False
            self.cell_depth=0
        elif tag=="tr" and self.row_depth:
            if self.row_depth==1 and self.cells:self.rows.append(list(self.cells))
            self.row_depth-=1
        elif tag=="tbody":
            self.body_depth-=1
            if self.body_depth==0:self.in_body=False

def parse_official_plus(html:bytes, *,today:date|None=None)->dict:
    if not isinstance(html,bytes) or not 100<len(html)<=2_000_000:
        raise ConstituentsError("Invalid issuer HTML")
    raw=html.decode("utf-8","strict")
    # The date is the explicit selected constituent-PDF date, not the NAV date.
    dates=re.findall(r'<input\b[^>]*\bid=["\']pdfDate["\'][^>]*\bdata-format=["\'](\d{4}-\d{2}-\d{2})["\']',raw,re.I)
    if len(dates)!=1:raise ConstituentsError("Missing or ambiguous issuer holdings date")
    asof=date.fromisoformat(dates[0])
    today=today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    age=(today-asof).days
    if age<0 or age>STALE_AFTER_DAYS:
        raise ConstituentsError("Issuer holdings snapshot out of freshness range")
    parser=HoldingsParser()
    parser.feed(raw)
    if not 5<=len(parser.rows)<=300:
        raise ConstituentsError("Unexpected number of official holdings rows")
    holdings=[]
    seen=set()
    total=0
    skipped=[]
    for cells in parser.rows:
        # Hidden index; code; display name; volume; percent
        if len(cells)!=5:raise ConstituentsError("Unexpected table row structure")
        _,code,name,volume,weight=cells
        if not re.fullmatch(r"\d{6}",code):
            skipped.append({"name":name[:70],"reason":"NON_EQUITY_OR_UNMAPPED_IDENTIFIER"})
            continue
        if code in seen:raise ConstituentsError("Duplicate holdings identifier")
        seen.add(code)
        m=re.fullmatch(r"(\d{1,3})(?:\.(\d{1,4}))?%",weight.strip())
        if not m:raise ConstituentsError("Missing constituent weight")
        w=float(weight[:-1])
        bp=round(w*100)
        if bp<=0 or bp>10000:raise ConstituentsError("Invalid weight")
        total+=bp
        holdings.append({"market":"KR","symbol":code,"region":"KR","weight_bps":bp})
    if not 5<=len(holdings)<=300 or total>10050:
        raise ConstituentsError("Invalid official composition weight sum")
    # The original mapping requires <=10000 bps: issuer % display rounding
    # can make it exceed slightly. Do not silently normalize over 100%.
    if total>10000:raise ConstituentsError("Issuer rounded weights exceed 100%")
    return {
        "symbol":PLUS_SYMBOL, "as_of":asof.isoformat(), "source_url":PLUS_URL,
        "holdings":holdings, "raw_sha256":sha256(html).hexdigest(),
        "date_age_days":age,"source_type":"OFFICIAL_ISSUER_PRODUCT_HTML",
        "coverage_weight_bps":total,"skipped":skipped,
        "partial_holdings_only":total<9900,
        "provenance":"ISSUER_PAGE_FETCHED_BUT_NOT_INDEPENDENTLY_ATTESTED",
    }

def fetch_official_plus(*,today:date|None=None, fetcher=None)->dict:
    target=urlsplit(PLUS_URL)
    if target.scheme!="https" or target.hostname!="www.plusetf.co.kr":
        raise ConstituentsError("Invalid official URL")
    if fetcher is not None:
        payload=fetcher(PLUS_URL)
    else:
        request=Request(PLUS_URL,headers={"User-Agent":"Mozilla/5.0 (ETF-Composition-Research)"})
        with urlopen(request,timeout=13) as res:
            actual=urlsplit(res.geturl())
            if res.status!=200 or actual.scheme!="https" or actual.hostname!="www.plusetf.co.kr":
                raise ConstituentsError("Unexpected issuer response")
            payload=res.read(2_000_001)
    return parse_official_plus(payload,today=today)

def save_snapshot(result:dict, target:Path)->None:
    if not result or result.get("source_type")!="OFFICIAL_ISSUER_PRODUCT_HTML":
        raise ConstituentsError("Only official issuer snapshot accepted")
    parent=target.parent
    parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if parent.is_symlink() or (parent.stat().st_mode & 0o077):
        raise ConstituentsError("Unsafe cache directory")
    if target.is_symlink():raise ConstituentsError("Cache symlink refused")
    fd,path=tempfile.mkstemp(prefix=".etf-official-",dir=parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w") as fp:
            json.dump(result,fp,ensure_ascii=False,separators=(",",":"))
            fp.flush();os.fsync(fp.fileno())
        os.replace(path,target)
    finally:
        if os.path.exists(path):os.unlink(path)

def public_snapshot(snapshot:dict)->dict:
    return {
        "funds":[{"symbol":snapshot["symbol"],"as_of":snapshot["as_of"],
                  "source_url":snapshot["source_url"],"holdings":snapshot["holdings"]}]
    }

if __name__=="__main__":
    path=Path.home()/".local/state/kis-mcp/etf-plus-official-161510.json"
    try:
        result=fetch_official_plus()
        save_snapshot(result,path)
        print(json.dumps({"ok":True,"source":PLUS_URL,"as_of":result["as_of"],
                          "holdings_count":len(result["holdings"]),"coverage_bps":result["coverage_weight_bps"],
                          "sha256":result["raw_sha256"],"path":str(path)},ensure_ascii=False))
    except (ConstituentsError,OSError,ValueError) as exc:
        print(json.dumps({"ok":False,"reason":type(exc).__name__,"detail":str(exc)[:140]}))
        raise SystemExit(2)


def read_fresh_official_cache(*,today:date|None=None,path:Path|None=None)->dict|None:
    target=path or Path.home()/".local/state/kis-mcp/etf-plus-official-161510.json"
    if not target.is_file() or target.is_symlink() or (target.stat().st_mode & 0o077):
        return None
    try:
        result=json.loads(target.read_text())
        expected=date.fromisoformat(result["as_of"])
        age=((today or datetime.now(ZoneInfo("Asia/Seoul")).date())-expected).days
        if not 0<=age<=STALE_AFTER_DAYS:
            return None
        if result.get("source_url")!=PLUS_URL or result.get("symbol")!=PLUS_SYMBOL:
            return None
        if not result.get("partial_holdings_only") or not 5<=len(result.get("holdings",[]))<=300:
            return None
        if len(result.get("raw_sha256",""))!=64:
            return None
        return public_snapshot(result)
    except (ValueError,TypeError,KeyError,OSError):
        return None
