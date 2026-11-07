import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {once} from "node:events";
import {canonicalPlatform,legacyProjection} from "../platform-data.mjs";
import {platformCommand} from "../platform-commands.mjs";
import {views,page} from "../platform-ui.mjs";
import {createApp} from "../server.mjs";
const fixture=JSON.parse(fs.readFileSync(new URL("fixtures/fictional-platform-ledger.json",import.meta.url)));
const now=new Date("2026-11-05T11:05:00Z");
const data=()=>canonicalPlatform(fixture.issues,fixture.comments,now);

test("Fictional cross-language ledger exposes only verified BTTS markets",()=>{
 const output=data(),v=views(output,"2026-11-05");
 assert.equal(output.records.length,3);assert.equal(v.today.length,3);assert.equal(v.top.length,3);assert.ok(v.historical_highlights.length<=3);
 assert.equal(output.records.filter(r=>r.market.status==="verified_available").length,3);
 assert.equal(output.records.filter(r=>r.market.status==="not_found").length,0);
 assert.ok(output.records.every(r=>r.market.status==="verified_available"));
 assert.equal(output.metrics,null); // Research-wide aggregates are not market-eligible results.
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
test("Per-league coverage is public numeric evidence, while private metric fields are rejected",()=>{
 const f=structuredClone(fixture),score={n:0},report={schema_version:1,status:"forward_recorded_experimental_no_trades",revision_policy:"test",overall:score,
  by_league:{epl:{n:0,evaluated_prematch_fixtures:2,prediction_coverage:.5}},by_model_version:{},by_month:{},
  by_confidence:Object.fromEntries(["0.50-0.55","0.55-0.60","0.60-0.65","0.65-0.70","0.70-0.75","0.75-1.01"].map(k=>[k,{all:score,YES:score,NO:score}])),
  coverage:{predicted_fixtures:1,evaluated_prematch_fixtures:2,fraction:.5},no_model_promoted:true,trades_placed:0,note:"test"};
 const comment={id:9999,user:{login:"github-actions[bot]"},created_at:now.toISOString(),updated_at:now.toISOString(),body:"statrally-prediction-metrics-v1:"+JSON.stringify(report)};
 f.comments["1"].push(comment);assert.equal(canonicalPlatform(f.issues,f.comments,now).metrics,null);
 report.by_league.epl.private_dataset="never-export";comment.body="statrally-prediction-metrics-v1:"+JSON.stringify(report);
 assert.throws(()=>canonicalPlatform(f.issues,f.comments,now));
});
test("Slash response contains only verified-market fixtures",()=>{
 const output=data(),found=new Set();
 for(let i=1;i<=5;i++) {
  const text=platformCommand({data:{name:"btts",options:[{name:"page",value:i}]}},output,now);
  assert.ok(text.length<1900);for(const match of text.matchAll(/ESPN (\d+)/g))found.add(match[1]);
 }
 assert.equal(found.size,3);
});
test("Web routes expose only canonical read-only records without requiring Discord credentials",async()=>{
 const server=createApp({platformReader:async()=>data()});server.listen(0,"127.0.0.1");await once(server,"listening");
 try {
  const base=`http://127.0.0.1:${server.address().port}`;
  const home=await fetch(base+"/");assert.equal(home.status,200);assert.match(await home.text(),/Today's predictions/);
  const api=await fetch(base+"/api/predictions");assert.equal(api.status,200);assert.equal((await api.json()).records.length,3);
  assert.equal((await fetch(base+"/platform-web.mjs")).status,200);
  assert.equal((await fetch(base+"/api/trade",{method:"POST"})).status,404);
 } finally {await new Promise(resolve=>server.close(resolve));}
});
test("Unavailable public export returns an error rather than inventing an empty slate",async()=>{
 const server=createApp({platformReader:async()=>{throw new Error("Fictional outage");}});server.listen(0,"127.0.0.1");await once(server,"listening");
 try {const result=await fetch(`http://127.0.0.1:${server.address().port}/api/predictions`);assert.equal(result.status,503);assert.ok(!(await result.json()).records);}
 finally {await new Promise(resolve=>server.close(resolve));}
});

// Full analytics filters never depend on market availability or ranking.
test("Forecast filters preserve YES NO and pending within verified-market cohort",async()=>{
 const {filterForecasts}=await import("../prediction-quality.mjs");
 const output=data(),policy=output.selection_policy,records=output.records;
 assert.equal(filterForecasts(records,"all",policy).length,3);
 assert.ok(filterForecasts(records,"no",policy).some(r=>Number(r.prediction.confidence)===.72));
 assert.ok(filterForecasts(records,"low",policy).every(r=>Number(r.prediction.confidence)<.55));
 assert.equal(filterForecasts(records,"top",policy).length,3);
 assert.equal(filterForecasts(records,"pending",policy).length,3);
 assert.equal(filterForecasts(records,"graded",policy).length,0);
 for(const r of records)assert.equal(r.presentation.selection_eligible,false);
});

test("Unlimited yellow-star model picks are descriptive and do not include finished fixtures",()=>{
 const output=data(),v=views(output,"2026-11-05");
 assert.equal(v.top.length,3);
 assert.ok(v.top.every(r=>Number(r.prediction.confidence)>=.7));
 const text=platformCommand({data:{name:"picks",options:[{name:"page",value:1}]}},output,now);
 assert.match(text,/⭐ 70%\+ Model Picks/);
 assert.match(text,/🟨/);
 assert.doesNotMatch(text,/Validated top selections/);
 const finished=new Date("2026-11-06T20:00:00Z");
 assert.match(platformCommand({data:{name:"picks"}},output,finished),/No unstarted fixtures/);
});

test("Unverified and identity-mismatched results cannot leak into public views",()=>{
 const f=structuredClone(fixture);
 const record=canonicalPlatform(f.issues,f.comments,now);
 assert.equal(record.records.length,3);
 assert.equal(record.metrics,null);
 for(const row of record.records)assert.equal(row.market.status,"verified_available");
 const matching=views(record,"2026-11-05");
 assert.equal(matching.today.length,3);
 assert.equal(matching.history.length,3);
 assert.equal(matching.top.length,3);
 assert.ok(!platformCommand({data:{name:"btts"}},record,now).includes("Polymarket: not_found"));
 assert.ok(!platformCommand({data:{name:"picks"}},record,now).includes("identity_mismatch"));
});
test("Identity unconfirmed appears in model picks and totals while not-found is removed",()=>{
 const f=structuredClone(fixture);
 const marketRows=Object.values(f.comments).flat().filter(c=>c.body.startsWith("statrally-market-v1:"));
 const unconfirmed=marketRows.find(c=>JSON.parse(c.body.slice("statrally-market-v1:".length)).status==="not_found");
 assert.ok(unconfirmed);
 const m=JSON.parse(unconfirmed.body.slice("statrally-market-v1:".length));
 m.status="identity_mismatch";
 unconfirmed.body="statrally-market-v1:"+JSON.stringify(m);
 const output=canonicalPlatform(f.issues,f.comments,now);
 assert.equal(output.records.length,4);
 assert.equal(output.records.filter(r=>r.market.status==="identity_mismatch").length,1);
 assert.equal(views(output,"2026-11-05").today.length,4);
 const picks=platformCommand({data:{name:"picks"}},output,now);
 assert.match(picks,/identity_mismatch/);
 assert.doesNotMatch(picks,/not_found/);
});
test("Legacy public export keeps its exact schema and immutable forecast bytes",()=>{
 const current=data(),legacy=legacyProjection(current);
 assert.deepEqual(Object.keys(legacy).sort(),["schema_version","generated_at","records","evaluated","coverage","metrics","trades_placed"].sort());
 for(let i=0;i<legacy.records.length;i++) {
  assert.deepEqual(Object.keys(legacy.records[i]).sort(),["comment_id","deliveries","grade","issue_number","issued_at","market","prediction"].sort());
  assert.deepEqual(legacy.records[i].prediction,current.records[i].prediction);
 }
 assert.ok(current.records.every(r=>r.presentation));assert.ok(current.selection_policy);
});

test("Decimal confidence boundaries match saved values without floating-point promotion",async()=>{
 const {probabilityCategory}=await import("../prediction-quality.mjs");
 assert.equal(probabilityCategory("0.54999999999999999"),"Low confidence");
 assert.equal(probabilityCategory("0.59999999999999998"),"Moderate confidence");
 assert.equal(probabilityCategory("0.69999999999999996"),"Higher model probability");
 assert.equal(probabilityCategory("5.5e-1"),"Moderate confidence");
 assert.equal(probabilityCategory("0.70"),"Very high model probability");
 assert.throws(()=>probabilityCategory("0.49999999999999999"));
});
