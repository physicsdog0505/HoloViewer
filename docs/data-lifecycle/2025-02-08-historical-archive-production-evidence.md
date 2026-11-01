# 2025/02–08 Historical PTT archive production evidence

Date: 2026-11-02 (Asia/Taipei)

Durable recovery handoff: `4c9b3d0208bfd31d5ae3ef37b284e8440411d93c`

Public base before release: `48830c0de15710800f2e712fa24c1d309863e977`

Scope: one Owner-local Static Assets release for 2025/02 through 2025/08, followed by frontend archive-month wiring. 2025/01 remains HOLD.

## Accepted sources and authoritative artifacts

| Month | Articles | Raw | Verified Web | Web exceptions | Pushes | Accepted-set SHA-256 | SQLite SHA-256 | Audit SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| 2025-02 | 56 | 35 | 18 | 3 | 152856 | `7680d0256df6407f3bbb589b9b93f4a29a5679e0348018be564c7a3d6c8491a3` | `6644536e75e5d33176deacd0a0a70ee73144bc07a73c1407d851b2666489462c` | `94911188d14904fe6fa830545370bd93e270daf6162d88206b5d4681730d3286` |
| 2025-03 | 63 | 41 | 22 | 0 | 226206 | `0c24c338603d563ca69cd9bcad203c25e4427007da05d8aea25a6b75f1fb89cf` | `1bd65f53f968283013aed361c2f28941d73c91add3f143d42c2a51171b5e495a` | `437b59cf730bd67a817e942bd1754b598323f7417c9ef2aa2a38cac339618760` |
| 2025-04 | 60 | 43 | 17 | 0 | 162998 | `c73143990554c9c36299ac2175ec0188b25f820e8eb6446b1048d6187498987d` | `6b5e81ce4f40552cd08cb28d0ac831b00f41ba270288d1c1844ec22945fdf85c` | `7dec7e2358b720f5389dae6b356e41c3bfc7815767bdd8c6eec095f2d43211a5` |
| 2025-05 | 62 | 44 | 18 | 0 | 154324 | `f71eb2c5b029765930223a4227f7ffe76574485ae92cdeb12eff46d22025505f` | `3ee9bf3303b0f6c47ba8ca0faf232d6f46c68e622370d7c0845120b5f71a66bb` | `20b7a6abf5e713129a0322cc4b80fa7eaf69f1de178db60e1a8a70e5604e3432` |
| 2025-06 | 60 | 41 | 19 | 0 | 148747 | `91d5441ce34f91c0834d5da25a2588353aa67301df5d9f3c9eb6a98fc6311ba4` | `d480282713d83a2895269ca7c730f9010d2e0592fe820ace9c43cc646b221d45` | `39de277be522263c24054984568e4dc3f7b80275a29888549955730d4f8d16ac` |
| 2025-07 | 61 | 33 | 28 | 0 | 113496 | `54eac2bc5cb2ce659c5422f5d1a5911b9bd25c0e5cc08e7a59d8728dfc4b6976` | `985caf9fcc761c30597b9c30c672c2c3eddb99fde3a669aa5169b7ce47873f9a` | `a8b5c6e0dc7c5a52a907f627df7a43712594551d90ed2c51698fa8107d80ad68` |
| 2025-08 | 62 | 39 | 23 | 0 | 139395 | `55acf4deaf4d737fa344f7b9c68fba9e2a233aaf9cfd811b2a81367ba1757291` | `b20b02e66c8c6026d923514231f254b6d7713351bef79f51be3cb89bb43c1bc2` | `821b1242e620f005be647f61f7212cef4969d0b3babb63afff14fb0d96942137` |

The three explicit 2025/02 source-unavailable exceptions are `M.1738452607.A.526`, `M.1738493391.A.5BE`, and `M.1738579127.A.31B`. Each fixture entry binds the exception to the durable handoff commit, owner approval, and reason `ptt_article_not_found`.

