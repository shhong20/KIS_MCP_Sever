import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kis_mcp.config import Settings
from kis_mcp.normalize import normalize_balance
class NormalizationTests(unittest.TestCase):
 def setUp(self):
  self.s=Settings('real','key','secret','12345678','01','ISA',True)
  self.data={'complete':True,'holdings':[{'pdno':'000660','prdt_name':'SK','hldg_qty':'1','evlu_amt':'1176000'}], 'summary':{'dnca_tot_amt':'137717','scts_evlu_amt':'1176000','tot_evlu_amt':'1313717'}}
 def test_user_confirmed_provenance(self):
  r=normalize_balance(self.data,self.s)
  self.assertTrue(r['ok']);self.assertEqual(r['account_type'],'ISA');self.assertEqual(r['account_type_source'],'user_confirmed');self.assertFalse(r['isa_api_eligibility_verified'])
 def test_money_consistency_without_double_count(self):
  r=normalize_balance(self.data,self.s)
  self.assertTrue(r['positions_match_securities_summary']);self.assertTrue(r['sum_position_plus_cash_equals_broker_total']);self.assertFalse(r['cash_is_order_buyable']);self.assertEqual(r['holdings'][0]['quantity'],1)
 def test_unconfirmed_label_does_not_imply_isa(self):
  s=Settings('real','key','secret','12345678','01','ISA')
  self.assertEqual(normalize_balance(self.data,s)['account_type'],'unverified')
 def test_missing_data_fails_closed(self):
  self.assertFalse(normalize_balance({'complete':True,'holdings':[], 'summary':{}},self.s)['ok'])
  self.data['holdings'][0]['evlu_amt']='invalid'
  self.assertFalse(normalize_balance(self.data,self.s)['ok'])
 def test_no_secret_or_account_id(self):
  self.assertNotIn('12345678',str(normalize_balance(self.data,self.s)))
  self.assertNotIn('secret',str(normalize_balance(self.data,self.s)))
if __name__=='__main__':unittest.main()
