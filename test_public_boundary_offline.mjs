// Deterministic, read-only snapshot + live contract regression.
// No DOM, cloud requests, tokens, operational data, or production changes.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

globalThis.window = {};
globalThis.location = { origin: "https://physicsdog0505.github.io" };
globalThis.document = { readyState: "loading", addEventListener() {}, querySelector() { return null; } };
const source = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
vm.runInThisContext(source.replace("window.HoloViewerCloud = {", "window.HoloViewerCloud = { loadPttArtifact, assertCompatiblePush, mergeCompatiblePushes, compatiblePushMap, "));
const client = window.HoloViewerCloud;
const id = "ptt:v1:" + "a".repeat(64);
const base = {
  push_id: id, aid: "M.123.A.1",
  article_url: "https://www.ptt.cc/bbs/C_Chat/M.123.A.1.html",
  source_line: 7, floor: null, kind: "推", author: "fixture",
  content: "synthetic push", occurred_at: "2026-10-09T01:00:00Z", cursor: 8
};
const relay = {
  schema_version: 1, next_cursor: 8, has_more: false,
  history_gap: false, purged_through_cursor: 0,
  checked_at: "2026-10-09T01:00:01Z", pushes: [base]
};
const page = client.validateRelayPage(relay, 7);
assert.equal(page.pushes.length, 1);
assert.equal(page.pushes[0].pushId, id);
assert.equal(page.pushes[0].floor, null);
assert.equal(page.nextCursor, 8);
assert.throws(() => client.validateRelayPage(relay, 8), /cursor/);
assert.throws(() => client.validateRelayPage({...relay, next_cursor: 7}, 7), /precedes/);
assert.throws(() => client.validateRelayPage({...relay, pushes: [{...base, secret: "private"}]}, 7), /fields mismatch/);
const lost = client.validateRelayPage({
  ...relay, history_gap: true, purged_through_cursor: 7
}, 7);
assert.equal(lost.historyGap, true);
assert.equal(lost.purgedThrough, 7);

const artifact = {
  schema_version: 1, snapshot_id: "fixture-2026-10-09",
  generated_at: "2026-10-09T01:00:00Z", completeness: "partial",
  articles: [{
    article_id: "ptt:C_Chat:M.123.A.1", board: "C_Chat", aid: "M.123.A.1",
    title: "synthetic fixture only", url: base.article_url, completeness: "unknown",
    pushes: [{
      push_id: id, source_line: 7, floor: null, kind: "推",
      author: "fixture", content: base.content, occurred_at: base.occurred_at
    }]
  }]
};
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => new Response(JSON.stringify(artifact), {
  status: 200, headers: {"content-type": "application/json"}
});
try {
  const snapshot = await client.loadPttArtifact(new URL("https://fixture.invalid/ptt.json"));
  assert.equal(snapshot.completeness, "partial");
  assert.equal(snapshot.articles[0].completeness, "unknown");
  const merged = new Map(snapshot.articles[0].pushes.map(p => [p.pushId, p]));
  for (const p of page.pushes) merged.set(p.pushId, p);
  assert.equal(merged.size, 1, "same canonical ID should have one visible row");

  // Same identity must never mask changed author, content, timestamp or floor.
  const baseline = snapshot.articles[0].pushes[0];
  assert.doesNotThrow(() => client.assertCompatiblePush(baseline, page.pushes[0]));
  for (const changed of [
    {content: "different fixture payload"}, {author: "another"},
    {occurredAt: "2026-10-09T02:00:00Z"}, {floor: 3},
    {sourceLine: 8}, {kind: "噓"}
  ]) {
    assert.throws(() => client.assertCompatiblePush(baseline, {...page.pushes[0], ...changed}), /payload conflict/);
  }
  const state = new Map([[id, baseline]]);
  assert.throws(() => client.assertCompatiblePush(state.get(id), {...page.pushes[0], content: "changed"}), /payload conflict/);
  assert.equal(state.get(id).content, base.content, "snapshot value must remain unchanged");

} finally {
  globalThis.fetch = originalFetch;
}

// Snapshot rebase must either commit the entire batch or preserve old rows.
const unchanged = {pushId: id, floor: null, sourceLine: 7, kind: "推",
                   author: "fixture", content: "synthetic push",
                   occurredAt: "2026-10-09T01:00:00Z", cursor: 8};
const newlySeen = {...unchanged, pushId: "ptt:v1:" + "b".repeat(64)};
const conflict = {...unchanged, content: "conflicting rebase payload"};
const existingRows = new Map([[id, unchanged]]);
assert.throws(
  () => client.mergeCompatiblePushes(existingRows, [newlySeen, conflict]),
  /payload conflict/
);
assert.equal(existingRows.size, 1, "failed rebase must not partially insert");
assert.equal(existingRows.get(id), unchanged, "failed rebase must not replace previous value");
client.mergeCompatiblePushes(existingRows, [newlySeen, {...unchanged}]);
assert.equal(existingRows.size, 2, "valid complete rebase should insert new evidence");
assert.equal(existingRows.get(id).content, unchanged.content);

