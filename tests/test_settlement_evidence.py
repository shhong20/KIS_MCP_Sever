"""Settlement source fields remain evidence, never a computed full NAV."""
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kis_mcp.config import Settings
from kis_mcp.normalize import normalize_balance
from kis_mcp.snapshots import capture_snapshot, snapshot_history


class SettlementEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "snapshots"
        self.settings = Settings("real", "key", "secret", "12345678", "01", "ISA", True)
        self.raw = {
            "complete": True,
            "holdings": [{"pdno": "000660", "prdt_name": "SK",
                          "hldg_qty": "1", "evlu_amt": "120000"}],
            "summary": {"dnca_tot_amt": "25000", "scts_evlu_amt": "120000",
                        "tot_evlu_amt": "150000",
                        "nxdy_excc_amt": "-5000", "prvs_rcdl_excc_amt": "30000"},
        }

    def capture(self, day, raw=None):
        exported = normalize_balance(raw or self.raw, self.settings)
        return capture_snapshot(
            self.settings, lambda: exported, day=day, root=self.root,
            captured_at=day + "T11:35:00+09:00",
        )

    def test_normalized_settlement_is_raw_signed_and_not_a_nav_adjustment(self):
        normalized = normalize_balance(self.raw, self.settings)
        self.assertEqual(normalized["broker_reported_settlement_fields_krw"],
                         {"nxdy_excc_amt": -5000, "prvs_rcdl_excc_amt": 30000})
        self.assertEqual(normalized["broker_reported_total_assets_krw"], 150000)
        self.assertEqual(normalized["broker_reported_cash_krw"], 25000)
        self.assertFalse(normalized["sum_position_plus_cash_equals_broker_total"])
        self.assertNotIn("12345678", str(normalized))
        self.assertNotIn("secret", str(normalized))

    def test_capture_and_history_preserve_evidence_but_not_return(self):
        self.assertTrue(self.capture("2026-11-20")["created"])
        history = snapshot_history(self.settings, "2026-11", root=self.root)
        row = history["series"][0]
        self.assertTrue(row["settlement_evidence_captured"])
        self.assertFalse(row["settlement_accounting_mapping_verified"])
        self.assertEqual(row["reported_settlement_fields_krw"]["nxdy_excc_amt"], -5000)
        self.assertEqual(row["reported_total_minus_cash_and_securities_krw"], 5000)
        self.assertFalse(row["reported_totals_internal_arithmetic_matches"])
        self.assertIsNone(row["actual_investment_return_pct"])
        self.assertFalse(history["return_calculation_available"])

    def test_missing_legacy_evidence_remains_unknown_not_zero(self):
        old = normalize_balance(self.raw, self.settings)
        old.pop("broker_reported_settlement_fields_krw")
        capture_snapshot(self.settings, lambda: old, day="2026-11-19",
                         root=self.root)
        self.capture("2026-11-20")
        out = snapshot_history(self.settings, root=self.root)["series"]
        self.assertIsNone(out[0]["reported_settlement_fields_krw"])
        self.assertFalse(out[0]["settlement_evidence_captured"])
        self.assertIsNone(out[1]["previous_reported_settlement_fields_krw"])
        self.assertIsNone(out[0]["actual_investment_profit_krw"])

    def test_missing_field_is_unknown(self):
        raw = json.loads(json.dumps(self.raw))
        raw["summary"].pop("nxdy_excc_amt")
        self.capture("2026-11-20", raw)
        value = snapshot_history(self.settings, root=self.root)["series"][0]
        self.assertIsNone(value["reported_settlement_fields_krw"]["nxdy_excc_amt"])
        self.assertEqual(value["reported_settlement_fields_krw"]["prvs_rcdl_excc_amt"], 30000)

    def test_invalid_field_fails_before_creating_snapshot(self):
        for invalid in ["10000", True, 10**16]:
            with self.subTest(invalid=invalid):
                exported = normalize_balance(self.raw, self.settings)
                exported["broker_reported_settlement_fields_krw"]["nxdy_excc_amt"] = invalid
                with self.assertRaises(ValueError):
                    capture_snapshot(self.settings, lambda: exported,
                                     day="2026-11-20", root=self.root)
                self.assertEqual(list(self.root.glob("*/*.json")), [])

    def test_tamper_evidence_fails_closed_when_read(self):
        self.capture("2026-11-20")
        file = next(self.root.glob("*/*.json"))
        data = json.loads(file.read_text())
        data["reported_settlement_fields_krw"]["nxdy_excc_amt"] = "invalid"
        file.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "settlement evidence invalid"):
            snapshot_history(self.settings, root=self.root)


if __name__ == "__main__":
    unittest.main()
