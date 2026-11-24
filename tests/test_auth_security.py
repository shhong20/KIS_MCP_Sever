import json,sys,unittest,multiprocessing,time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from kis_mcp.client import KISClient,KISError,_NoRedirect
from kis_mcp.config import Settings
from urllib import request
C=Settings("real","TEST_KEY","TEST_SECRET","12345678","01","ISA",True)

def worker(home,queue):
    with patch("kis_mcp.client.Path.home",return_value=Path(home)):
        calls=0
        def transport(*args):
            nonlocal calls
            calls+=1
            time.sleep(.2)
            return 200,{},json.dumps({"access_token":"TEST_TOKEN","expires_in":7200}).encode()
        c=KISClient(C,transport=transport)
        c._allow_disk_cache=True
        c._token()
        queue.put(calls)

def hold_lock(home,ready):
    with patch("kis_mcp.client.Path.home",return_value=Path(home)):
        c=KISClient(C)
        with c._token_lock():
            ready.set()
            time.sleep(60)

class Security(unittest.TestCase):
    def test_crash_releases_lock(self):
        with TemporaryDirectory() as temp:
            ctx=multiprocessing.get_context("fork")
            ready=ctx.Event()
            p=ctx.Process(target=hold_lock,args=(temp,ready))
            p.start()
            try:
                self.assertTrue(ready.wait(5))
                p.kill()
                p.join(5)
                self.assertFalse(p.is_alive())
                with patch("kis_mcp.client.Path.home",return_value=Path(temp)):
                    c=KISClient(C)
                    start=time.monotonic()
                    with c._token_lock():
                        self.assertLess(time.monotonic()-start,2)
            finally:
                if p.is_alive():p.kill()
                p.join()

    def test_host_redirect_and_proxy(self):
        with self.assertRaises(KISError):
            KISClient._urlopen_transport("https://evil.invalid/token","POST",{},b"")
        with self.assertRaises(KISError):
            _NoRedirect().redirect_request(None,None,307,"",{},"https://evil.invalid")
        with patch("kis_mcp.client.request.build_opener") as opener:
            response=opener.return_value.open.return_value.__enter__.return_value
            response.status=200
            response.headers={}
            response.read.return_value=b"{}"
            KISClient._urlopen_transport(C.base_url+"/oauth2/tokenP","POST",{},b"")
            handlers=opener.call_args.args
            self.assertEqual(handlers[0].proxies,{})
            self.assertIsInstance(handlers[1],_NoRedirect)
    def test_status_does_not_issue(self):
        with TemporaryDirectory() as temp, patch("kis_mcp.client.Path.home",return_value=Path(temp)):
            c=KISClient(C,transport=lambda *a: self.fail("unexpected transport"))
            s=c.auth_security_status()
            self.assertFalse(s["disk_valid"])
            c._save_cached_token("TEST_TOKEN",time.time()+7200)
            s=c.auth_security_status()
            self.assertTrue(s["disk_valid"])
            for secret in ("TEST_KEY","TEST_SECRET","TEST_TOKEN","12345678"):
                self.assertNotIn(secret,json.dumps(s))
    def test_concurrent_processes(self):
        with TemporaryDirectory() as temp:
            ctx=multiprocessing.get_context("fork")
            q=ctx.Queue()
            ps=[ctx.Process(target=worker,args=(temp,q)) for _ in range(5)]
            for p in ps:p.start()
            try:
                for p in ps:
                    p.join(8)
                    self.assertEqual(p.exitcode,0)
                self.assertEqual(sum(q.get(timeout=2) for _ in ps),1)
            finally:
                for p in ps:
                    if p.is_alive():p.terminate()
                    p.join()
                q.close()

if __name__=="__main__":unittest.main()
