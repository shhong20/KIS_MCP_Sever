import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kis_mcp.config import Settings, HOSTS
from kis_mcp.client import KISClient, KISError
from kis_mcp.server import make_service

SETTINGS = Settings("real", "test-key", "test-secret", "12345678", "01", "ISA")

class FakeTransport:
    def __init__(self, pages=None, headers=None):
        self.calls = []
        self.pages = pages or [{"rt_cd": "0", "output1": [{"pdno": "379800", "prdt_name": "S&P 500",
                         "hldg_qty": "3", "evlu_amt": "69000", "CANO": "secret"}],
                         "output2": [{"dnca_tot_amt": "1000", "sensitive_field": "secret"}]}]
        self.headers = headers or [{}]
    def __call__(self, url, method, headers, payload):
        self.calls.append((url, method, headers, payload))
        if "/oauth2/tokenP" in url:
            return 200, {}, json.dumps({"access_token": "secret-token", "expires_in": 3600}).encode()
        ix = sum("/inquire-balance" in x[0] for x in self.calls) - 1
        return 200, self.headers[min(ix,len(self.headers)-1)], json.dumps(self.pages[min(ix,len(self.pages)-1)]).encode()

class ClientTests(unittest.TestCase):
    def test_restrict_host_and_account(self):
        self.assertEqual(SETTINGS.base_url, HOSTS["real"])
        with patch.dict(os.environ, {"KIS_ENV": "https://evil.example"}, clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env()
        with patch.dict(os.environ, {"KIS_ENV": "real", "KIS_CANO": "bad"}, clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env()

    def test_status_no_credentials(self):
        s = SETTINGS.public_status()
        self.assertTrue(s["read_only"])
        self.assertFalse(s["trading_enabled"])
        self.assertNotIn("test-secret", str(s))
        self.assertNotIn("12345678", str(s))

    def test_balance_redaction_and_auth(self):
        t=FakeTransport()
        result=KISClient(SETTINGS,transport=t).domestic_balance()
        self.assertTrue(result["complete"])
        self.assertEqual(result["holdings"][0]["pdno"],"379800")
        self.assertNotIn("secret",str(result))
        self.assertNotIn("CANO",str(result))
        self.assertNotIn("12345678",str(result))
        self.assertEqual(t.calls[1][1],"GET")
        self.assertEqual(sum("/oauth2/tokenP" in x[0] for x in t.calls),1)

    def test_reject_order_path(self):
        c=KISClient(SETTINGS,transport=FakeTransport())
        with self.assertRaisesRegex(KISError,"allowlisted"):
            c._request("/uapi/domestic-stock/v1/trading/order-cash",
                method="GET",headers={})
        with self.assertRaisesRegex(KISError,"read-only"):
            c._request("/uapi/domestic-stock/v1/trading/inquire-balance",
                method="POST",headers={})

    def test_broker_error_fail_closed(self):
        t=FakeTransport([{"rt_cd":"1","msg1":"unknown secret","output1":[]}])
        with self.assertRaises(KISError) as e:
            KISClient(SETTINGS,transport=t).domestic_balance()
        self.assertNotIn("secret",str(e.exception))

    def test_multi_page(self):
        t=FakeTransport(
            pages=[
                {"rt_cd":"0","output1":[{"pdno":"A"}],"output2":[],"ctx_area_fk100":"next","ctx_area_nk100":"key"},
                {"rt_cd":"0","output1":[{"pdno":"B"}],"output2":[]},
            ],
            headers=[{"tr_cont":"M"},{}]
        )
        x=KISClient(SETTINGS,transport=t).domestic_balance()
        self.assertEqual(x["page_count"],2)
        self.assertEqual([z["pdno"] for z in x["holdings"]],["A","B"])
        self.assertIn("tr_cont",t.calls[2][2])

    def test_repeated_pagination_fails(self):
        t=FakeTransport(
            pages=[{"rt_cd":"0","output1":[],"ctx_area_fk100":"x","ctx_area_nk100":"y"}],
            headers=[{"tr_cont":"M"}]
        )
        with self.assertRaisesRegex(KISError,"repeating"):
            KISClient(SETTINGS,transport=t).domestic_balance()

    def test_settings_without_keys_fails_closed(self):
        t=FakeTransport()
        with self.assertRaisesRegex(KISError,"not configured"):
            KISClient(Settings("real","","","12345678","01","ISA"),transport=t).domestic_balance()
        self.assertFalse(t.calls)

    def test_service_failure_and_no_isa_claim(self):
        status,balance,export=make_service(Settings("real","","","","","ISA"))
        self.assertFalse(status()["isa_api_eligibility_verified"])
        self.assertFalse(balance()["ok"])
        self.assertFalse(export()["ok"])

if __name__ == "__main__":
    unittest.main()
