// Deterministic, read-only snapshot + live contract regression.
// No DOM, cloud requests, tokens, operational data, or production changes.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

globalThis.window = {};
globalThis.location = { origin: "https://physicsdog0505.github.io" };
globalThis.document = { readyState: "loading", addEventListener() {}, querySelector() { return null; } };
const source = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
vm.runInThisContext(source.replace("window.HoloViewerCloud = {", "window.HoloViewerCloud = { loadPttArtifact, "));
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

  // Document an existing contract gap, rather than silently accepting conflicting payload.
  const conflicting = {...base, content: "different fixture payload", cursor: 9};
  const conflictPage = client.validateRelayPage({
    ...relay, next_cursor: 9, pushes: [conflicting]
  }, 8);
  assert.equal(conflictPage.pushes[0].pushId, id);
  assert.notEqual(conflictPage.pushes[0].content, snapshot.articles[0].pushes[0].content);
  assert.equal(
    typeof client.assessPayloadConflict, "undefined",
    "payload conflict detection is NOT implemented by the current client; #317 contract gate"
  );
} finally {
  globalThis.fetch = originalFetch;
}

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

console.log("public snapshot/live boundary offline: PASS (payload conflict handling remains gated)");
