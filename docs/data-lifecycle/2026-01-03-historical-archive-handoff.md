# 2026/01–03 Historical PTT Archive handoff

Status: owner-local production deployment completed and manifest readback passed.

## Source authority

- Public base: `physicsdog0505/HoloViewer@871923157254f4f8d7d951a7ea45532998ece8f2`
- Recovery ledger: `physicsdog0505/Hololive-PTT-Viewer@1b634e4f9bafb589a9434e3f760a3e92e04f009b`
- Historical tooling reference: `4874a194701357e320abced5dae7b57c47f31db0`
- No PTT recovery, Collector, Publisher, D1, or frontend operation was performed.
  The only production mutation was the explicitly authorized Owner-local Static
  Assets deployment recorded below.

## Accepted sets and authoritative months

| Month | Accepted set SHA-256 | Articles | Raw | Web | Pushes | Month SQLite SHA-256 | Audit SHA-256 |
|---|---|---:|---:|---:|---:|---|---|
| 2026-01 | `8f96cfc2407541525fb7945f2f5ee55211bc7154d798e417846ff25ab11950de` | 62 | 35 | 27 | 125,187 | `f7e9df7d75c8407dbdb2cf5cebe5578af9c5748f5ddf9068779ad2e54b5f25f1` | `38b7216ff501ab5a9c6903dec584648cd479c8a63d1f5e3abd4a1bfbc83089c5` |
| 2026-02 | `9b6f1fa317259d9657cc1f0e47738139c1ff8deac32b1488856fdb41511ef2de` | 56 | 22 | 34 | 67,555 | `16275f111728553b62b3e3c1fd1d873d4b9c97b72384f75babd38dc780cfe7c5` | `bc84a53d570887500b3382451ccae7c3bbec8b8387079b9f6377af33cdb44fe1` |
| 2026-03 | `8628cb249054cbac19790a68ef43f11a90e2e849ccb133692b1718c5c8301e27` | 62 | 35 | 27 | 137,454 | `e9d93a907b398b219cf5df6145b22ce60c572ef6ccde04f49741f7f016b04c21` | `2830481dc1b994b1ca6a0865260a47274d41a2fbac841aa49ad45c54cb5d024c` |

Combined: 180 articles, 92 Raw, 88 Web, 330,196 pushes.

## Daily Static Assets packages

| Month | Manifest SHA-256 | Objects | Pushes | Registration identity |
|---|---|---:|---:|---|
| 2026-01 | `032568e88c0184f34f7493527abdfd577896a5d999e00afc0d91581e3fc6aeed` | 32 | 125,187 | `9d367d9e0994a4fe596e17d1e6ad992cec4332649abb7f4b4c722d4b437b6ff6` |
| 2026-02 | `3290945ef8119f961b6de139aeb3651b5bb64e35ee15a0520d0b27291cfb1fe4` | 29 | 67,555 | `c217d9396eb8bfe2dce9fa7be7945111b7c1f970d725af3951719d034e738571` |
| 2026-03 | `ab72556d320d20e351efded092ca61b391cf5099cd4a183daf4a7553c18c2141` | 32 | 137,454 | `a576aac5cb6189260a21aeb8d7659ca9a6ef29f07713e97e20976f96470e978a` |

Every candidate object uses `ptt/v1/months/YYYY-MM/days/YYYY-MM-DD/day.json`, declares `partition_start`, `partition_end`, and `push_count`, and contains no hourly `chunks/` path. Boundary overflow days are retained by the existing contract and marked `PARTIAL`; every registered in-month day remains `COMPLETE`.

## Joint release receipt and production baselines

- Staged release: `/private/tmp/issue160-20260103-production-release-v2`
- Receipt SHA-256: `5c2e844db8f248da8015ea9a0ae5bacb6245dc5335e21914a54d38eb95048066`
- Deployable files: 1,254
- Deployable bytes: 897,714,730
- Largest asset: 13,459,330 bytes
- Production version observed before staging: `3d24ecca-074e-4427-b3cb-5d3c85c017a7`

The current HTTP manifests were byte-compared with the local deployed baseline, then all referenced objects were hash-verified by `month_static_release`. Existing registration and provenance sidecars are also copied exactly.

| Baseline | Manifest SHA-256 | Objects | Pushes |
|---|---|---:|---:|
| 2026-04 | `f931ac184017a1ab6c9c6c8a9636f7198fdad6811c89fef652688485e716b8f5` | 31 | 77,777 |
| 2026-05 | `8105f48f13a53335fe4b47a00657501828fda68dbdfd75ebf37704ab042eaf6f` | 32 | 95,740 |
| 2026-06 | `b7eddc70382d4c26707306912ee743eebc12471daa63d1d6b650679df30ac5b7` | 31 | 125,080 |
| 2026-07 | `9f7a49c182e5d10b68d6c1b1ac66b398cdded9d55644be5ae45001e2cc117973` | 33 | 135,671 |
| 2026-08 | `73f7cf73ad8798e8e1590e87f727d020efbd1b23a40092a624896fd3ea7a9ccd` | 639 | 124,181 |
| 2026-10 | `4bc9dc9d91b36ab38046267663b40a1e1ecb1eb9447bcd15aa8ecf413ba93470` | 371 | 54,886 |

Unreferenced stale 06/07 hourly files are not restored into the staged bundle.

## Owner-local commands

Executed Owner-local deploy command after explicit owner authorization:

```bash
OWNER_LOCAL=YES GITHUB_ACTIONS=NO CI_DEPLOY=NO npx --yes wrangler deploy --config /private/tmp/issue160-20260103-production-release-v2/wrangler.jsonc --name holoviewer-ptt-static-assets-full-offline
```

Post-deploy full HTTP readback:

```bash
python3 -B -m ptt_offline.month_static_release verify-http --spec ptt_offline/fixtures/history/2026-01-03-production-release.json --observed-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --receipt /private/tmp/issue160-20260103-production-readback.json
```

The readback checks all baseline objects, all candidate registration/manifest/provenance/object identities, representative early/mid/late days, response headers, CORS, and 404 behavior.

## Production deployment receipt

- Deployed at: `2026-10-30T02:49:01Z`
- Worker version: `ab656742-4cc9-4fee-8cd9-aa72866387b2`
- Wrangler result: 102 new or changed assets uploaded; 1,151 existing assets reused.
- HTTP readback reproduced the expected manifest SHA-256 for 2026-01 through
  2026-08 and 2026-10.
- The separate 2026-09 Pilot Worker remained reachable; its manifest SHA-256
  after this deployment was
  `a4f171c4e3cf04916f146625119c187f5e9e6f40afdc11fc9722f4311e461f32`.

## Execution boundary

- `PRODUCTION_CHANGED=YES`
- `DEPLOY=YES`
- No GitHub Actions were dispatched.
- Pipeline build and release fail-closed gates passed. A separate standalone unit-test run was not requested or executed.
