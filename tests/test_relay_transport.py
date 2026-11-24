import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from kis_mcp.client import KISClient,KISError
from kis_mcp.relay_transport import relay_request

class RelayTests(unittest.TestCase):
    def test_external_destination_denied(self):
        with self.assertRaises(ValueError):
            relay_request("https://outside.invalid/","HEAD",{},None,"/nonexistent")
    def test_configured_relay_never_falls_back(self):
        for path in ("","/nonexistent/broker.sock"):
            with patch.dict(os.environ,{"KIS_BROKER_RELAY_SOCKET":path}),patch("kis_mcp.client.request.build_opener") as direct:
                with self.assertRaises(KISError):
                    KISClient._urlopen_transport("https://openapi.koreainvestment.com:9443/","HEAD",{},None)
                direct.assert_not_called()
if __name__=="__main__":unittest.main()
