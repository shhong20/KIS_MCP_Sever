"""Secure configuration: live/sim hosts are fixed, no trading switch exists."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path

HOSTS = {
    "real": "https://openapi.koreainvestment.com:9443",
    "virtual": "https://openapivts.koreainvestment.com:29443",
}

def load_local_env() -> None:
    """Load simple KEY=VALUE .env only if process environment does not override it."""
    path = Path.cwd() / ".env"
    if not path.is_file():
        return
    if path.is_symlink():
        raise ValueError("Refusing symlink .env")
    if path.stat().st_mode & 0o077:
        raise ValueError(".env permissions are too broad: chmod 600 .env")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in {"KIS_ENV","KIS_APP_KEY","KIS_APP_SECRET","KIS_CANO","KIS_ACNT_PRDT_CD","KIS_ACCOUNT_LABEL","KIS_ISA_USER_CONFIRMED"}:
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

@dataclass(frozen=True)
class Settings:
    environment: str
    app_key: str
    app_secret: str
    cano: str
    product_code: str
    account_label: str
    isa_user_confirmed: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        load_local_env()
        environment = os.environ.get("KIS_ENV", "real").strip().lower()
        if environment not in HOSTS:
            raise ValueError("KIS_ENV must be real or virtual")
        cano = os.environ.get("KIS_CANO", "").strip()
        product_code = os.environ.get("KIS_ACNT_PRDT_CD", "").strip()
        if cano and (len(cano) != 8 or not cano.isdigit()):
            raise ValueError("KIS_CANO must be eight digits")
        if product_code and (len(product_code) != 2 or not product_code.isdigit()):
            raise ValueError("KIS_ACNT_PRDT_CD must be two digits")
        return cls(
            environment,
            os.environ.get("KIS_APP_KEY", "").strip(),
            os.environ.get("KIS_APP_SECRET", "").strip(),
            cano,
            product_code,
            os.environ.get("KIS_ACCOUNT_LABEL", "unverified").strip()[:32],
            os.environ.get("KIS_ISA_USER_CONFIRMED", "false").strip().lower() == "true",
        )

    @property
    def base_url(self) -> str:
        return HOSTS[self.environment]

    def ready(self) -> bool:
        return bool(self.app_key and self.app_secret and self.cano and self.product_code)

    def public_status(self) -> dict:
        return {
            "environment": self.environment,
            "read_only": True,
            "trading_enabled": False,
            "credentials_configured": bool(self.app_key and self.app_secret),
            "account_configured": bool(self.cano and self.product_code),
            "account_label_user_declared": self.account_label,
            "isa_api_eligibility_verified": False,
            "isa_user_confirmed": self.isa_user_confirmed,
            "account_type_source": "user_confirmed" if self.isa_user_confirmed else "unverified",
        }
