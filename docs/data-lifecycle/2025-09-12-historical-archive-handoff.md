# 2025/09–12 Historical PTT Archive production handoff

Status: Owner-local production deployment completed.

- Durable recovery authority: `b1748e76cc963c988c90ac3158e8728c5e4f9bf7`
- Active Worker version: `8a330d85-2459-437b-be66-d5f9b0b21342`
- Joint release receipt SHA-256: `e817a8d1b8b7a4c80140fe777edcc33195f1e8ce05bf6548c0fb99698a0e0ecb`
- Production target: `holoviewer-ptt-static-assets-full-offline`
- No recovery, Collector, Publisher, D1, frontend, CI, or GitHub Actions operation was performed.

| Month | Accepted set SHA-256 | SQLite SHA-256 | Audit SHA-256 | Manifest SHA-256 | Objects | Pushes |
|---|---|---|---|---|---:|---:|
| 2025-09 | `c7926c83ef682310d11f9380f7f69de1c379a9bf60478bfae320c1c74c34d8d4` | `bfc50c6b8df339b9c79495322ed9b969f0a8300284d9423ff6eed04d7d48e9a9` | `99da6f70edbebe16c00578496715944d28ea3ed6f15f249786453cc0bd2024d6` | `c8bbc7c504975af0650eeec4d3903e3b251582aaaa497045aab04ccb161459fa` | 31 | 177,434 |
| 2025-10 | `3525912ecb3fd4d121a90399eebe9213c8a9f90797a8adcb456bfa4de91f6c1d` | `563eff94cb54593108a44f80dde5ef5f48055daf1cd022a38539333f8bee7cbf` | `af378fca6d154c99c4f47a88ae78483c73b657b275c2a59f4ea736cca034893f` | `d46de04433059a5dbdbf40c937b34b3fb6e1e1e520235741c581d729bdb08cfa` | 32 | 167,238 |
| 2025-11 | `e96f1ae786a903a1a7f252101d9e4daee007c6f7c79ede098e7eafe4e792019a` | `f05e0b5979bb4935d70f1a6bdcfeb81b7ecb28e56389bdb6aa21123ca53ac752` | `e20f4a206e81dcdbd021c785ff6a9e3e739a54fa9b034154b058ed56d9b01193` | `fe832f9f83c16242321365e350439e9c1e694d3fe997fd6edf4630fba19b4d12` | 31 | 108,112 |
| 2025-12 | `1704e14df52b33851a257d9807cb6c91037194dc43b3628da6f2f177469e7262` | `a4bfb8b4f3c6fe286a062676332d5e175bab66d61b76269097c963ba7d09a763` | `b4e763704991fd44db9ef87eba1ef01cbfa7e776cdd1d524c00f3b425a431cae` | `47aee3d947015cd90270cf864a24d3aea6af80746436de531b35025c657b6002` | 33 | 173,839 |

All four manifests were read back over HTTPS with exact SHA matches. Every
in-month calendar day is finalized `COMPLETE`, every object is a daily
`day.json`, and every object declares `partition_start`, `partition_end`, and
`push_count`.

The initial deployment exposed six legitimate late pushes from December
threads dated 2026-02-24. The existing generator only recognized December to
January rollover and initially assigned those pushes to 2025-02-24. A bounded
forward-only correction generalized the winter rollover, rebuilt December,
and deployed the corrected manifest. Recovery data and accepted counts did not
change.

Existing 2026/01–08 and 2026/10 production manifests were included as exact
baselines. The separate 2026/09 Worker and unfinished 2025/08 recovery were not
touched.

```ini
SEPTEMBER_DEPLOY=PASS
OCTOBER_DEPLOY=PASS
NOVEMBER_DEPLOY=PASS
DECEMBER_DEPLOY=PASS
MONTH_MANIFESTS=4/4
DAILY_COVERAGE=PASS
SOURCE_SHA_VERIFIED=YES
STATIC_ASSETS_RELEASE=PASS
COLLECTOR_CHANGED=NO
PUBLISHER_CHANGED=NO
D1_CHANGED=NO
FRONTEND_CHANGED=NO
GITHUB_ACTIONS_USED=NO
```
