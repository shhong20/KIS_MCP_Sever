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
from contextlib import contextmanager
import fcntl
import sys
import stat
from .config import Settings
from .cache_crypto import seal, unseal

TOKEN_PATH = "/oauth2/tokenP"
DOMESTIC_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
BUYABLE_PATH = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
ALLOWED_DATA_PATHS = frozenset({DOMESTIC_BALANCE_PATH, BUYABLE_PATH})

class KISError(RuntimeError):
    """Errors must not echo API credentials, account numbers or response bodies."""

class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise KISError("KIS redirect blocked")

def _audit(event: str) -> None:
    print(json.dumps({"broker":"KIS","event":event,"time":int(time.time())}), file=sys.stderr)

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
        origin = parse.urlsplit(url)
        if (origin.scheme, origin.netloc) not in {("https","openapi.koreainvestment.com:9443"),("https","openapivts.koreainvestment.com:29443")}:
            raise KISError("KIS endpoint not allowed")
        print(json.dumps({"broker":"KIS","event":"outbound","origin":origin.scheme+"://"+origin.netloc,"kind":"auth" if origin.path==TOKEN_PATH else "data"}),file=sys.stderr)
        opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
        with opener.open(req, timeout=12) as res:
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
                failed = headers.get("authorization", "").removeprefix("Bearer ")
                headers = {**headers, "authorization": "Bearer " + self._token(failed=failed)}
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

    def auth_security_status(self) -> dict:
        path = self._cache_file()
        until = 0.0
        scheme = None
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
                raise KISError("Token cache permissions invalid")
            obj, scheme = self._read_cache(path)
            if isinstance(obj.get("token"), str) and obj["token"]:
                until = float(obj.get("expires_at", 0))
        return {"read_only":True,"api_origin":self.config.base_url,
                "disk_valid":until>time.time()+60,
                "expires_at_unix":int(until) if until>0 else None,
                "memory_valid":bool(self._access_token and time.monotonic()<self._token_until),
                "redirects_allowed":False,"proxy_enabled":False,
                "cache_protection":self._protection(path),"cache_format":scheme}

    def _cache_file(self) -> Path:
        identity = sha256((self.config.environment + ":" + self.config.app_key
                           + ":" + self.config.app_secret).encode()).hexdigest()[:24]
        directory = Path.home() / ".local" / "state" / "kis-mcp"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir() or (directory.stat().st_mode & 0o077):
            raise KISError("Token cache directory permissions invalid")
        return directory / ("token-" + identity + ".json")

    def _protection(self,path):
        marker=path.parent/"host-protection"
        if not marker.exists() and not marker.is_symlink():
            return "aes-gcm-v1"
        st=marker.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_uid!=os.getuid():
            raise KISError("KIS cache protection permissions invalid")
        if marker.read_text().strip()!="systemd-host-v1":
            raise KISError("KIS cache protection invalid")
        return "systemd-host-v1"

    def _read_cache(self,path):
        try:
            st=path.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_uid!=os.getuid():
                raise ValueError()
            return unseal(json.loads(path.read_text()),self.config.app_secret,path.stem,self._protection(path))
        except (OSError,ValueError,TypeError,AttributeError):
            raise KISError("KIS cache decrypt failed") from None

    def _load_cached_token(self) -> str | None:
        path = self._cache_file()
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or (path.stat().st_mode & 0o077):
            raise KISError("Token cache permissions invalid")
        try:
            obj, scheme = self._read_cache(path)
            token = obj.get("token")
            until = float(obj.get("expires_at", 0))
            if isinstance(token, str) and token and until > time.time() + 60:
                if scheme!=self._protection(path):
                    self._save_cached_token(token,until)
                    _audit("cache_encrypted")
                self._access_token = token
                self._token_until = time.monotonic() + (until - time.time())
                return token
        except (ValueError, OSError, TypeError, AttributeError):
            raise KISError("Token cache invalid") from None
        return None

    def _save_cached_token(self, token: str, expires_at: float) -> None:
        path = self._cache_file()
        try:
            envelope=seal({"token":token,"expires_at":expires_at},self.config.app_secret,path.stem,self._protection(path))
        except (OSError,ValueError,TypeError):
            raise KISError("KIS cache encryption failed") from None
        tmp = path.with_name("." + path.name + "." + uuid4().hex)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(tmp, flags, 0o600)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(envelope, stream)
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

    @contextmanager
    def _token_lock(self):
        path = self._cache_file().with_suffix(".lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.getuid():
                raise KISError("KIS token lock permissions invalid")
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise KISError("KIS token lock timeout")
                    time.sleep(.1)
            yield
        finally:
            os.close(fd)

    def _token(self, failed: str | None = None) -> str:
        if self._access_token and self._access_token != failed and time.monotonic() < self._token_until:
            _audit("memory_reuse")
            return self._access_token
        if not self._allow_disk_cache:
            return self._issue_token()
        with self._token_lock():
            cached = self._load_cached_token()
            if cached and cached != failed:
                _audit("disk_reuse")
                return cached
            if failed:
                self._invalidate_token()
                _audit("revoked")
            return self._issue_token()

    def _issue_token(self) -> str:
        _audit("issue_attempt")
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
        _audit("issued")
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
