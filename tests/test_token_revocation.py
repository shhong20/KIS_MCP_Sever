import json, sys, unittest
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from kis_mcp.client import KISClient,KISError
from kis_mcp.config import Settings
from kis_mcp.buyability import query_buyable

CONFIG=Settings("real","fake-key","fake-secret","12345678","01","ISA",True)
class ExpiredTokenTransport:
    def __init__(self, recover=True, one_401_only=True):
        self.token_calls=0
        self.balance_calls=0
        self.recover=recover
        self.one_401_only=one_401_only
    def __call__(self,url,method,headers,payload):
        if "/oauth2/tokenP" in url:
            self.token_calls+=1
            return 200,{},json.dumps({"access_token":"new-token-"+str(self.token_calls),"expires_in":3600}).encode()
        self.balance_calls+=1
        if self.balance_calls==1 or not self.recover:
            return 401,{},b"not for display"
        if "/inquire-psbl-order" in url:
            return 200,{},json.dumps({"rt_cd":"0","output":{"nrcvb_buy_amt":"10000","nrcvb_buy_qty":"1"}}).encode()
        return 200,{},json.dumps({"rt_cd":"0","output1":[],"output2":[{"dnca_tot_amt":"0","scts_evlu_amt":"0","tot_evlu_amt":"0"}]}).encode()

class KISStaleTokenTest(unittest.TestCase):
    def test_401_retries_once_without_secrets(self):
        t=ExpiredTokenTransport()
        c=KISClient(CONFIG,transport=t)
        out=c.domestic_balance()
        self.assertTrue(out["complete"])
        self.assertEqual(t.balance_calls,2)
        self.assertEqual(t.token_calls,2)
        self.assertNotIn("fake-secret",str(out))
    def test_401_repeated_stops(self):
        t=ExpiredTokenTransport(recover=False)
        with self.assertRaises(KISError) as cm:
            KISClient(CONFIG,transport=t).domestic_balance()
        self.assertEqual(t.balance_calls,2)
        self.assertEqual(t.token_calls,2)
        self.assertNotIn("fake-secret",str(cm.exception))
    def test_401_readonly_buyability(self):
        t=ExpiredTokenTransport()
        out=query_buyable(KISClient(CONFIG,transport=t),"379800",20000)
        self.assertTrue(out["ok"])
        self.assertTrue(out["not_an_order"])
        self.assertEqual(t.balance_calls,2)
    def test_disk_cache_revoked_then_refreshed(self):
        with TemporaryDirectory() as temp:
            with patch("kis_mcp.client.Path.home",return_value=Path(temp)):
                t=ExpiredTokenTransport()
                c=KISClient(CONFIG,transport=t)
                c._allow_disk_cache=True
                out=c.domestic_balance()
                self.assertTrue(out["complete"])
                self.assertEqual(t.token_calls,2)
                cache=list((Path(temp)/".local/state/kis-mcp").glob("token-*.json"))
                self.assertEqual(len(cache),1)
                self.assertEqual(cache[0].stat().st_mode&0o777,0o600)
                obj=json.loads(cache[0].read_text())
                self.assertEqual(obj["token"],"new-token-2")
if __name__=="__main__":unittest.main()
