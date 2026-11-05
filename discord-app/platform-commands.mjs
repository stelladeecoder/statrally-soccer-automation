import {views} from "./platform-ui.mjs";
import {safeText,optionsFor,centralDay} from "./commands.mjs";
import {classifyPrediction} from "./prediction-quality.mjs";
const pct=v=>Number.isFinite(Number(v))?(100*Number(v)).toFixed(1)+"%":"unavailable";
const clock=s=>new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric",minute:"2-digit"}).format(new Date(s));
export function platformCommand(interaction,data,now=new Date()) {
 const name=interaction.data.name,all=views(data,centralDay(now));
 if(name==="performance") {
  const m=data.metrics?.overall;
  if(!m)return "**StatRally forward performance**\nNo saved monitoring report yet. Pending outcomes are not losses.";
  return `**StatRally forward performance**\nPredictions: ${m.total_predictions} | Graded: ${m.graded_predictions} | Pending: ${m.pending_predictions} | Ungradable: ${m.ungradable_predictions}\nAccuracy: ${m.accuracy===null?"unavailable":pct(m.accuracy)} | YES precision: ${m.yes_precision===null?"unavailable":pct(m.yes_precision)} | NO precision: ${m.no_precision===null?"unavailable":pct(m.no_precision)}\nBrier: ${m.brier??"unavailable"} | Log loss: ${m.log_loss??"unavailable"}\nActual immutable prematch records; experimental estimates. No trades or betting ROI. Export: ${data.generated_at}`;
 }
 let rows;
 if(name==="match") {
  const opts=optionsFor(interaction);
  if(opts.length!==1||opts[0].name!=="event_id"||!/^\d{1,20}$/.test(opts[0].value))return "Enter a valid numeric ESPN event ID.";
  rows=all.history.filter(r=>r.prediction.espn_event_id===opts[0].value);
 } else if(name==="picks")rows=all.top.filter(r=>r.deliveries.some(e=>e.kind==="top"&&e.state==="accepted"));
 else rows=all.today;
 const options=optionsFor(interaction),requested=options.find(o=>o.name==="page")?.value??1;
 if(!Number.isInteger(requested)||requested<1||requested>10000)return "Enter a positive page number.";
 const render=r=>{const p=r.prediction,q=classifyPrediction(p,data.selection_policy);return `• **${safeText(p.home_team,50)} vs ${safeText(p.away_team,50)}**\n  ${safeText(p.league)} · ${clock(p.kickoff_utc)} CT · BTTS ${p.side} · selected ${pct(p.confidence)}\n  YES ${pct(p.p_yes)} / NO ${pct(p.p_no)} · ${q.probability_category} (descriptive)\n  ${safeText(p.model_version)} · ${q.calibration_status} · ${safeText(p.data_quality_status)}\n  ${q.selection_eligible?"Policy eligible":"Experimental; no validated selection approval"} · Polymarket: ${safeText(r.market?.status||"provider_unavailable")}\n  ${safeText(r.grade?.status||"pending")} · ESPN ${p.espn_event_id}`;};
 if(name==="picks"&&!rows.length)return `**StatRally | ${centralDay(now)} Central · Validated top selections**\nNo forecasts pass an applicable validated selection policy. Zero selections is a normal outcome. All valid forecasts remain available through /btts.\n${all.historical_highlights.length} previously published experimental highlights remain archived; they are not validated selections.`;
 const entries=rows.map(render);
 if(name==="btts")entries.push(...all.unavailable.map(r=>`• **${safeText(r.home_team,55)} vs ${safeText(r.away_team,55)}**\n  ${safeText(r.league)} · ${clock(r.kickoff_utc)} CT · ${safeText(r.prediction_status)}`));
 const pages=Math.max(1,Math.ceil(entries.length/3)),page=Math.min(requested,pages);
 return `**StatRally | ${centralDay(now)} Central · ${name==="picks"?"Delivered highlights":name==="match"?"Prediction history":"Full BTTS slate"}**\n`+
   (entries.length?entries.slice((page-1)*3,page*3).join("\n"):"No issued records in this view. Future-day fixtures are not substituted.")+`\nPage ${page}/${pages} · ${entries.length} records. ${name==="btts"&&pages>1?"Use /btts page:<number> for every fixture. ":""}Experimental uncalibrated estimates; no trades or proven edge.`;
}
