from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import unittest

import ptt_offline.archive_job_evidence as archive_module
import ptt_offline.archive_pr147_projection as projection_module
from ptt_offline.archive_job_evidence import (
    ArchiveEvidenceError,
    archive_object_identity,
    build_archive_job_evidence,
    build_readback_receipt,
    reject_sensitive,
)
from ptt_offline.archive_pr147_projection import (
    project_archive_as_sync_job,
    project_archive_job_for_pr147,
)


FIXTURE=(
    Path(__file__).parent/"fixtures"/"archive_delivery"/
    "archive_delivery_cases.sanitized.json"
)


class ArchiveJobEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]

    def build_case(self,name):
        case=self.fixture[name]
        job=case["job"]
        read=case.get("readback")
        receipt=None
        if read is not None:
            receipt=build_readback_receipt(
                target=job["target"],job_id=job["job_id"],
                manifest_digest=job["manifest"]["digest"],
                source_revision=job["source_revision"],scope=job["scope"],
                **read,
            )
        return build_archive_job_evidence(
            readback_receipt=receipt,
            **job,
        )

    def test_case1_complete_manifest_succeeded_full_readback_verified(self):
        body=self.build_case("static_success_full")
        self.assertEqual(body["coverage_summary"]["status"],"COMPLETE")
        self.assertEqual(body["job_status"],"succeeded")
        self.assertTrue(body["job_verified"])
        self.assertEqual(body["target"]["kind"],"workers-static-assets")
        self.assertEqual(body["uploaded_count"],2)
        self.assertEqual(body["independently_verified_count"],2)
        self.assertEqual(body["expected_aid_completeness"]["status"],"UNKNOWN")

    def test_case2_complete_manifest_job_not_run_stays_unknown(self):
        body=self.build_case("manifest_complete_job_not_run")
        self.assertEqual(body["coverage_summary"]["status"],"COMPLETE")
        self.assertEqual(body["job_status"],"unknown")
        self.assertFalse(body["job_verified"])
        self.assertIsNone(body["attempted_at"])
        self.assertIsNone(body["uploaded_count"])
        self.assertIn("archive-job-id-unavailable",body["contract_gaps"])
        self.assertIn("archive-readback-receipt-unavailable",body["contract_gaps"])

    def test_case3_job_succeeded_does_not_promote_partial_manifest(self):
        body=self.build_case("job_success_manifest_partial")
        self.assertEqual(body["job_status"],"succeeded")
        self.assertTrue(body["job_verified"])
        self.assertEqual(body["coverage_summary"]["status"],"PARTIAL")

    def test_case4_verified_archive_does_not_invent_expected_aid_authority(self):
        body=self.build_case("static_success_full")
        self.assertTrue(body["job_verified"])
        self.assertEqual(body["expected_aid_completeness"]["status"],"UNKNOWN")
        self.assertIn(
            "expected-aid-authority-unavailable",
            body["expected_aid_completeness"]["contract_gaps"],
        )

    def test_case5_bounded_sample_never_verifies_whole_job(self):
        body=self.build_case("bounded_sample")
        receipt=body["readback_receipt"]
        self.assertEqual(receipt["verification_mode"],"bounded_sample")
        self.assertEqual(receipt["objects_checked"],3)
        self.assertEqual(receipt["objects_verified"],3)
        self.assertFalse(receipt["job_verified"])
        self.assertFalse(body["job_verified"])
        self.assertIn(
            "bounded-sample-cannot-verify-whole-job",
            receipt["contract_gaps"],
        )

    def test_case6_manifest_digest_mismatch_fails_closed(self):
        job=self.fixture["static_success_full"]["job"]
        read=self.fixture["static_success_full"]["readback"]
        receipt=build_readback_receipt(
            target=job["target"],job_id=job["job_id"],
            manifest_digest="f"*64,
            source_revision=job["source_revision"],scope=job["scope"],
            **{**read,"snapshot_id":"9"*64},
        )
        with self.assertRaisesRegex(ArchiveEvidenceError,"manifest digest mismatch"):
            build_archive_job_evidence(readback_receipt=receipt,**job)

    def test_manifest_digest_verification_false_fails_closed(self):
        job=self.fixture["static_success_full"]["job"]
        read=self.fixture["static_success_full"]["readback"]
        receipt=build_readback_receipt(
            target=job["target"],job_id=job["job_id"],
            manifest_digest=job["manifest"]["digest"],
            source_revision=job["source_revision"],scope=job["scope"],
            **{**read,"manifest_digest_match":False,"snapshot_id":"7"*64},
        )
        self.assertFalse(receipt["job_verified"])
        self.assertEqual(receipt["error_code"],"manifest_digest_mismatch")

    def test_case7_object_hash_mismatch_fails_closed(self):
        job=self.fixture["static_success_full"]["job"]
        read=self.fixture["static_success_full"]["readback"]
        receipt=build_readback_receipt(
            target=job["target"],job_id=job["job_id"],
            manifest_digest=job["manifest"]["digest"],
            source_revision=job["source_revision"],scope=job["scope"],
            **{**read,"content_hash_match":False,"snapshot_id":"8"*64},
        )
        self.assertFalse(receipt["job_verified"])
        self.assertEqual(receipt["error_code"],"object_hash_mismatch")
        body=build_archive_job_evidence(readback_receipt=receipt,**job)
        self.assertFalse(body["job_verified"])

    def test_case8_missing_fields_preserve_null_and_contract_gaps(self):
        body=build_archive_job_evidence(
            job_id=None,target={"kind":"workers-static-assets","identity":None},
            source_revision=None,source_hash=None,manifest=None,scope=None,
            attempted_at=None,succeeded_at=None,attempt_count=None,
            retry_after=None,backoff_seconds=None,error_code=None,
            uploaded_count=None,independently_verified_count=None,
            readback_receipt=None,coverage_days=None,job_status=None,
            expected_aid_completeness=None,
        )
        self.assertIsNone(body["job_id"])
        self.assertIsNone(body["source_revision"])
        self.assertIsNone(body["manifest"])
        self.assertEqual(body["job_status"],"unknown")
        self.assertGreater(len(body["contract_gaps"]),8)

    def test_case9_job_manifest_snapshot_identities_are_distinct(self):
        body=self.build_case("static_success_full")
        values={
            body["job_id"],
            body["manifest"]["digest"],
            body["snapshot_id"],
        }
        self.assertEqual(len(values),3)
        job=self.fixture["static_success_full"]["job"]
        read=self.fixture["static_success_full"]["readback"]
        with self.assertRaisesRegex(ArchiveEvidenceError,"must be distinct"):
            build_readback_receipt(
                target=job["target"],job_id=job["manifest"]["digest"],
                manifest_digest=job["manifest"]["digest"],
                source_revision=job["source_revision"],scope=job["scope"],
                **{**read,"snapshot_id":"7"*64},
            )

    def test_case10_sensitive_fields_and_values_are_rejected(self):
        bad_values=[
            {"hmac_secret":"x"},
            {"api_token":"x"},
            {"wrangler_credential":"x"},
            {"authorization":"Bearer x"},
            {"url":"https://example.invalid/file?X-Amz-Signature=abc"},
            {"source_path":"/Users/example/private/archive.json"},
        ]
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(ArchiveEvidenceError):
                    reject_sensitive(value)

    def test_case11_contract_projection_modules_have_no_runtime_io_surface(self):
        for module in (archive_module,projection_module):
            tree=ast.parse(inspect.getsource(module))
            imports=set()
            calls=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node,ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
                elif isinstance(node,ast.Call):
                    if isinstance(node.func,ast.Name):
                        calls.append(node.func.id)
                    elif isinstance(node.func,ast.Attribute):
                        calls.append(node.func.attr)
            self.assertTrue(
                imports.isdisjoint({"subprocess","urllib","requests","http","socket","sqlite3"})
            )
            self.assertNotIn("open",calls)
            self.assertNotIn("run",calls)
            self.assertNotIn("Popen",calls)

    def test_object_identity_is_manifest_key_sha_not_timestamp(self):
        identity=archive_object_identity(
            manifest_digest="a"*64,
            object_key="ptt/v1/chunks/2026/10/01/0000.json",
            canonical_sha256="b"*64,
        )
        self.assertEqual(
            identity,
            "a"*64+":ptt/v1/chunks/2026/10/01/0000.json:"+"b"*64,
        )
        self.assertNotIn("2026-10-20T",identity)

    def test_projection_keeps_three_statuses_separate(self):
        body=self.build_case("job_success_manifest_partial")
        projected=project_archive_job_for_pr147(body)
        self.assertEqual(projected["component"],"Archive")
        self.assertEqual(projected["job_status"],"succeeded")
        self.assertEqual(projected["coverage_summary"]["status"],"PARTIAL")
        self.assertEqual(projected["expected_aid_completeness"]["status"],"UNKNOWN")

        sync=project_archive_as_sync_job(body)
        self.assertEqual(sync["status"],"completed")
        self.assertEqual(
            sync["evidence_source_fields"]["coverage_summary"]["status"],"PARTIAL"
        )
        self.assertEqual(
            sync["evidence_source_fields"]["expected_aid_completeness"]["status"],
            "UNKNOWN",
        )


if __name__=="__main__":
    unittest.main()
