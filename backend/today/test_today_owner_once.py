import unittest,json
from .today_owner_once import prepare,dispatch,API
C="UC"+"A"*22
R={"version":"approved-v1","channels":[{"id":C,"group":"hololive","uploads_playlist":"UU"+C[2:]}]}
DATA={"mode":"PROVIDER_READ_ONLY","d1_writes":0,"roster_version":"approved-v1","gap":False,
 "records":[{"channel_id":C,"group":"hololive","video_id":"abcdefghijk"}]}
class OwnerSendTests(unittest.TestCase):
 def test_dry_run_not_network(self):
  raw=prepare(DATA,R)
  result=dispatch(raw,"",transport=lambda _:self.fail("should not send"))
  self.assertEqual(result["mode"],"DRY_RUN_NO_SEND")
  with self.assertRaises(ValueError):dispatch(raw,"x"*40,send=True,approved_sha="wrong")
 def test_signed_single_delivery_receipt(self):
  raw=prepare(DATA,R)
  received=[]
  def transport(req):
   received.append(req)
   return 200,json.dumps({"status":"verified","records_verified":1}).encode()
  import hashlib
  result=dispatch(raw,"s"*40,send=True,approved_sha=hashlib.sha256(raw).hexdigest(),
                  now_ms=1792080000000,transport=transport)
  self.assertEqual(len(received),1)
  self.assertEqual(received[0].full_url,API)
  self.assertEqual(result["mode"],"ONE_SHOT_REMOTE_ACK")
 def test_gap_refused(self):
  with self.assertRaises(ValueError):prepare({**DATA,"gap":True},R)
if __name__=="__main__":unittest.main()
