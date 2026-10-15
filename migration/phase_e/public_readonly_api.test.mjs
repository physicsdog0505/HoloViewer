import assert from "node:assert/strict";
import { test } from "node:test";
import { endpointFor, videoEndpoint, readPublicApi } from "./public_readonly_api.mjs";

test("only certified read contracts are routable", () => {
  assert.equal(endpointFor("today"), "/v1/catalog/today");
  assert.equal(endpointFor("history", {day:"2026-10-15"}), "/v1/history?day=2026-10-15&limit=50&offset=0");
  assert.equal(videoEndpoint("dQw4w9WgXcQ"), "/v1/catalog/videos/dQw4w9WgXcQ");
  assert.throws(() => endpointFor("ptt", {aid:"example"}), /unsupported/);
  assert.throws(() => endpointFor("history", {day:"2026-10-15",limit:10000}), /invalid/);
  assert.throws(() => videoEndpoint("../bad"), /invalid/);
});

test("read-only requests refuse secrets, redirects and non-v1 paths", async () => {
  const calls=[];
  const fakeFetch=async (url, options)=>{
    calls.push({url,options});
    return {ok:true,json:async()=>({items:[]})};
  };
  await readPublicApi("https://api.example.test", endpointFor("today"), {fetchImpl:fakeFetch});
  assert.equal(calls[0].url,"https://api.example.test/v1/catalog/today");
  assert.equal(calls[0].options.method,"GET");
  assert.equal(calls[0].options.credentials,"omit");
  assert.equal(calls[0].options.redirect,"error");
  await assert.rejects(readPublicApi("http://api.example.test","/v1/catalog/today",{fetchImpl:fakeFetch}),/HTTPS/);
  await assert.rejects(readPublicApi("https://api.example.test","//evil.example/v1/catalog/today",{fetchImpl:fakeFetch}),/outside/);
  await assert.rejects(readPublicApi("https://api.example.test","/admin",{fetchImpl:fakeFetch}),/outside/);
});
