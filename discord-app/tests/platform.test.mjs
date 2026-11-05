import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {once} from "node:events";
import {canonicalPlatform} from "../platform-data.mjs";
import {platformCommand} from "../platform-commands.mjs";
import {views,page} from "../platform-ui.mjs";
import {createApp} from "../server.mjs";
const fixture=JSON.parse(fs.readFileSync(new URL("fixtures/fictional-platform-ledger.json",import.meta.url)));
const now=new Date("2026-11-05T11:05:00Z");
const data=()=>canonicalPlatform(fixture.issues,fixture.comments,now);

test("Fictional cross-language ledger retains all 14 fixtures, three markets and three separate highlights",()=>{
 const output=data(),v=views(output,"2026-11-05");
 assert.equal(output.records.length,14);assert.equal(v.today.length,14);assert.equal(v.top.length,3);
 assert.equal(output.records.filter(r=>r.market.status==="verified_available").length,3);
 assert.equal(output.records.filter(r=>r.market.status==="not_found").length,11);
 assert.equal(output.records[0].prediction.side,"NO");assert.ok(Math.abs(Number(output.records[0].prediction.confidence)-.72)<1e-12);
 assert.ok(output.records[0].prediction.home_team.includes("Café 🚀"));
});
test("Edited or post-kickoff forecasts and unreviewed private fields fail closed",()=>{
 for(const kind of ["edit","late","private"]) {
  const f=structuredClone(fixture),comment=f.comments["1"].find(c=>c.body.startsWith("statrally-prediction-v1:"));
  if(kind==="edit")comment.updated_at="2026-11-06T00:00:00Z";
  if(kind==="late")comment.created_at=comment.updated_at="2026-11-06T00:00:00Z";
  if(kind==="private") {const p=JSON.parse(comment.body.slice("statrally-prediction-v1:".length));p.private_dataset="NEVER EXPOSE";comment.body="statrally-prediction-v1:"+JSON.stringify(p);}
  assert.throws(()=>canonicalPlatform(f.issues,f.comments,now));
 }
});
test("Same-day views never substitute future dates and busy pagination loses no fixtures",()=>{
 const output=data();assert.equal(views(output,"2026-11-06").today.length,0);
 const records=Array.from({length:127},(_,i)=>i),collected=[];
 for(let i=1;i<=6;i++)collected.push(...page(records,i).items);
 assert.deepEqual(collected,records);
});
test("Full-slate slash response exposes every fixture through bounded pages",()=>{
 const output=data(),found=new Set();
 for(let i=1;i<=5;i++) {
  const text=platformCommand({data:{name:"btts",options:[{name:"page",value:i}]}},output,now);
  assert.ok(text.length<1900);for(const match of text.matchAll(/ESPN (\d+)/g))found.add(match[1]);
 }
 assert.equal(found.size,14);
});
test("Web routes expose only canonical read-only records without requiring Discord credentials",async()=>{
 const server=createApp({platformReader:async()=>data()});server.listen(0,"127.0.0.1");await once(server,"listening");
 try {
  const base=`http://127.0.0.1:${server.address().port}`;
  const home=await fetch(base+"/");assert.equal(home.status,200);assert.match(await home.text(),/Today's predictions/);
  const api=await fetch(base+"/api/predictions");assert.equal(api.status,200);assert.equal((await api.json()).records.length,14);
  assert.equal((await fetch(base+"/platform-web.mjs")).status,200);
  assert.equal((await fetch(base+"/api/trade",{method:"POST"})).status,404);
 } finally {await new Promise(resolve=>server.close(resolve));}
});
test("Unavailable public export returns an error rather than inventing an empty slate",async()=>{
 const server=createApp({platformReader:async()=>{throw new Error("Fictional outage");}});server.listen(0,"127.0.0.1");await once(server,"listening");
 try {const result=await fetch(`http://127.0.0.1:${server.address().port}/api/predictions`);assert.equal(result.status,503);assert.ok(!(await result.json()).records);}
 finally {await new Promise(resolve=>server.close(resolve));}
});
