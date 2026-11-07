// Explicit public projection of canonical forward records. No model execution.
import crypto from "node:crypto";
import { centralDay } from "./commands.mjs";
import fs from "node:fs";
import {classifyPrediction,validPolicy} from "./prediction-quality.mjs";
const selectionPolicy=JSON.parse(fs.readFileSync(new URL("../config/prediction_selection_policy.json",import.meta.url)));

const BOT = "github-actions[bot]";
const prefix = "statrally-";
const forecastFields = new Set("fixture_id espn_event_id league home_team away_team espn_home_team_id espn_away_team_id kickoff_utc fixture_observed_at fixture_source prediction_status p_yes p_no side confidence model_name model_version created_at history_coverage identity_verified probabilities_calibrated data_quality_status baseline_yes_probability prediction_source prediction_id revision".split(" "));
const leagues = new Set("epl bundesliga laliga serie_a ligue_1 eredivisie liga_portugal brasileirao mls liga_mx primera_lpf champions_league europa_league".split(" "));
const markets = new Set(["verified_available", "not_found", "identity_mismatch", "market_closed", "provider_unavailable"]);
const numeric = value => value === null || (typeof value === "number" && Number.isFinite(value));
export function canonical(value) {
  const sort = x => Array.isArray(x) ? x.map(sort) : x && typeof x === "object"
    ? Object.fromEntries(Object.keys(x).sort().map(k => [k, sort(x[k])])) : x;
  return JSON.stringify(sort(value)).replace(/[\u007f-\uffff]/g, c => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
}
export function forecastId(p) {
  const value = Object.fromEntries(Object.entries(p).filter(([k]) => !["created_at", "fixture_observed_at", "prediction_id", "revision"].includes(k)));
  return crypto.createHash("sha256").update(canonical(value)).digest("hex");
}
function stamp(value) {
  const ms = Date.parse(value);
  if (typeof value !== "string" || !/(Z|[+-]\d\d:\d\d)$/i.test(value) || !Number.isFinite(ms)) throw new Error("Invalid aware record timestamp");
  return ms;
}
function readEvent(comment, name) {
  const marker = prefix + name + "-v1:";
  if (comment?.user?.login !== BOT || !String(comment.body || "").startsWith(marker)) return null;
  if (stamp(comment.created_at) !== stamp(comment.updated_at)) throw new Error("Edited canonical event");
  return JSON.parse(comment.body.slice(marker.length));
}
function validate(p, comment, day) {
  if (!p || typeof p !== "object" || Object.keys(p).length !== forecastFields.size || Object.keys(p).some(k => !forecastFields.has(k))) throw new Error("Unreviewed prediction fields");
  if (!leagues.has(p.league) || p.fixture_id !== `espn:${p.league}:${p.espn_event_id}` || p.prediction_id !== forecastId(p)) throw new Error("Prediction identity mismatch");
  for (const key of ["espn_event_id", "espn_home_team_id", "espn_away_team_id"]) if (!/^\d{1,20}$/.test(p[key])) throw new Error("Invalid stable identity");
  for (const key of ["home_team", "away_team"]) if (typeof p[key] !== "string" || !p[key].trim() || p[key].length > 400 || /[\x00-\x1f]/.test(p[key])) throw new Error("Invalid team name");
  const y = Number(p.p_yes), n = Number(p.p_no), conf = Number(p.confidence);
  if (![y,n,conf].every(v => Number.isFinite(v) && v >= 0 && v <= 1) || Math.abs(y+n-1) > 1e-12 ||
      Math.abs(conf-Math.max(y,n)) > 1e-12 || p.side !== (y >= .5 ? "YES" : "NO")) throw new Error("Contradictory prediction");
  if (p.model_name !== "uncalibrated_rolling_poisson" || p.model_version !== "rolling-poisson-10-v1" || p.identity_verified !== true ||
      p.probabilities_calibrated !== false || p.prediction_status !== "predicted" || p.prediction_source !== "forward_recorded" ||
      !["research_snapshot", "reviewed_domestic_proxy"].includes(p.data_quality_status)) throw new Error("Unapproved prediction provenance");
  const kickoff = stamp(p.kickoff_utc), issued = stamp(comment.created_at), created = stamp(p.created_at);
  if (!(stamp(p.fixture_observed_at) <= created && created <= issued && issued + 1000 < kickoff) ||
      centralDay(new Date(kickoff)) !== day || centralDay(new Date(created)) !== day || !Number.isInteger(p.revision) || p.revision < 1) throw new Error("Forecast was not issued prematch");
  const h = p.history_coverage;
  if (!h || Object.keys(h).sort().join(",") !== ["minimum_matches_per_team", "home_matches_used", "away_matches_used", "latest_history_date", "source"].sort().join(",") ||
      h.minimum_matches_per_team !== 10 || h.home_matches_used !== 10 || h.away_matches_used !== 10 ||
      !["same_competition", "reviewed_domestic_proxy"].includes(h.source) || !/^\d{4}-\d{2}-\d{2}$/.test(h.latest_history_date) ||
      h.latest_history_date >= new Date(created).toISOString().slice(0,10)) throw new Error("Historical coverage guard failed");
}
const scoreFields = new Set("n accuracy balanced_accuracy brier log_loss ece yes_precision no_precision yes_recall no_recall yes_f1 no_f1 accuracy_wilson_95 confusion total_predictions graded_predictions pending_predictions ungradable_predictions correct_predictions incorrect_predictions yes_accuracy no_accuracy baseline_same_fixtures model_baseline_matched evaluated_prematch_fixtures prediction_coverage".split(" "));
function safeScore(value) {
  if (!value || typeof value !== "object" || Object.keys(value).some(k => !scoreFields.has(k))) throw new Error("Unreviewed aggregate fields");
  for (const [k,v] of Object.entries(value)) {
    if (["baseline_same_fixtures", "model_baseline_matched"].includes(k)) safeScore(v);
    else if (k === "confusion") { if (Object.keys(v).sort().join(",") !== "fn,fp,tn,tp" || !Object.values(v).every(numeric)) throw new Error("Invalid aggregate matrix"); }
    else if (k === "accuracy_wilson_95") { if (v !== null && (!Array.isArray(v) || v.length !== 2 || !v.every(numeric))) throw new Error("Invalid interval"); }
    else if (!numeric(v)) throw new Error("Non-numeric aggregate");
  }
  return value;
}
function safeMetrics(value) {
  const keys = new Set("schema_version status revision_policy overall by_league by_model_version by_confidence by_month coverage no_model_promoted trades_placed note".split(" "));
  if (!value || Object.keys(value).length !== keys.size || Object.keys(value).some(k => !keys.has(k)) || value.trades_placed !== 0 || value.no_model_promoted !== true) throw new Error("Invalid monitoring projection");
  safeScore(value.overall);
  for (const key of ["by_league","by_model_version","by_month"]) for (const [group,v] of Object.entries(value[key])) {
    if (!/^[A-Za-z0-9_.-]{1,100}$/.test(group) || (key === "by_league" && !leagues.has(group))) throw new Error("Invalid metric group");
    safeScore(v);
  }
  for (const [range,v] of Object.entries(value.by_confidence)) {
    if (!/^0\.(50-0\.55|55-0\.60|60-0\.65|65-0\.70|70-0\.75|75-1\.01)$/.test(range) || Object.keys(v).sort().join(",") !== "NO,YES,all") throw new Error("Invalid confidence groups");
    for (const s of Object.values(v)) safeScore(s);
  }
  if (Object.keys(value.coverage).sort().join(",") !== "evaluated_prematch_fixtures,fraction,predicted_fixtures" || !Object.values(value.coverage).every(numeric)) throw new Error("Invalid coverage metrics");
  return {...value, revision_policy:"First issued forecast per fixture; first per fixture/model version in model groups.", note:"Experimental uncalibrated estimates; small samples do not establish a reliable confidence range or betting edge."};
}
function safeCoverage(value) {
  if (!value || typeof value!=="object" || Object.keys(value).some(k=>!leagues.has(k))) throw new Error("Invalid competition coverage");
  for(const row of Object.values(value)) {
    if(Object.keys(row).sort().join(",")!=="excluded,failed_queries,fixtures,predicted,provider_status" ||
       !["complete","incomplete"].includes(row.provider_status) ||
       ![row.failed_queries,row.fixtures,row.predicted].every(v=>Number.isInteger(v)&&v>=0) ||
       Object.keys(row.excluded).some(k=>!["predicted","insufficient_history","unresolved_team_identity","missing_fixture_data","model_error"].includes(k)) ||
       !Object.values(row.excluded).every(v=>Number.isInteger(v)&&v>=0)) throw new Error("Unreviewed coverage fields");
  }
  return value;
}

export function canonicalPlatform(issues, comments, now = new Date()) {
  const records = [], evaluated = new Map(), ids = new Set(), days = new Set();
  let metrics = null, metricTime = 0, coverage = {};
  for (const issue of issues) {
    if (issue?.user?.login !== BOT || issue.pull_request || !String(issue.body || "").startsWith("statrally-prediction-ledger-v1:")) continue;
    const metadata = JSON.parse(issue.body.slice("statrally-prediction-ledger-v1:".length));
    if (metadata.schema_version !== 1 || !/^\d{4}-\d{2}-\d{2}$/.test(metadata.date_central) || days.has(metadata.date_central)) throw new Error("Ambiguous ledger day");
    days.add(metadata.date_central);
    const rows = comments[String(issue.number)] || [];
    for (const comment of rows) {
      const p = readEvent(comment,"prediction");
      if (p) {
        const quarantined=rows.some(row=>{const q=readEvent(row,"prediction-quarantine");return q?.prediction_id===p.prediction_id&&q.comment_id===comment.id&&q.reason==="not_issued_prematch";});
        if(quarantined&&stamp(comment.created_at)+1000>=stamp(p.kickoff_utc))continue;
        validate(p,comment,metadata.date_central);
        if (ids.has(p.prediction_id)) throw new Error("Duplicate canonical forecast");
        ids.add(p.prediction_id);
        records.push({prediction:p, issued_at:comment.created_at, issue_number:issue.number, comment_id:comment.id,
                      market:{status:"provider_unavailable"}, grade:{status:"pending"}, deliveries:[]});
      }
      const scan = readEvent(comment,"prediction-scan");
      if (scan) {
        coverage[scan.date_central] = safeCoverage(scan.coverage);
        for (const raw of scan.evaluated) {
          const keys = "fixture_id espn_event_id league home_team away_team kickoff_utc fixture_observed_at fixture_source prediction_status espn_home_team_id espn_away_team_id reason".split(" ");
          if (Object.keys(raw).some(k => !keys.includes(k)) || !leagues.has(raw.league)) throw new Error("Unreviewed evaluated fixture");
          evaluated.set(raw.fixture_id,Object.fromEntries(keys.filter(k => k in raw).map(k => [k,raw[k]])));
        }
      }
      const report = readEvent(comment,"prediction-metrics");
      if (report && stamp(comment.created_at) >= metricTime) { metrics=safeMetrics(report);metricTime=stamp(comment.created_at); }
    }
  }
  const byId = new Map(records.map(r => [r.prediction.prediction_id,r]));
  for (const issue of issues) for (const comment of comments[String(issue.number)] || []) {
    for (const name of ["market","grade","prediction-delivery"]) {
      const event = readEvent(comment,name);
      if (!event) continue;
      const item=byId.get(event.prediction_id);
      if (!item) continue;
      if(item.issue_number!==issue.number)throw new Error("Canonical event attached to the wrong ledger");
      if (name === "market") {
        const allowed = new Set("prediction_id provider status checked_at event_slug market_slug".split(" "));
        if (Object.keys(event).some(k => !allowed.has(k)) || !markets.has(event.status) || event.provider !== "polymarket_us") throw new Error("Invalid market annotation");
        item.market=event;
      } else if (name === "grade") {
        const allowed=new Set("prediction_id status reason btts_yes correct result home_goals away_goals side graded_at source_observed_at source source_url".split(" "));
        if (Object.keys(event).some(k => !allowed.has(k)) || !["graded","pending","postponed","canceled","abandoned","provider_unavailable","unconfirmed"].includes(event.status)) throw new Error("Invalid grade projection");
        if (event.status === "graded") {
          const actual=event.home_goals>0 && event.away_goals>0, correct=(item.prediction.side === "YES") === actual;
          if (![event.home_goals,event.away_goals].every(n => Number.isInteger(n) && n>=0) || event.btts_yes!==actual || event.correct!==correct ||
              event.result!==(correct?"WIN":"LOSS") || event.side!==item.prediction.side || event.source!=="ESPN scoreboard" ||
              !/^https:\/\/site\.api\.espn\.com\/apis\/site\/v2\/sports\/soccer\/[a-z0-9.]+\/scoreboard\?dates=\d{8}$/.test(event.source_url) ||
              stamp(event.source_observed_at)<stamp(item.prediction.kickoff_utc) || stamp(event.graded_at)<stamp(event.source_observed_at) ||
              stamp(comment.created_at)+1000<stamp(event.graded_at)) throw new Error("Unverified or contradictory final score");
          if (item.grade.status === "graded") throw new Error("Conflicting repeated final grade");
          item.grade=event;
        } else if (item.grade.status!=="graded") item.grade=event;
      } else {
        const allowed = new Set(["prediction_id","kind","state","reserved_at","receipt"]);
        if (Object.keys(event).some(k=>!allowed.has(k)) || !["daily","top","result"].includes(event.kind) || !["reserved","accepted"].includes(event.state)) throw new Error("Invalid delivery projection");
        if (event.receipt && (Object.keys(event.receipt).sort().join(",")!=="channel_id,message_id" || !Object.values(event.receipt).every(v=>/^\d{1,22}$/.test(v)))) throw new Error("Invalid public receipt");
        item.deliveries.push(event);
      }
    }
  }
  if(!validPolicy(selectionPolicy))throw new Error("Invalid checked-in selection policy");
  // Preserve all source records internally for validation, but only expose
  // verified BTTS markets to public-facing pick/result/performance clients.
  // An aggregate computed over ALL research forecasts cannot be presented as
  // market-eligible performance; suppress it until re-scoped upstream.
  const eligible=records.filter(r=>r.market.status==="verified_available");
  for(const record of eligible)record.presentation=classifyPrediction(record.prediction,selectionPolicy,now);
  return {schema_version:1,generated_at:now.toISOString(),records:eligible,evaluated:[...evaluated.values()],coverage,
          metrics:eligible.length===records.length?metrics:null,
          selection_policy:selectionPolicy,trades_placed:0};
}

// Preserve the pre-policy public contract for hosted clients deployed earlier.
export function legacyProjection(data) {
 const {selection_policy,...legacy}=data;
 return {...legacy,records:data.records.map(({presentation,...record})=>record)};
}

const publicSource="https://raw.githubusercontent.com/stelladeecoder/statrally-soccer-automation/main/docs/predictions-public-v2.json";
let cached=null, cachedAt=0;
export async function publicPlatform({fetcher=fetch,now=new Date()}={}) {
  if (cached && now.getTime()-cachedAt<60000) return cached;
  const response=await fetcher(publicSource,{signal:AbortSignal.timeout(5500),headers:{"User-Agent":"StatRally-Public-Analytics/1"}});
  if (!response.ok) throw new Error("Canonical public export unavailable");
  const value=await response.json();
  const rootKeys=new Set(["schema_version","generated_at","records","evaluated","coverage","metrics","trades_placed","selection_policy"]);
  if (value?.schema_version!==1 || value.trades_placed!==0 || !Array.isArray(value.records) || !Array.isArray(value.evaluated) ||
      Object.keys(value).some(k=>!rootKeys.has(k)) || !Number.isFinite(Date.parse(value.generated_at))) throw new Error("Invalid canonical public export");
  for(const item of value.records) {
    if(Object.keys(item).filter(k=>k!=="presentation").sort().join(",")!=="comment_id,deliveries,grade,issue_number,issued_at,market,prediction")throw new Error("Unreviewed public record fields");
    validate(item.prediction,{created_at:item.issued_at},centralDay(new Date(item.prediction.kickoff_utc)));
    item.presentation=classifyPrediction(item.prediction,selectionPolicy,now);
  }
  if(value.metrics)safeMetrics(value.metrics);
  for(const row of Object.values(value.coverage))safeCoverage(row);
  const eligible=value.records.filter(r=>r.market?.status==="verified_available");
  // Also gate older already-published snapshots; never silently display
  // unverified-market records or research-wide metrics as pick performance.
  cached={...value,records:eligible,metrics:eligible.length===value.records.length?value.metrics:null,
          selection_policy:selectionPolicy,stale:now.getTime()-Date.parse(value.generated_at)>45*60*1000};
  cachedAt=now.getTime();return cached;
}

export function todayRows(data, now=new Date()) {
  const day=centralDay(now), latest=new Map();
  for (const item of data.records) if (centralDay(new Date(item.prediction.kickoff_utc))===day) {
    const key=item.prediction.fixture_id;
    if (!latest.has(key)||latest.get(key).prediction.revision<item.prediction.revision) latest.set(key,item);
  }
  return [...latest.values()].sort((a,b)=>Date.parse(a.prediction.kickoff_utc)-Date.parse(b.prediction.kickoff_utc));
}
