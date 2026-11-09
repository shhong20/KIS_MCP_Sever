import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kis_mcp.config import Settings
from kis_mcp.client import KISClient,KISError
from kis_mcp.buyability import query_buyable
S=Settings('real','test-key','test-secret','12345678','01','ISA',True)
class Transport:
 def __init__(self, response=None):
  self.calls=[]
  self.response=response or {'rt_cd':'0','output':{'ord_psbl_cash':'137717','nrcvb_buy_amt':'137031','nrcvb_buy_qty':'6','max_buy_amt':'190000'}}
 def __call__(self,url,method,headers,body):
  self.calls.append((url,method,headers))
  if '/oauth2/tokenP' in url:return 200,{},json.dumps({'access_token':'mock-token','expires_in':3600}).encode()
  return 200,{},json.dumps(self.response).encode()
class BuyabilityTest(unittest.TestCase):
 def test_broker_no_margin_only(self):
  t=Transport();r=query_buyable(KISClient(S,transport=t),'379800',22600)
  self.assertTrue(r['ok']);self.assertEqual(r['no_margin_buy_quantity'],6)
  self.assertEqual(r['no_margin_buy_amount_krw'],137031)
  self.assertNotEqual(r['max_buy_amount_with_possible_margin_krw'],r['no_margin_buy_amount_krw'])
  self.assertTrue(r['not_an_order']);self.assertEqual(t.calls[-1][1],'GET')
  self.assertIn('tr_id',t.calls[-1][2]);self.assertNotIn('12345678',str(r))
 def test_invalid_input_fails_before_any_http(self):
  for sym,price in [('Evil',100),('379800',0),('379800',True),('379800',-1)]:
   t=Transport();c=KISClient(S,transport=t)
   with self.assertRaises(KISError):query_buyable(c,sym,price)
   self.assertEqual(t.calls,[])
 def test_failure_does_not_claim_cash(self):
  t=Transport({'rt_cd':'1','msg_cd':'APBK9999','msg1':'PRIVATE DATA'})
  x=query_buyable(KISClient(S,transport=t),'379800',22600)
  self.assertFalse(x['ok']);self.assertNotIn('PRIVATE DATA',str(x))
 def test_missing_no_margin_fail_closed(self):
  t=Transport({'rt_cd':'0','output':{'max_buy_amt':'999999'}})
  with self.assertRaises(KISError):query_buyable(KISClient(S,transport=t),'379800',22600)
 def test_order_endpoint_remains_blocked(self):
  t=Transport();c=KISClient(S,transport=t)
  with self.assertRaises(KISError):c._request('/uapi/domestic-stock/v1/trading/order-cash',method='GET',headers={})
  self.assertFalse(t.calls)
if __name__=='__main__':unittest.main()
