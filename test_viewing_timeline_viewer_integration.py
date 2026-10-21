from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parent
VIEWER = (ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
HTML = (ROOT / "site/viewer/index.html").read_text(encoding="utf-8")


class ViewingTimelineViewerIntegrationTests(unittest.TestCase):
    def run_node(self, source: str) -> None:
        result = subprocess.run(
            ["node", "-e", source],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            self.fail(result.stdout + result.stderr)

    def test_adapter_breakpoint_primary_and_replacement_contract(self):
        script = r"""
const assert=require('node:assert/strict');
const timeline=require('./site/assets/viewing-timeline-core.js');
const factory=require('./site/assets/viewing-timeline-viewer-adapter.js');
const session={
 schema_version:timeline.SCHEMA,session_id:'event-1',absolute_start_ms:1000000,master_end_ms:100000,
 povs:[
  {pov_id:'A',segments:[
   {segment_id:'a1',master_start_ms:0,master_end_ms:40000,video_id:'AAAAAAAAAAA',source_start_ms:5000},
   {segment_id:'a2',master_start_ms:40000,master_end_ms:100000,video_id:'BBBBBBBBBBB',source_start_ms:2000},
  ]},
  {pov_id:'B',segments:[
   {segment_id:'b1',master_start_ms:0,master_end_ms:100000,video_id:'CCCCCCCCCCC',source_start_ms:10000},
  ]},
 ]
};
const adapter=factory.create(session,{timeline,initialMasterTimeMs:39999,primaryPovId:'A'});
const absoluteBefore=adapter.absoluteTimeMs();
adapter.setPrimaryPov('B');
assert.equal(adapter.absoluteTimeMs(),absoluteBefore);
adapter.setPrimaryPov('A');

let plan=adapter.plan({A:'AAAAAAAAAAA',B:'CCCCCCCCCCC'});
assert.equal(plan.find(x=>x.pov_id==='A').replace,false);
assert.equal(plan.find(x=>x.pov_id==='B').replace,false);

adapter.setMasterTimeMs(40000);
assert.equal(adapter.absoluteTimeMs(),1040000);
plan=adapter.plan({A:'AAAAAAAAAAA',B:'CCCCCCCCCCC'});
assert.equal(plan.find(x=>x.pov_id==='A').replace,true);
assert.equal(plan.find(x=>x.pov_id==='A').video_id,'BBBBBBBBBBB');
assert.equal(plan.find(x=>x.pov_id==='B').replace,false);

adapter.setMasterTimeMs(39999);
plan=adapter.plan({A:'BBBBBBBBBBB',B:'CCCCCCCCCCC'});
assert.equal(plan.find(x=>x.pov_id==='A').replace,true);
assert.equal(plan.find(x=>x.pov_id==='A').video_id,'AAAAAAAAAAA');
assert.equal(plan.find(x=>x.pov_id==='B').replace,false);

adapter.setMasterTimeMs(39000);
assert.equal(adapter.masterFromSource('A','AAAAAAAAAAA',45000),40000);
"""
        self.run_node(textwrap.dedent(script))

    def test_viewer_loads_shared_modules_before_runtime(self):
        expected = [
            '/assets/viewing-timeline-core.js',
            '/assets/viewing-share-state.js',
            '/assets/viewing-timeline-viewer-adapter.js',
            '/assets/viewer-standalone.js',
        ]
        positions = [HTML.index(value) for value in expected]
        self.assertEqual(positions, sorted(positions))

    def test_viewer_uses_session_clock_for_ptt_and_primary_is_presentation_only(self):
        self.assertIn("if(viewingTimelineActive())return viewingAdapter.absoluteTimeMs();", VIEWER)
        self.assertIn("if(primaryChanged&&!viewingTimelineActive())resolvePrimaryPtt();", VIEWER)
        self.assertIn("viewingAdapter.setPrimaryPov(streams[index].povId)", VIEWER)
        self.assertIn("async function resolveViewingSessionPtt()", VIEWER)
        self.assertIn("const startMs=viewingSession.absolute_start_ms;", VIEWER)
        self.assertIn("const endMs=startMs+viewingSession.master_end_ms;", VIEWER)

    def test_viewer_replaces_only_resolved_pov_and_keeps_same_source_player(self):
        self.assertIn("function replaceTimelinePovSource(index,resolved)", VIEWER)
        self.assertIn("if(String(stream.videoId)===String(resolved.video_id))return false;", VIEWER)
        self.assertIn("if(resolved.replace){\n    replaceTimelinePovSource(index,resolved);", VIEWER)
        self.assertIn("if(player&&(!Number.isFinite(currentSeconds)||Math.abs(currentSeconds-target)>1.2))", VIEWER)
        self.assertNotIn("destroyPlayers();\n  const plan=viewingAdapter.plan", VIEWER)

    def test_share_state_runtime_reconstruction_is_real(self):
        self.assertIn("const parsed=viewingShareState.parse(params);", VIEWER)
        self.assertIn("viewingShareState.serialize({", VIEWER)
        self.assertIn("sessionId:viewingSession.session_id", VIEWER)
        self.assertIn("primaryPovId:viewingAdapter.primaryPovId", VIEWER)
        self.assertIn("masterTimeMs:viewingAdapter.masterTimeMs", VIEWER)
        self.assertIn("q.append(key,value)", VIEWER)


if __name__ == "__main__":
    unittest.main()
