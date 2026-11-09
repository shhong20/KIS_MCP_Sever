import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kis_mcp.etf_allocation import allocate_etf_sleeve,TARGETS
Q={'379800':22570,'161510':21780,'458730':15220,'241180':30560,'214980':114725,'411060':25045}
class AllocationTest(unittest.TestCase):
 def setUp(self):
  self.isa={'ok':True,'complete':True,'positions_match_securities_summary':True,
   'holdings':[{'symbol':'000660','market':'KR','quantity':1,'market_value_krw':1163000}]}
 def test_simulator_not_order(self):
  x=allocate_etf_sleeve(self.isa,Q,137031,cash_ceiling_krw=137031)
  self.assertTrue(x['ok']);self.assertFalse(x['orders_submitted'])
  self.assertEqual(x['non_target_KIS_securities_krw'],1163000)
  self.assertEqual(sum(y['target_weight_pct'] for y in x['items']),100)
  self.assertEqual(x['suggested_total_krw']+x['unallocated_krw'],137031)
  self.assertLessEqual(x['suggested_total_krw'],137031)
  self.assertFalse(x['prices_verified_live'])
 def test_budget_ceiling(self):
  x=allocate_etf_sleeve(self.isa,Q,300000,cash_ceiling_krw=100000)
  self.assertEqual(x['budget_krw'],100000)
  self.assertLessEqual(x['suggested_total_krw'],100000)
 def test_holds_etf_uses_existing_sleeve(self):
  self.isa['holdings'].append({'symbol':'379800','market':'KR','quantity':5,'market_value_krw':110000})
  x=allocate_etf_sleeve(self.isa,Q,150000)
  self.assertEqual(x['current_target_etf_securities_krw'],110000)
  self.assertEqual(x['items'][0]['current_quantity'],5)
 def test_incomplete_rejected(self):
  self.isa['positions_match_securities_summary']=False
  self.assertFalse(allocate_etf_sleeve(self.isa,Q,300000)['ok'])
 def test_missing_and_negative_quote_rejected(self):
  for q in [{**Q,'161510':-10},{k:v for k,v in Q.items() if k!='161510'},{**Q,'161510':True}]:
   self.assertFalse(allocate_etf_sleeve(self.isa,q,300000)['ok'])
 def test_no_cash(self):
  x=allocate_etf_sleeve(self.isa,Q,0)
  self.assertEqual(x['suggested_total_krw'],0)
  self.assertEqual(sum(y['suggested_quantity'] for y in x['items']),0)
if __name__=='__main__':unittest.main()
