# 8501 Production Read-only Integration Shell — Phase 1

Status: **shell / tests / docs only**. No Production reader is enabled or implemented.

## Architecture

```text
Browser
  ↓
Internal Auth Boundary
  ↓
8501 Admin Controller
  ↓
Read Admission Controller
  ↓
Evidence Reader Set
  ├─ D1 Reader [disabled]
  ├─ Archive Reader [disabled]
  ├─ API Semantic Reader [disabled]
  ├─ Publisher Reader [disabled]
  └─ Collector Reader [disabled]
  ↓
Sanitized Contracts
  ↓
Existing Admin UI
```

**ALL Production readers are disabled by default.**

## Authentication

`AdminAuthenticator.authenticate(request_context) -> AuthResult` is the host-owned server-side boundary.

`AuthResult` exposes only:
- authenticated;
- principal;
- auth_method;
- observed_at;
- bounded error_code.

Credential material is not part of the result and is not returned to the browser. Auth happens before the dashboard handler. Missing auth evidence or authenticator exceptions deny access before any reader call.

The fixture authenticator exists only for offline acceptance and is not Production auth proof.

## Exposure / isolation

The shell provides `InternalExposureConfig` / `evaluate_internal_exposure()`.

Accepted Phase 1 shapes:
- loopback listener; or
- an explicitly proven internal network listener behind an authenticated internal proxy.

Rejected:
- `0.0.0.0` / `::` wildcard as proof of isolation;
- public route exposure;
- unproven hostname/private network exposure.

A future running 8501 mount must place authentication before Admin dispatch and must not reuse a Public Worker route.

Current running 8501 exposure/authentication was **not changed or proven by this phase**.

## Capability readers

`ProductionEvidenceReader` is deliberately narrow:

- `read_d1_snapshot(D1ReadScope)`
- `read_archive_delivery_evidence(ArchiveReadScope)`
- `read_api_semantic_health()`
- `read_publisher_evidence()`
- `read_collector_evidence()`

There is no method accepting raw SQL, arbitrary URL, arbitrary filesystem path, storage path, or Worker endpoint.

D1 bounds are encoded in `D1ReadScope`:
- <=3 query groups;
- page size <=100;
- <=5 pages;
- <=500 returned rows;
- bounded day/AID scope;
- explicit verification mode.

Actual query templates/table/view allowlists belong to the future D1 capability implementation, not the Admin consumer.

## Provider selection

`select_reader_provider()` is explicit and defaults to `fixture`.

Production mode never auto-detects. It requires an explicitly supplied Production reader set. Missing capabilities fail closed.

`ProductionReaderConfig` contains one independent gate for:
- D1;
- Archive;
- API semantic;
- Publisher;
- Collector.

Every gate defaults `enabled=false`.

## Credential design

`ServerCredentialProvider` exposes only `available(source) -> bool`.

The Admin consumer never receives credential bytes. Future credentials must remain server-side in environment/secret-store ownership and must never be committed, logged, stored in fixture data, or returned to browser payloads.

`NoProductionCredentials` is the Phase 1 default. Credential-required sources remain unavailable without calling the source reader.

## Admission / quota

`SQLiteReadAdmissionController` stores only local operational metadata in a host-owned SQLite file.

It is multi-process safe through SQLite transactions and WAL locking and does not expose a Production writer capability.

Default D1 admission:
- 6 refreshes / 10 minutes globally per admission DB;
- same-key in-flight lease coalescing;
- atomic window update;
- corrupt state => deny;
- over budget => deny;
- source not configured => deny.

The UI 30-second refresh cooldown is still UX only and is not quota enforcement.

The admission request contains:
- source;
- bounded scope;
- verification mode;
- request class;
- cost class;
- coalesce key.

The receipt contains only sanitized operational evidence:
- request_id;
- source;
- scope_hash;
- mode;
- admitted/reason;
- window start;
- used/limit;
- cache_hit;
- coalesced;
- observed_at.

No SQL, credential, raw URL, payload, user content, or secret is stored.

## Audit

The same host-owned SQLite state stores a sanitized `admin_read_audit` table:
- timestamp;
- principal;
- source;
- operation class;
- scope hash;
- admitted/denied;
- cache hit;
- duration bucket;
- result class;
- bounded error code.

No PTT content, author, token, raw query, secret, raw URL, response body, filesystem path, or exception text is recorded.

A read whose audit receipt cannot be recorded fails closed to unavailable.

## Failure / retry

Each source call is independent. A D1 failure does not prevent Archive; an Archive failure does not prevent health; an API failure does not prevent Coverage.

Phase 1 performs exactly one bounded reader attempt. It adds no automatic retry loop, poller, scheduler, background task, restart, uploader, repair, or writer.

`ReaderTimeouts` defines future connect/read/admission limits. Actual Production client timeout implementation is deferred until each source is individually authorized.

## Last-good

The dashboard controller keeps:
- current read time;
- last successful read time;
- last-good age;
- current bounded error;
- retained last-good payload.

A failed read is never labeled current.

## Browser boundary

All section payloads still pass through `sanitize_for_browser()`, which strips browser-forbidden secret/content/credential keys and local absolute filesystem paths.

Production capability implementation must return only already-sanitized contracts; the browser sanitizer is defense in depth, not a replacement for source validation.

## Writer isolation

The Production shell contains no:
- D1 writer;
- Publisher writer;
- R2 uploader;
- Static Assets deployer;
- migration runner;
- restart/activate script;
- mutation method.

POST/PUT/DELETE remain 405.

## Current operational disposition

```text
running 8501 modified: NO
Production query: NO
Production credential: NO
Production D1: NO
Production R2: NO
Static Assets deploy: NO
Publisher/Collector restart: NO
writer action: NO
```

Phase 2 must be authorized source-by-source by #45:
1. D1 bounded readback;
2. Archive / Static Assets evidence;
3. Production API semantic evidence;
4. Publisher / Collector sanitized evidence.
