import assert from "node:assert/strict";
import {test} from "node:test";
import {createCustomViewState} from "./custom_view_state.mjs";
import {parseAcceptedSession,createViewingRouteController} from "./viewing_route_controller.mjs";

const A="dQw4w9WgXcQ", B="9bZkp7q19f0";
test("accepted custom builder retains order and selection by video identity",()=>{
 const s=createCustomViewState();
 assert.equal(s.add(A),true);assert.equal(s.add(B),true);
 s.setPrimary(A);s.setAudio(B);s.move(0,1);
 const q=new URLSearchParams(s.sessionQuery());
 assert.deepEqual(q.getAll("stream"),[B,A]);
 assert.equal(q.get("primary"),"1");
 assert.equal(q.get("audio"),"0");
 s.remove(A);
 assert.equal(s.snapshot().primary,B);
 assert.equal(s.snapshot().layout,"auto");
});
test("accepted custom-view layout and validated session URL",()=>{
 const s=createCustomViewState();s.add(A);s.add(B);
 for(const name of ["auto","equal","primary"]){
  assert.equal(s.setLayout(name),true);
  assert.equal(parseAcceptedSession(s.sessionQuery()).layout,name);
 }
 assert.throws(()=>parseAcceptedSession("stream=../invalid"),/invalid/);
 assert.throws(()=>parseAcceptedSession("stream="+A+"&primary=2"),/invalid/);
});
test("route change pauses without unmounting, return reuses frames",()=>{
 const calls=[];
 const host={sync(ids){calls.push(["sync",ids]);},
 activate(value){calls.push(["active",value]);},
 ids(){return [A];}};
 const c=createViewingRouteController(host);
 c.openSession("stream="+A);
 c.navigate("history");
 c.navigate("custom-session");
 assert.deepEqual(calls,[["sync",[A]],["active",true],["active",false],["active",true]]);
});
