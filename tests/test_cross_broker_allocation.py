import copy, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kis_mcp.cross_broker_allocation import combined_exposure
from kis_mcp.reconcile import ReconciliationError

class CrossBrokerAllocationTests(unittest.TestCase):
    def setUp(self):
        self.nh = {
            "scope": "domestic_KR_and_overseas_US_securities_only",
            "market_value_krw": 2300000,
            "positions": [
                {"market":"KR","symbol":"000660","quantity":1,"market_value_krw":1000000},
                {"market":"US","symbol":"TSM","quantity":1,"market_value_krw":800000},
                {"market":"KR","symbol":"379800","quantity":20,"market_value_krw":500000},
            ],
        }
        self.kis = {
            "ok":True,"complete":True,"broker":"KIS","currency":"KRW",
            "positions_match_securities_summary":True,
            "securities_krw_rows":1250000,"securities_krw_broker_reported":1250000,
            "account_type":"ISA","account_type_source":"user_confirmed",
            "holdings":[
                {"broker":"KIS","market":"KR","symbol":"000660","quantity":1,"market_value_krw":1100000},
                {"broker":"KIS","market":"KR","symbol":"161510","quantity":5,"market_value_krw":150000},
            ],
        }
    def test_combined_direct_and_unknown_etf_exposure(self):
        x=combined_exposure(self.nh,self.kis,monthly_investment_krw=300000)
        self.assertEqual(x["combined_securities_krw"],3550000)
        self.assertEqual(x["direct_named_semiconductor_krw"],2900000)
        self.assertEqual(x["etf_total_value_krw"],650000)
        self.assertEqual(x["unmapped_etf_exposure_krw"],650000)
        self.assertEqual(x["target_etf_sleeve_current_krw"],650000)
        self.assertIsNone(x["verified_combined_net_assets_krw"])
        self.assertFalse(x["orders_submitted"])
        self.assertEqual(x["cross_broker_duplicates"][0]["symbol"],"000660")
        self.assertEqual(sum(z["weight_pct"] for z in x["monthly_etf_target_shortfalls"]),100)
    def test_partial_lookthrough_only_named_semis(self):
        data={"funds":[{"symbol":"379800","as_of":"2026-11-06",
             "source_url":"https://example.com/holdings",
             "holdings":[{"market":"US","symbol":"INTC","region":"US","weight_bps":300},
                         {"market":"US","symbol":"AAPL","region":"US","weight_bps":250}]}]}
        x=combined_exposure(self.nh,self.kis,lookthrough=data)
        self.assertEqual(x["mapped_etf_semiconductor_krw_conditional"],15000)
        self.assertEqual(x["unmapped_etf_exposure_krw"],622500)
        self.assertEqual(x["caller_mapped_etf_region_value_krw_conditional"]["US"],27500)
        self.assertEqual(next(row["status"] for row in x["etf_lookthrough"] if row["symbol"]=="379800"),"CALLER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED")
    def test_bad_weight_rejected(self):
        data={"funds":[{"symbol":"379800","as_of":"2026-11-06","source_url":"https://x",
             "holdings":[{"market":"US","symbol":"INTC","region":"US","weight_bps":9800},
                         {"market":"US","symbol":"AAPL","region":"US","weight_bps":500}]}]}
        with self.assertRaises(ReconciliationError):
            combined_exposure(self.nh,self.kis,lookthrough=data)
    def test_duplicate_fund_rejected(self):
        row={"symbol":"379800","as_of":"2026-11-06","source_url":"https://x",
             "holdings":[{"market":"US","symbol":"INTC","region":"US","weight_bps":100}]}
        with self.assertRaises(ReconciliationError):
            combined_exposure(self.nh,self.kis,lookthrough={"funds":[row,row]})
    def test_source_totals_rejected(self):
        invalid=copy.deepcopy(self.nh)
        invalid["market_value_krw"]=123
        with self.assertRaises(ReconciliationError):
            combined_exposure(invalid,self.kis)
    def test_monthly_negative_rejected(self):
        with self.assertRaises(ReconciliationError):
            combined_exposure(self.nh,self.kis,monthly_investment_krw=-1)
    def test_no_full_nav_claim(self):
        x=combined_exposure(self.nh,self.kis)
        self.assertIsNone(x["verified_combined_net_assets_krw"])
        self.assertEqual(x["provenance"].startswith("NH caller-supplied"),True)
if __name__=="__main__":
    unittest.main()
