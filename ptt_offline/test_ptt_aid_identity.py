import unittest
from ptt_offline.ptt_aid_identity import aid_from_article_url,verify_aid_url,identity_receipt
from ptt_offline.public_today_contract import ContractError

class PttAidIdentityTests(unittest.TestCase):
    URL="https://www.ptt.cc/bbs/ask/M.1673149653.A.9E3.html"
    AID="1ZkZpLdZ"

    def test_independently_published_real_article_identity(self):
        self.assertEqual(aid_from_article_url(self.URL),("ask",self.AID))
        self.assertTrue(verify_aid_url("ask","#"+self.AID,self.URL))
        receipt=identity_receipt("ask",self.AID,self.URL)
        self.assertEqual(len(receipt["digest"]),64)

    def test_mismatch_spoof_malformed_fail_closed(self):
        for board,aid,url in (
            ("C_Chat",self.AID,self.URL),
            ("ask","1ZkZpLdY",self.URL),
            ("ask",self.AID,self.URL.replace("9E3","9E2")),
            ("ask",self.AID,self.URL.replace("www.ptt.cc","evil.example")),
            ("ask",self.AID,self.URL.replace("https://","http://")),
            ("ask",self.AID,""),
        ):
            with self.subTest(url=url,aid=aid):
                self.assertFalse(verify_aid_url(board,aid,url))
                with self.assertRaises(ContractError):
                    identity_receipt(board,aid,url)

if __name__=="__main__":
    unittest.main()
