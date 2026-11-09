import sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from kis_mcp.etf_official import (
    ConstituentsError, parse_official_plus, fetch_official_plus, save_snapshot,
    read_fresh_official_cache, public_snapshot, PLUS_URL
)

def html(when="2026-11-09",weights=None):
    weights=weights or [6.49,5.74,5.61,5.14,4.8,4.7,4.4,4.3,4.21,4.19]
    rows="".join(
        f'<tr><td style="display:none">{i+1}</td><td>{i+5000:06d}</td>'
        f'<td>Company {i}</td><td>10</td><td>{w:.2f}%</td></tr>'
        for i,w in enumerate(weights))
    return (f'<input id="pdfDate" data-max-date="{when}" data-format="{when}"/>'
            f'<table><tbody id="pdfListBody">{rows}</tbody></table>').encode()

class IssuerETFFeedTests(unittest.TestCase):
    def test_valid_partial_only_with_date_provenance(self):
        x=parse_official_plus(html(),today=date(2026,11,9))
        self.assertEqual(x["symbol"],"161510")
        self.assertEqual(len(x["holdings"]),10)
        self.assertTrue(x["partial_holdings_only"])
        self.assertLess(x["coverage_weight_bps"],10000)
        self.assertEqual(x["source_url"],PLUS_URL)
        self.assertEqual(public_snapshot(x)["funds"][0]["as_of"],"2026-11-09")
    def test_fake_fetcher_no_network(self):
        x=fetch_official_plus(today=date(2026,11,9),fetcher=lambda url:html())
        self.assertEqual(x["source_type"],"OFFICIAL_ISSUER_PRODUCT_HTML")
    def test_stale_or_future_date_rejected(self):
        for when in ("2026-11-02","2026-11-10"):
            with self.assertRaises(ConstituentsError):
                parse_official_plus(html(when),today=date(2026,11,9))
    def test_excess_weights_rejected(self):
        with self.assertRaises(ConstituentsError):
            parse_official_plus(html(weights=[11.0]*10),today=date(2026,11,9))
    def test_duplicate_ticker_rejected(self):
        payload=html().replace(b"005001",b"005000")
        with self.assertRaises(ConstituentsError):
            parse_official_plus(payload,today=date(2026,11,9))
    def test_missing_table_rejected(self):
        with self.assertRaises(ConstituentsError):
            parse_official_plus(html().replace(b'pdfListBody',b'otherTable'),today=date(2026,11,9))
    def test_safe_cache_and_stale_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"private"/"latest.json"
            snap=parse_official_plus(html(),today=date(2026,11,9))
            save_snapshot(snap,p)
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            self.assertIsNotNone(read_fresh_official_cache(today=date(2026,11,10),path=p))
            self.assertIsNone(read_fresh_official_cache(today=date(2026,11,20),path=p))
    def test_old_cache_no_auto_promote(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"private"/"latest.json"
            snap=parse_official_plus(html(),today=date(2026,11,9))
            save_snapshot(snap,p)
            p.write_text(p.read_text().replace(PLUS_URL,"https://example.org/false"))
            self.assertIsNone(read_fresh_official_cache(today=date(2026,11,9),path=p))

if __name__=="__main__":unittest.main()