## Daily packages and production reconciliation

| Month | Objects | Pushes | Manifest SHA-256 | Registration identity | HTTP |
| --- | ---: | ---: | --- | --- | --- |
| 2025-02 | 31 | 152856 | `83d55ac7421f8227c61d871573c6761a9fe75288849742b297e39d7368a8352e` | `ff7ea3a7ecc79c4846424a6ebfbae70a880b8a8aeb281c817bf8b21e608f6ff3` | 200 |
| 2025-03 | 32 | 226206 | `e59a3771639255c9e5d7eceb034ce43c7bab225e457a18beb11a769a4c1eefe4` | `a840d5b0ed63781bcc49b58a2e63d8eb69888d758a21d40408738013a0fb68b4` | 200 |
| 2025-04 | 31 | 162998 | `c5e6c14d7028b5e805f0ff4172bf03126efb67eee3005ffe8fb3c68c21abcb61` | `991b927a52e320033a28b8d00ea118a8b29bcd0c926d1a180a10946d96b1598d` | 200 |
| 2025-05 | 32 | 154324 | `0fa2de29ae9208c2d1cb2be38b46b27ef6fda1142440ff85797f11b8d842e8c6` | `7074cb38f4db7c569974b7ce9e1bad89523eb6bdaaf6ee1152439990ea8d42ac` | 200 |
| 2025-06 | 32 | 148747 | `375d468d1a315b1a66159d42d3146546834fc1b4ee2c0fa9584957fe84ebf042` | `79062ab29011e10503026c1fff15995bc434bb280a9257e754fed3fd962a51e0` | 200 |
| 2025-07 | 33 | 113496 | `7f05a33b9aa7c329d6df7d468645116d8593ca3b557fc1a765c9dbff04209ae5` | `d8794af2c4788c2a34fd2146359c6427edd25c74364374f546119bc6f9d942e0` | 200 |
| 2025-08 | 34 | 139395 | `595fb04cbf25b6533e4da007092fb6e1c434de3c30ba34abc32df9c0802a69e1` | `b3a03c6149933f1f69fca96df4d02a4c1debdced7ea3595c8748434a337f1f64` | 200 |

All in-month days are `COMPLETE` and finalized. The joint release contains 225 daily objects and 1,098,022 pushes. Live manifests, registrations, and one representative day object per month were read back and matched the staged candidate exactly.

Release receipt SHA-256: `f380df3ce3367adedd63c936a1b96d6320e0c5fabb02a35e8c25d1bf36b3bf93`

Static Assets production version: `92d8d382-d840-4b64-ae10-9f16a40ee451`

The release retained all existing 2025/09–12 and 2026/01–08, 2026/10 baseline manifests with their exact pre-release SHA-256 values. Wrangler uploaded 246 new assets and reused 1,392 existing assets.

## Frontend wiring

`site/assets/config.js` adds only the seven month mappings from 2025/02 through 2025/08. All existing month mappings remain present. No PTT archive payload is bundled into the frontend site.

Frontend production version: `a11c66d9-010c-4812-8b7b-3b535fd61974`

Live `https://holodocchi.com/assets/config.js` returned HTTP 200 and matched the local file exactly:

`db43eee08e4a73b8ba65237c9755c304b4149bddcd9ace1d80f0f06adeb19e5b`

## Boundaries

- `OWNER_LOCAL=YES`
- `GITHUB_ACTIONS_USED=NO`
- `CI_DEPLOY=NO`
- `PTT_RECOVERY_RERUN=NO`
- `COLLECTOR_CHANGED=NO`
- `PUBLISHER_CHANGED=NO`
- `D1_CHANGED=NO`
- `YOUTUBE_CHANGED=NO`
- `WATCHALONG_CHANGED=NO`
- `VOD_SUBTITLE_CHANGED=NO`
- ports 8501 and 4174 were not touched

