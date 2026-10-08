import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

globalThis.window = {};
globalThis.location = { origin: "https://physicsdog0505.github.io" };
globalThis.document = { readyState: "loading", addEventListener() {}, querySelector() { return null; } };
vm.runInThisContext(fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8"));


assert.equal(window.HoloViewerCloud.parseYouTubeId("https://youtube.com/watch?v=abcdefghijk"), "abcdefghijk");
assert.equal(window.HoloViewerCloud.parseYouTubeId("https://youtu.be/abcdefghijk"), "abcdefghijk");
assert.equal(window.HoloViewerCloud.parseYouTubeId("https://example.com/watch?v=abcdefghijk"), null);
assert.equal(window.HoloViewerCloud.parseYouTubeId("https://youtube.com.evil.example/watch?v=abcdefghijk"), null);
assert.equal(window.HoloViewerCloud.parseYouTubeId("javascript:alert(1)"), null);
const push = {push_id:"ptt:C_Chat:aid:1",aid:"M.123.A.1",article_url:"https://www.ptt.cc/bbs/C_Chat/M.123.A.1.html",source_line:1,floor:1,kind:"推",author:"fixture",content:"hello",occurred_at:"2026-10-08T10:00:00Z",cursor:1};
const page = {schema_version:1,next_cursor:1,has_more:false,checked_at:"2026-10-08T10:00:01Z",pushes:[push]};
assert.equal(window.HoloViewerCloud.validateRelayPage(page, 0).pushes[0].cursor, 1);
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, items:page.pushes}, 0));
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, pushes:[{...push, secret:"no"}]}, 0));
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, next_cursor:0}, 0));
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, pushes:[{...push,cursor:2},{...push,push_id:"ptt:C_Chat:aid:2",cursor:1}],next_cursor:2}, 0));

const transcript = JSON.parse(fs.readFileSync(new URL("./public-data/demo/transcripts.json", import.meta.url), "utf8"));
const bundles = window.HoloViewerCloud.validateTranscriptArtifact(transcript);
assert.equal(bundles[0].translations[0].texts.length, bundles[0].segments.length);
assert.throws(() => window.HoloViewerCloud.validateTranscriptArtifact({...transcript, bundles:[{...transcript.bundles[0], translations:[{...transcript.bundles[0].translations[0],texts:[]}]}]}));
console.log("cloud-client contract tests: pass");
