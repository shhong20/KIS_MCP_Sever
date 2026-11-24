import sys, json, time, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from kis_mcp.cache_crypto import seal,unseal
from kis_mcp.client import KISClient,KISError
from kis_mcp.config import Settings

class CacheCrypto(unittest.TestCase):
    def test_auth_encryption(self):
        value={"token":"SYNTHETIC_TOKEN","expires_at":time.time()+3600}
        obj=seal(value,"secret","scope","aes-gcm-v1")
        self.assertNotIn(value["token"],json.dumps(obj))
        self.assertEqual(unseal(obj,"secret","scope","aes-gcm-v1")[0],value)
        with self.assertRaises(ValueError):unseal(obj,"wrong","scope","aes-gcm-v1")
        with self.assertRaises(ValueError):unseal(obj,"secret","wrong-scope","aes-gcm-v1")
    def test_migrate_and_tamper_fail_closed(self):
        settings=Settings("real","test-key","test-secret","12345678","01","ISA")
        with tempfile.TemporaryDirectory() as root, patch("kis_mcp.client.Path.home",return_value=Path(root)):
            def forbid(*args):self.fail("network forbidden")
            c=KISClient(settings,transport=forbid);c._allow_disk_cache=True
            f=c._cache_file()
            expiry=time.time()+3600
            f.write_text(json.dumps({"token":"SYNTHETIC_TOKEN","expires_at":expiry}));f.chmod(0o600)
            self.assertEqual(c._token(),"SYNTHETIC_TOKEN")
            raw=f.read_text()
            self.assertNotIn("SYNTHETIC_TOKEN",raw)
            self.assertEqual(c._read_cache(f)[0]["expires_at"],expiry)
            obj=json.loads(raw);obj["blob"]="AAAA";f.write_text(json.dumps(obj))
            other=KISClient(settings,transport=forbid);other._allow_disk_cache=True
            with self.assertRaises(KISError):other._token()

if __name__=="__main__":unittest.main()