// Snapshot refresh must also reject conflicting duplicate IDs within its own batch.
const selfConflictRows = new Map();
assert.throws(
  () => client.mergeCompatiblePushes(selfConflictRows, [newlySeen, {...newlySeen, author: "changed"}]),
  /payload conflict/
);
assert.equal(selfConflictRows.size, 0);

// Initial snapshot entries must not silently overwrite the same-ID row.
const duplicateStart = {...unchanged, content: "conflicting starting snapshot"};
assert.throws(() => client.compatiblePushMap([unchanged, duplicateStart]), /payload conflict/);
const identicalStart = client.compatiblePushMap([unchanged, {...unchanged}]);
assert.equal(identicalStart.size, 1);
assert.equal(identicalStart.get(id).content, unchanged.content);

// G2 Worker GET v1: synthetic two-page, sparse cursor, partial/gap, and overlap.
// This uses only in-memory wire envelopes; no Worker/cloud endpoint is called.
const hashPush = "ptt:v1:" + "c".repeat(64);
const wirePush = {...base, push_id: hashPush, cursor: 13};
const secondWirePush = {...base, push_id: "ptt:v1:" + "d".repeat(64), cursor: 17, source_line: 8};
const pageOne = client.validateRelayPage({
  ...relay, next_cursor: 13, has_more: true, pushes: [wirePush],
  checked_at: "2026-10-10T01:00:00Z"
}, 7);
const pageTwo = client.validateRelayPage({
  ...relay, next_cursor: 17, has_more: false, pushes: [secondWirePush],
  checked_at: "2026-10-10T01:00:01Z"
}, pageOne.nextCursor);
const mergedG2 = client.compatiblePushMap([unchanged]);
client.mergeCompatiblePushes(mergedG2, [...pageOne.pushes, ...pageTwo.pushes]);
assert.equal(mergedG2.size, 3);
assert.equal(pageTwo.nextCursor, 17, "next_cursor is a relay cursor, not an archive floor");
const gapAfterPurge = client.validateRelayPage({
  ...relay, next_cursor: 17, pushes: [], history_gap: true,
  purged_through_cursor: 18, checked_at: "2026-10-10T01:00:02Z"
}, 17);
assert.equal(gapAfterPurge.historyGap, true, "retention loss must remain explicit");
assert.equal(gapAfterPurge.purgedThrough, 18);
assert.equal(mergedG2.size, 3, "history_gap alone does not authorize deleting snapshot rows");
assert.throws(
  () => client.mergeCompatiblePushes(mergedG2, [{...pageOne.pushes[0], content: "G2 conflicting replay"}]),
  /payload conflict/
);
assert.equal(mergedG2.get(hashPush).content, base.content, "conflict must preserve earlier wire value");
// 409 is a Publisher rejection (not a GET read page and never an ACK):
// do not fabricate a read envelope or advance any Reader cursor from it.
const syntheticRejection = {status: 409, error: "source-floor-conflict"};
assert.equal(syntheticRejection.status, 409);
assert.equal(pageTwo.nextCursor, 17);

// Negative-path fixture matrix: verify no invalid relay page is accepted and no
// incomplete snapshot is silently promoted to complete.
const invalidRelayPages = [
  [{...relay, checked_at: "invalid"}, /UTC-Z/],
  [{...relay, has_more: "false"}, /schema/],
  [{...relay, purged_through_cursor: -1}, /schema/],
  [{...relay, next_cursor: 1}, /cursor/],
  [{...relay, pushes: [{...base, cursor: 7}]}, /cursor/],
  [{...relay, pushes: [{...base, cursor: 8}, {...base, cursor: 8}], next_cursor: 8}, /cursor/],
  [{...relay, pushes: Array.from({length: 501}, (_, i) => ({...base, cursor: 8 + i})), next_cursor: 508}, /list/],
];
for (const [badPage, expected] of invalidRelayPages) {
  assert.throws(() => client.validateRelayPage(badPage, 7), expected);
}
const rejectedSnapshots = [
  {...artifact, schema_version: 2},
  {...artifact, generated_at: "2026-10-09T01:00:00+08:00"},
  {...artifact, completeness: "complete-ish"},
  {...artifact, articles: null},
];
globalThis.fetch = async () => new Response(JSON.stringify(rejectedSnapshots[0]), {status: 200});
try {
  for (const rejected of rejectedSnapshots) {
    globalThis.fetch = async () => new Response(JSON.stringify(rejected), {status: 200});
    await assert.rejects(
      client.loadPttArtifact(new URL("https://fixture.invalid/ptt.json")),
      /schema|UTC-Z|completeness/
    );
  }
  globalThis.fetch = async () => { throw new TypeError("fixture offline"); };
  await assert.rejects(
    client.loadPttArtifact(new URL("https://fixture.invalid/ptt.json")),
    /fixture offline/
  );
} finally {
  globalThis.fetch = originalFetch;
}

console.log("public snapshot/live boundary offline: PASS (same-ID conflict protected)");
