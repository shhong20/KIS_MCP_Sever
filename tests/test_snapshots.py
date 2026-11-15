import copy
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kis_mcp.config import Settings
from kis_mcp.snapshots import capture_snapshot, snapshot_history


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "snapshots"
        self.settings = Settings("real", "app-key", "secret", "12345678", "01", "ISA", True)
        self.export = {
            "ok": True, "complete": True, "broker": "KIS", "currency": "KRW",
            "holdings_count": 2, "positions_match_securities_summary": True,
            "securities_krw_broker_reported": 130000,
            "broker_reported_cash_krw": 20000,
            "broker_reported_total_assets_krw": 150000,
            "holdings": [
                {"market": "KR", "symbol": "000660", "name": "SK", "quantity": 1, "market_value_krw": 100000},
                {"market": "KR", "symbol": "360750", "name": "TIGER", "quantity": 1, "market_value_krw": 30000},
            ],
        }

    def capture(self, day="2026-11-12", export=None):
        return capture_snapshot(self.settings, lambda: copy.deepcopy(export or self.export),
                                day=day, root=self.root, captured_at="2026-11-12T07:20:00+00:00")

    def test_immutable_duplicate_and_no_extra_broker_call(self):
        first = self.capture()
        self.assertEqual(first["securities_value_krw"], 130000)
        self.assertTrue(first["created"])
        called = []
        second = capture_snapshot(self.settings, lambda: called.append("BROKER_CALLED"),
                                  day="2026-11-12", root=self.root)
        self.assertFalse(second["created"])
        self.assertTrue(second["broker_calls_skipped"])
        self.assertEqual(called, [])
        files = list(self.root.glob("*/*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(files[0].parent.stat().st_mode), 0o700)
        self.assertNotIn("12345678", files[0].as_posix())
        self.assertNotIn("secret", str(first))

    def test_history_gap_and_position_contribution(self):
        self.capture()
        next_export = copy.deepcopy(self.export)
        next_export["holdings"][0]["market_value_krw"] = 95000
        next_export["securities_krw_broker_reported"] = 125000
        next_export["broker_reported_total_assets_krw"] = 145000
        self.capture("2026-11-14", next_export)
        result = snapshot_history(self.settings, "2026-11", root=self.root)
        self.assertEqual(result["observations"], 2)
        self.assertIsNone(result["series"][0]["securities_valuation_change_krw"])
        self.assertEqual(result["series"][1]["securities_valuation_change_krw"], -5000)
        self.assertEqual(result["series"][1]["calendar_gap_days"], 2)
        self.assertTrue(result["series"][1]["same_position_quantities"])
        self.assertEqual(result["series"][1]["top_position_value_changes"][0]["symbol"], "000660")
        self.assertFalse(result["return_calculation_available"])

    def test_trade_changes_disable_per_position_attribution(self):
        self.capture()
        d = copy.deepcopy(self.export)
        d["holdings"][0]["quantity"] = 2
        self.capture("2026-11-13", d)
        row = snapshot_history(self.settings, root=self.root)["series"][-1]
        self.assertFalse(row["same_position_quantities"])
        self.assertEqual(row["top_position_value_changes"], [])

    def test_fail_closed_on_bad_or_incomplete_export(self):
        for mutation in ("bad_status", "bad_amount", "sum_mismatch", "duplicate", "negative_cash"):
            d = copy.deepcopy(self.export)
            if mutation == "bad_status":
                d["complete"] = False
            elif mutation == "bad_amount":
                d["holdings"][0]["market_value_krw"] = "100000"
            elif mutation == "sum_mismatch":
                d["securities_krw_broker_reported"] += 1
            elif mutation == "duplicate":
                d["holdings"][1]["symbol"] = "000660"
            elif mutation == "negative_cash":
                d["broker_reported_cash_krw"] = -1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.capture(export=d)
            self.assertEqual(list(self.root.glob("*/*.json")), [])

    def test_separate_accounts_and_reject_unsafe_file(self):
        self.capture()
        other = Settings("real", "app-key", "secret", "87654321", "01", "ISA", True)
        self.assertEqual(snapshot_history(other, root=self.root)["observations"], 0)
        file = next(self.root.glob("*/*.json"))
        os.chmod(file, 0o644)
        with self.assertRaises(ValueError):
            snapshot_history(self.settings, root=self.root)

    def test_invalid_month_and_future_day(self):
        with self.assertRaises(ValueError):
            snapshot_history(self.settings, "2026-13", root=self.root)
        with self.assertRaises(ValueError):
            self.capture("2099-11-11")


if __name__ == "__main__":
    unittest.main()
