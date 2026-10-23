import assert from "node:assert/strict";
import test from "node:test";
import { assertDisposableIdentity, makeBatchPacket, packetReceipt, executeDisposableBatch } from "./collab_disposable_batch.mjs";

const identity = {kind:"disposable-cloudflare-d1",database_id:"test-disposable-not-prod",binding:"DB",name:"hv197-collab-disposable-ci"};
const event = {event_id:"holoserver-hide-and-seek:5680e7ec7c29074a",event_key:"k",label:"x",confidence:"high",event_date:"2026-10-22",start_at:"2026-10-22T08:00:00Z",end_at:"2026-10-22T10:00:00Z",review_status:"candidate",live_scope:false,payload:{event_id:"holoserver-hide-and-seek:5680e7ec7c29074a"}};
const fixture = {projection_key:"live",source_revision:"sha256:8d0e11e2c08764f643c7751e08ea55e558b71f65eca71a25d89159022ca6fdeb",events:[event],source_event_count:1,effective_event_count:1,generated_at:"2026-10-23T06:00:00Z",source:{range_start:"2026-10-22T00:00:00Z",range_end:"2026-10-23T00:00:00Z"}};

test("production binding identity fails closed", () => {
  assert.throws(() => assertDisposableIdentity({...identity,database_id:"64e1a0ee-1455-4377-9640-3922e8f4d061"}),/STOP/);
  assert.throws(() => assertDisposableIdentity({...identity,name:"holoviewer-public-v1"}),/STOP/);
});
test("reviewable three-statement canonical packet and distinct digest",async () => {
  const packet=makeBatchPacket(fixture);
  assert.equal(packet.length,3);
  assert.match(packet[0].sql,/^UPDATE public_collab_events/);
  assert.match(packet[1].sql,/^INSERT INTO public_collab_events/);
  assert.match(packet[2].sql,/^INSERT INTO public_collab_projection_meta/);
  const receipt=await packetReceipt(packet,identity);
  assert.equal(receipt.statement_digests.length,3);
  assert.equal(receipt.combined_packet_digest.length,64);
  assert.equal(receipt.production_approved,false);
  const failed=makeBatchPacket(fixture,{injectedFailure:true});
  assert.notEqual((await packetReceipt(failed,identity)).combined_packet_digest,receipt.combined_packet_digest);
});
test("batch is invoked once with ordered prepared statements",async () => {
  let batches=0, prepared=[];
  const db={
    prepare(sql) { return {bind(...args) {prepared.push({sql,args});return {sql,args};}}; },
    async batch(xs) {batches++;return xs;}
  };
  const output=await executeDisposableBatch(db,makeBatchPacket(fixture),identity);
  assert.equal(batches,1);
  assert.equal(output.length,3);
  assert.equal(prepared.length,3);
});
test("empty-live packet clears membership and preserves meta",() => {
  const doc={...fixture,events:[],source_event_count:0,effective_event_count:0};
  const packet=makeBatchPacket(doc,{mode:"empty-next-live"});
  assert.equal(packet.length,2);
});
