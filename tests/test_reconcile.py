import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kis_mcp.reconcile import reconcile_portfolios, ReconciliationError

class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.nh = {"scope":"domestic_KR_and_overseas_US_securities_only",
                   "market_value_krw": 2500000,
                   "positions":[
                       {"market":"KR","symbol":"000660","quantity":1,"market_value_krw":1000000},
                       {"market":"KR","symbol":"005930","quantity":6,"market_value_krw":1000000},
                       {"market":"US","symbol":"AAPL","quantity":1,"market_value_krw":500000}]}
        self.kis = {"ok":True,"complete":True,"broker":"KIS","currency":"KRW",
                    "account_type":"ISA","account_type_source":"user_confirmed",
                    "positions_match_securities_summary":True,
                    "securities_krw_rows":1100000,"securities_krw_broker_reported":1100000,
                    "broker_reported_cash_krw": 222000,"broker_reported_total_assets_krw":1322000,
                    "holdings":[{"broker":"KIS","market":"KR","symbol":"000660","quantity":1,"market_value_krw":1100000}]}
    def test_duplicates_and_independent_accounts(self):
        x=reconcile_portfolios(self.nh,self.kis,nh_audit_status="UNRECONCILED_ACCOUNTING")
        self.assertEqual(x["combined_securities_krw"],3600000)
        self.assertEqual(x["verified_combined_net_assets_krw"],None)
        self.assertEqual(x["duplicate_cross_broker_symbols"][0]["quantity"],2)
        self.assertEqual(x["duplicate_cross_broker_symbols"][0]["market_value_krw"],2100000)
        self.assertEqual(len(x["duplicate_cross_broker_symbols"][0]["sources"]),2)
        self.assertEqual(x["semiconductor_direct_value_krw"],3100000)
        self.assertEqual(x["semiconductor_direct_weight_pct"],86.11)
        self.assertTrue(x["cash_not_added"])
        self.assertEqual(x["nh_input_provenance"],"caller_supplied_not_authenticated")
    def test_strict_total_mismatch(self):
        nh=copy.deepcopy(self.nh);nh["market_value_krw"]+=1
        with self.assertRaisesRegex(ReconciliationError,"NH securities total"):
            reconcile_portfolios(nh,self.kis)
    def test_non_numeric_amounts_blocked(self):
        k=copy.deepcopy(self.kis);k["holdings"][0]["market_value_krw"]="not-a-number"
        with self.assertRaises(ReconciliationError):reconcile_portfolios(self.nh,k)
    def test_incomplete_or_unreconciled_kis_blocked(self):
        k=copy.deepcopy(self.kis);k["positions_match_securities_summary"]=False
        with self.assertRaises(ReconciliationError):reconcile_portfolios(self.nh,k)
        k["positions_match_securities_summary"]=True;k["complete"]=False
        with self.assertRaises(ReconciliationError):reconcile_portfolios(self.nh,k)
    def test_cross_market_same_ticker_not_merged(self):
        nh=copy.deepcopy(self.nh)
        nh["positions"][2]["symbol"]="000660"
        x=reconcile_portfolios(nh,self.kis)
        self.assertEqual(len(x["duplicate_cross_broker_symbols"]),1)
        self.assertEqual(x["duplicate_cross_broker_symbols"][0]["market"],"KR")
        self.assertEqual(len(x["aggregated"]),3)
    def test_invalid_symbol_or_market(self):
        nh=copy.deepcopy(self.nh);nh["positions"][0]["symbol"]="^evil"
        with self.assertRaises(ReconciliationError):reconcile_portfolios(nh,self.kis)
        nh["positions"][0]["symbol"]="000660";nh["positions"][0]["market"]="EU"
        with self.assertRaises(ReconciliationError):reconcile_portfolios(nh,self.kis)

if __name__=="__main__":
    unittest.main()
