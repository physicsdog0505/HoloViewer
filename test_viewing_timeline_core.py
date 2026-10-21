from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parent


class ViewingTimelineCoreTests(unittest.TestCase):
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

    def test_pure_timeline_and_share_contract(self):
        script = r"""
const assert=require('node:assert/strict');
const timeline=require('./site/assets/viewing-timeline-core.js');
const share=require('./site/assets/viewing-share-state.js');

const session={
 schema_version:timeline.SCHEMA,
 session_id:'event-20261021',
 revision:'r1',
 absolute_start_ms:1000000,
 master_end_ms:120000,
 povs:[
  {pov_id:'A',segments:[
   {segment_id:'a1',master_start_ms:0,master_end_ms:30000,video_id:'AAAAAAAAAAA',source_start_ms:5000},
   {segment_id:'a2',master_start_ms:30000,master_end_ms:120000,video_id:'BBBBBBBBBBB',source_start_ms:1000},
  ]},
  {pov_id:'B',segments:[
   {segment_id:'b1',master_start_ms:10000,master_end_ms:50000,video_id:'CCCCCCCCCCC',source_start_ms:0},
   {segment_id:'b2',master_start_ms:70000,master_end_ms:120000,video_id:'DDDDDDDDDDD',source_start_ms:9000},
  ]},
 ]
};

assert.equal(timeline.validateSession(session),true);
assert.equal(timeline.sessionAbsoluteTime(session,30000),1030000);
assert.deepEqual(
 timeline.resolvePov(session,'A',30000),
 {status:'READY',pov_id:'A',segment_id:'a2',video_id:'BBBBBBBBBBB',
  master_time_ms:30000,source_time_ms:1000,absolute_time_ms:1030000}
);

const a=timeline.resolvePov(session,'A',20000);
const b=timeline.resolvePov(session,'B',20000);
assert.equal(a.source_time_ms,25000);
assert.equal(b.source_time_ms,10000);
assert.equal(a.absolute_time_ms,b.absolute_time_ms);
assert.equal(a.absolute_time_ms,1020000);

assert.deepEqual(
 timeline.resolvePov(session,'B',60000),
 {status:'NO_COVERAGE',pov_id:'B',master_time_ms:60000,absolute_time_ms:1060000}
);
assert.deepEqual(timeline.breakpointsForPov(session,'A'),[30000]);

const overlap=structuredClone(session);
overlap.povs[0].segments[1].master_start_ms=29999;
assert.throws(()=>timeline.validateSession(overlap),/segment overlap/);

const encoded=share.serialize({
 sessionId:session.session_id,revision:session.revision,povIds:['A','B'],
 primaryPovId:'B',masterTimeMs:60000,layout:'focus',mode:'multi',pttMode:'video'
});
const decoded=share.parse(encoded);
assert.equal(decoded.status,'READY');
assert.deepEqual(decoded.state,{
 sessionId:'event-20261021',revision:'r1',povIds:['A','B'],primaryPovId:'B',
 masterTimeMs:60000,layout:'focus',mode:'multi',pttMode:'video'
});
assert.equal(timeline.sessionAbsoluteTime(session,decoded.state.masterTimeMs),1060000);
assert.equal(share.parse('session=x&pov=A&pov=A&primary_pov=A&t_ms=1').status,'INVALID');
"""
        self.run_node(textwrap.dedent(script))

    def test_core_has_no_dom_route_or_network_dependency(self):
        source = (ROOT / "site/assets/viewing-timeline-core.js").read_text(encoding="utf-8")
        share = (ROOT / "site/assets/viewing-share-state.js").read_text(encoding="utf-8")
        for text in (source, share):
            for forbidden in ("document.", "window.location", "location.href", "fetch(", "XMLHttpRequest", ".style", "querySelector("):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
