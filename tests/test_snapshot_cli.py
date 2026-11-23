import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kis_mcp import capture_daily

class SnapshotCliTests(unittest.TestCase):
    @patch("kis_mcp.capture_daily.capture_snapshot")
    @patch("kis_mcp.capture_daily.make_service")
    @patch("kis_mcp.capture_daily.Settings.from_env")
    def test_sanitized_success(self, settings, make_service, capture):
        settings.return_value = object()
        make_service.return_value = (None, None, lambda: None)
        capture.return_value = {"date":"2026-11-23","created":True,"broker_calls_skipped":False}
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(capture_daily.main(), 0)
        self.assertEqual(json.loads(stream.getvalue())["decision"], "KIS_SNAPSHOT_OK")
        self.assertNotIn("account", stream.getvalue().lower().replace("account_data_redacted",""))
    @patch("kis_mcp.capture_daily.capture_snapshot", side_effect=ValueError("Secret1234"))
    @patch("kis_mcp.capture_daily.make_service")
    @patch("kis_mcp.capture_daily.Settings.from_env")
    def test_failure_never_leaks_error_text(self, settings, make_service, capture):
        settings.return_value = object()
        make_service.return_value = (None, None, lambda: None)
        stream = io.StringIO()
        with redirect_stderr(stream):
            self.assertEqual(capture_daily.main(), 1)
        self.assertNotIn("Secret1234", stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())["decision"], "KIS_SNAPSHOT_FAILED")

if __name__ == "__main__":
    unittest.main()
