"""KIS Open API read-only client. Strict endpoint allowlist and paginated balance."""
from __future__ import annotations
import json
import time
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from urllib import parse, request, error
from typing import Callable
from .config import Settings

TOKEN_PATH = "/oauth2/tokenP"
DOMESTIC_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
BUYABLE_PATH = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
ALLOWED_DATA_PATHS = frozenset({DOMESTIC_BALANCE_PATH, BUYABLE_PATH})

class KISError(RuntimeError):
    """Errors must not echo API credentials, account numbers or response bodies."""

class KISClient:
    def __init__(self, config: Settings, *, transport: Callable | None = None):
        self.config = config
        self.transport = transport or self._urlopen_transport
        self._access_token = ""
        self._token_until = 0.0
        self._allow_disk_cache = transport is None

    @staticmethod
    def _urlopen_transport(url: str, method: str, headers: dict, payload: bytes | None):
        req = request.Request(url, data=payload, headers=headers, method=method)
        with request.urlopen(req, timeout=12) as res:
            return res.status, dict(res.headers.items()), res.read()

    def _request(self, path: str, *, method: str, headers: dict, body: dict | None = None, params: dict | None = None):
        if path != TOKEN_PATH and path not in ALLOWED_DATA_PATHS:
            raise KISError("Endpoint not allowlisted")
        if path == TOKEN_PATH and method != "POST":
            raise KISError("Invalid auth method")
        if path != TOKEN_PATH and method != "GET":
            raise KISError("Only read-only GET data requests are allowed")
        if not self.config.ready():
            raise KISError("KIS credentials or account not configured")
        url = self.config.base_url + path
        if params:
            url += "?" + parse.urlencode(params)
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        try:
            try:
                status, response_headers, raw = self.transport(url, method, headers, data)
            except error.HTTPError as exc:
                if exc.code != 401 or path == TOKEN_PATH:
                    raise
                status, response_headers, raw = 401, {}, b""
            if status == 401 and path != TOKEN_PATH:
                # One bounded retry. Do not repeat other errors or rotate on 429.
                self._invalidate_token()
                headers = {**headers, "authorization": "Bearer " + self._token()}
                try:
                    status, response_headers, raw = self.transport(url, method, headers, data)
                except error.HTTPError as exc:
                    raise KISError(f"KIS HTTP {exc.code} (response content withheld)") from None
            if status != 200:
                raise KISError("KIS HTTP response was not successful")
            if len(raw) > 3_000_000:
                raise KISError("KIS response exceeds safe size limit")
            decoded = json.loads(raw.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise KISError("Unexpected response format")
            return decoded, {str(k).lower():str(v) for k,v in response_headers.items()}
        except KISError:
            raise
        except error.HTTPError as exc:
            raise KISError(f"KIS HTTP {exc.code} (response content withheld)") from None
        except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            raise KISError("KIS transport or response error") from None

    def _cache_file(self) -> Path:
        identity = sha256((self.config.environment + ":" + self.config.app_key
                           + ":" + self.config.app_secret).encode()).hexdigest()[:24]
        directory = Path.home() / ".local" / "state" / "kis-mcp"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir() or (directory.stat().st_mode & 0o077):
            raise KISError("Token cache directory permissions invalid")
        return directory / ("token-" + identity + ".json")

    def _load_cached_token(self) -> str | None:
        path = self._cache_file()
        if not path.exists():
            return None
        if path.is_symlink() or (path.stat().st_mode & 0o077):
            raise KISError("Token cache permissions invalid")
        try:
            obj = json.loads(path.read_text())
            token = obj.get("token")
            until = float(obj.get("expires_at", 0))
            if isinstance(token, str) and token and until > time.time() + 60:
                self._access_token = token
                self._token_until = time.monotonic() + (until - time.time())
                return token
        except (ValueError, OSError, TypeError, AttributeError):
            raise KISError("Token cache invalid") from None
        return None

    def _save_cached_token(self, token: str, expires_at: float) -> None:
        path = self._cache_file()
        tmp = path.with_name("." + path.name + "." + uuid4().hex)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(tmp, flags, 0o600)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"token": token, "expires_at": expires_at}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _invalidate_token(self) -> None:
        """Drop only this client's cached token on explicit broker HTTP 401."""
        self._access_token = ""
        self._token_until = 0.0
        if not self._allow_disk_cache:
            return
        path = self._cache_file()
        if path.is_symlink():
            raise KISError("Token cache symlink refused")
        try:
            if path.exists():
                if path.stat().st_mode & 0o077:
                    raise KISError("Token cache permissions invalid")
                path.unlink()
        except OSError:
            raise KISError("Token cache invalidation failed") from None

    def _token(self) -> str:
        if self._access_token and time.monotonic() < self._token_until:
            return self._access_token
        if self._allow_disk_cache:
            cached = self._load_cached_token()
            if cached:
                return cached
        obj, _ = self._request(
            TOKEN_PATH,
            method="POST",
            headers={"content-type": "application/json; charset=utf-8"},
            body={"grant_type": "client_credentials",
                  "appkey": self.config.app_key, "appsecret": self.config.app_secret},
        )
        token = obj.get("access_token")
        if not isinstance(token, str) or not token:
            raise KISError("Token issuance unsuccessful")
        expiry = obj.get("expires_in", 3600)
        try:
            expiry = float(expiry)
        except (ValueError, TypeError):
            expiry = 3600
        self._access_token = token
        ttl = max(0, min(expiry, 86400) - 120)
        self._token_until = time.monotonic() + ttl
        if self._allow_disk_cache and ttl > 0:
            self._save_cached_token(token, time.time() + ttl)
        return token

    def domestic_balance(self) -> dict:
        """Collect all pages or fail closed: never report an incomplete ISA account as complete."""
        seen: set[tuple[str,str]] = set()
        rows: list[dict] = []
        page_count = 0
        fk = nk = ""
        totals = None
        for page in range(10):
            params = {
                "CANO": self.config.cano,
                "ACNT_PRDT_CD": self.config.product_code,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "00",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": fk,
                "CTX_AREA_NK100": nk,
            }
            obj, headers = self._request(
                DOMESTIC_BALANCE_PATH, method="GET",
                headers={
                    "authorization": "Bearer " + self._token(),
                    "appkey": self.config.app_key,
                    "appsecret": self.config.app_secret,
                    "tr_id": "TTTC8434R" if self.config.environment == "real" else "VTTC8434R",
                    "custtype": "P",
                    "content-type": "application/json",
                    **({"tr_cont": "N"} if page else {}),
                },
                params=params,
            )
            if obj.get("rt_cd") != "0":
                raise KISError("KIS balance API rejected the request (check account eligibility and API credentials)")
            page_count += 1
            data_rows = obj.get("output1", [])
            if not isinstance(data_rows, list):
                raise KISError("Unexpected balance rows")
            rows.extend(data_rows)
            if len(rows) > 1000:
                raise KISError("Balance exceeds row safety limit")
            if totals is None:
                vals = obj.get("output2", [])
                totals = vals[0] if isinstance(vals, list) and vals else (vals if isinstance(vals, dict) else {})
            continuation = headers.get("tr_cont", "")
            if continuation not in ("M", "F"):
                break
            next_fk = str(obj.get("ctx_area_fk100", "")).strip()
            next_nk = str(obj.get("ctx_area_nk100", "")).strip()
            cursor = (next_fk, next_nk)
            if not next_fk and not next_nk or cursor in seen:
                raise KISError("Balance pagination cursor absent or repeating")
            seen.add(cursor)
            fk, nk = cursor
        else:
            raise KISError("Balance pagination limit reached; incomplete data withheld")
        fields = ("pdno", "prdt_name", "hldg_qty", "ord_psbl_qty", "pchs_avg_pric",
                  "evlu_amt", "evlu_pfls_amt", "evlu_pfls_rt")
        cash_fields = ("dnca_tot_amt", "nxdy_excc_amt", "prvs_rcdl_excc_amt", "tot_evlu_amt",
                       "scts_evlu_amt", "pchs_amt_smtl_amt", "evlu_pfls_smtl_amt")
        return {
            "broker": "KIS",
            "currency": "KRW",
            "account_label_user_declared": self.config.account_label,
            "isa_eligibility_verified": False,
            "complete": True,
            "page_count": page_count,
            "holdings": [{k:r[k] for k in fields if k in r} for r in rows],
            "summary": {k:totals[k] for k in cash_fields if k in totals},
            "note": "KIS API balance data; account type and ISA contribution limit are not verified.",
        }
