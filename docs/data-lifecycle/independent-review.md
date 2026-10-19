# Independent Review — PR #147

Reviewed initial HEAD: `652c1d7d004580b00983197825ec02c59dd82458`.
Review method: direct source inspection, branch-contract comparison against
Public PRs #53, #55, #135 and #140, and new adversarial tests. The original
author's reported test results were not treated as evidence for this review.

## Findings

### P0

None. Initial PR #147 has no production writer or network adapter, so the
identified defects could not directly mutate production.

### P1 — merge blockers found and corrected

1. **Unproven empty expected sets could become COMPLETE.** `available=true`
   plus `expected_ids=[]` or `expected_aids=[]` was accepted as authority.
   Existing #47 explicitly says successful scans cannot self-certify
   completeness. Fixed by requiring a verified, exact-day, versioned authority
   envelope; otherwise inventory remains `UNKNOWN`.
2. **Checkpoint could advance without an ACK.** `acknowledge()` previously
   accepted only an identity and did not require prior reservation or a digest.
   Fixed with one in-flight content-bound reservation, idempotent re-reserve,
   and exact identity/digest ACK validation. Failure must also match in-flight.
3. **Planner silently collapsed duplicate target identities and compared time
   strings lexically.** Fixed by reporting `duplicate-target-identity`, parsing
   timezone-aware timestamps, and rejecting invalid revisions.
4. **PTT reconciliation identity was under-validated.** A missing day produced
   an identity containing `None`, while `push_id` and `source_record_key`
   mismatches were ignored. Fixed with canonical date validation and explicit
   conflict results for both established #48 identities.

### P2

1. Initial reports did not expose adapter contract gaps. Added machine-readable
   and Markdown `contract_gaps` output.
2. `missing_dates` repeated the same date once per incomplete source. It is now
   deduplicated.
3. The initial CLI accepted only the new normalized shape. Added a strictly
   read-only adapter for sanitized #47/#48 exports; no branch writer was copied.

## Review disposition

The initial HEAD required changes. The corrected HEAD is eligible for approval
only after its exact test evidence is recorded. This review does not validate
production data, deployment, active schedulers, D1/R2 state, or live services.
