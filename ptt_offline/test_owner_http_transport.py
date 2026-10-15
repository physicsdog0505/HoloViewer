import hashlib
import hmac
import io
import json
import unittest
from ptt_offline.owner_http_transport import owner_signed_http_executor
from ptt_offline.public_today_contract import ContractError

class Response:
    status=200
    def __init__(self,body):
        self.body=io.BytesIO(json.dumps(body).encode())
    def read(self,limit):
        return self.body.read(limit)
    def __enter__(self): return self
    def __exit__(self,*args): pass

class OwnerHttpTransportTests(unittest.TestCase):
    def test_no_write_without_explicit_owner_opt_in(self):
        with self.assertRaises(ContractError):
            owner_signed_http_executor(endpoint="https://holoviewer-public-api.singlebagel.workers.dev/private/ptt/publish",
                secret="s"*40)
    def test_one_signed_request_and_exact_response(self):
        calls=[]
        batch={"rows":[{"aid":"A1"}],"batch_id":"b","digest":"d","request_cap":1,"retry_cap":0}
        receipt={"status":"ACK","batch_id":"b","digest":"d","logical_rows_acked":1}
        def opener(request,timeout):
            raw=request.data
            timestamp=request.get_header("X-ptt-timestamp")
            expected=hmac.new(("s"*40).encode(),timestamp.encode()+b"\n"+raw,
                              hashlib.sha256).hexdigest()
            self.assertEqual(request.get_header("X-ptt-signature"),expected)
            self.assertEqual(request.get_header("User-agent"),"Mozilla/5.0")
            calls.append(raw)
            self.assertEqual(timeout,10)
            return Response(receipt)
        fn=owner_signed_http_executor(endpoint="https://holoviewer-public-api.singlebagel.workers.dev/private/ptt/publish",
            secret="s"*40,allow_write=True,opener=opener,clock_ms=lambda:1792069200000)
        self.assertEqual(fn(batch),receipt)
        self.assertEqual(len(calls),1)
    def test_wrong_hostname_never_sends(self):
        with self.assertRaises(ContractError):
            owner_signed_http_executor(endpoint="https://wrong.example/private/ptt/publish",
                secret="s"*40,allow_write=True)

    def test_wrong_path_never_sends(self):
        with self.assertRaises(ContractError):
            owner_signed_http_executor(endpoint="https://holoviewer-public-api.singlebagel.workers.dev/ptt/publish",
                secret="s"*40,allow_write=True)
if __name__=="__main__":
    unittest.main()
