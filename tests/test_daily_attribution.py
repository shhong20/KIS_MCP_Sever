import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from kis_mcp.config import Settings
from kis_mcp.snapshots import capture_snapshot,snapshot_history

class DailyAttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"snapshots"
        self.settings=Settings("real","appkey","secret","12345678","01","ISA",True)
        self.data={
            "ok":True,"complete":True,"broker":"KIS","currency":"KRW",
            "holdings_count":2,"positions_match_securities_summary":True,
            "securities_krw_broker_reported":130000,
            "broker_reported_cash_krw":20000,
            "broker_reported_total_assets_krw":150000,
            "holdings":[
                {"market":"KR","symbol":"000660","name":"SK","quantity":1,"market_value_krw":100000},
                {"market":"KR","symbol":"360750","name":"ETF","quantity":1,"market_value_krw":30000},
            ],
        }
    def put(self,date,change=None):
        d=copy.deepcopy(self.data)
        if change:change(d)
        return capture_snapshot(self.settings,lambda:d,day=date,root=self.root)
    def test_cash_and_securities_are_separate_from_return(self):
        self.put("2026-11-12")
        def change(d):
            d["holdings"][0]["market_value_krw"]=105000
            d["securities_krw_broker_reported"]=135000
            d["broker_reported_cash_krw"]=10000
            d["broker_reported_total_assets_krw"]=145000
        self.put("2026-11-13",change)
        r=snapshot_history(self.settings,root=self.root)
        x=r["series"][1]
        self.assertEqual(x["securities_valuation_change_krw"],5000)
        self.assertEqual(x["reported_cash_change_krw"],-10000)
        self.assertEqual(x["broker_reported_total_assets_change_krw"],-5000)
        self.assertEqual(x["unchanged_quantity_attributed_change_krw"],5000)
        self.assertEqual(x["top_unchanged_quantity_contributors"][0]["symbol"],"000660")
        self.assertIsNone(x["actual_investment_return_pct"])
        self.assertFalse(r["return_calculation_available"])
    def test_quantity_change_keeps_unaffected_stock_contribution(self):
        self.put("2026-11-12")
        def change(d):
            d["holdings"][0]["quantity"]=2
            d["holdings"][0]["market_value_krw"]=202000
            d["holdings"][1]["market_value_krw"]=28000
            d["securities_krw_broker_reported"]=230000
            d["broker_reported_total_assets_krw"]=250000
        self.put("2026-11-13",change)
        x=snapshot_history(self.settings,root=self.root)["series"][1]
        self.assertFalse(x["same_position_quantities"])
        self.assertEqual(x["top_position_value_changes"],[])
        self.assertEqual(x["unchanged_quantity_attributed_change_krw"],-2000)
        self.assertEqual(x["quantity_changed_or_added_or_removed_symbols"],["000660"])
        self.assertIn("POSITION_QUANTITY_CHANGED_OR_MISSING",x["return_blockers"])
    def test_missing_day_is_not_daily_return(self):
        self.put("2026-11-12")
        self.put("2026-11-16")
        x=snapshot_history(self.settings,root=self.root)["series"][1]
        self.assertEqual(x["calendar_gap_days"],4)
        self.assertIn("OBSERVATION_NOT_NEXT_CALENDAR_DAY",x["return_blockers"])
        self.assertIsNone(x["actual_investment_profit_krw"])
    def test_weekend_record_is_not_trading_day_return(self):
        self.put("2026-11-20")
        self.put("2026-11-21")
        x=snapshot_history(self.settings,root=self.root)["series"][1]
        self.assertTrue(x["observation_on_weekend"])
        self.assertFalse(x["exchange_session_calendar_verified"])
        self.assertIn("WEEKEND_OBSERVATION_NOT_MARKET_RETURN",x["return_blockers"])
        self.assertIsNone(x["actual_investment_return_pct"])

    def test_settlement_difference_is_preserved_not_misdiagnosed_as_return(self):
        self.put("2026-11-12")
        def unsettled(d):
            d["broker_reported_total_assets_krw"] = 160000
        self.put("2026-11-13", unsettled)
        r = snapshot_history(self.settings, root=self.root)
        day = r["series"][1]
        self.assertEqual(day["reported_total_minus_cash_and_securities_krw"], 10000)
        self.assertFalse(day["reported_totals_internal_arithmetic_matches"])
        self.assertIn("BROKER_TOTAL_ARITHMETIC_UNVERIFIED_SETTLEMENT_PENDING", day["return_blockers"])
        self.assertIsNone(day["actual_investment_return_pct"])

    def test_previous_settlement_difference_is_retained_for_next_day(self):
        def unsettled(d):
            d["broker_reported_total_assets_krw"] = 160000
        self.put("2026-11-12", unsettled)
        self.put("2026-11-13")
        r = snapshot_history(self.settings, root=self.root)
        self.assertIn("BROKER_TOTAL_ARITHMETIC_UNVERIFIED_SETTLEMENT_PENDING", r["series"][1]["return_blockers"])
    def test_corrupt_stored_arithmetic_is_not_accepted(self):
        self.put("2026-11-12")
        p=next(self.root.glob("*/*.json"))
        import json
        obj=json.loads(p.read_text())
        obj["securities_value_krw"]=999999
        p.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError,"does not reconcile"):
            snapshot_history(self.settings,root=self.root)

if __name__=="__main__":
    unittest.main()
