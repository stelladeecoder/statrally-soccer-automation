import {views,page,dayCentral} from "/platform-ui.mjs";
import {classifyPrediction,filterForecasts,isStarredProbability} from "/prediction-quality.mjs";
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const pct=n=>typeof n==="number"&&Number.isFinite(n)?(100*n).toFixed(1)+"%":"—";
const probability=n=>pct(n===null||n===undefined?null:Number(n));
const kickoff=s=>new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"}).format(new Date(s));
const status=s=>String(s||"pending").replaceAll("_"," ");
let data=null,view="today",number=1;
const content=document.querySelector("#content"),league=document.querySelector("#league"),forecastFilter=document.querySelector("#forecast-filter");
function card(item,history=false){
 const p=item.prediction,g=item.grade||{status:"pending"},q=classifyPrediction(p,data.selection_policy),node=el("article",undefined,"card "+p.side.toLowerCase()+(isStarredProbability(p)?" starred":""));
 node.append(el("h3",p.home_team+" vs "+p.away_team),el("div",p.league.replaceAll("_"," ")+" · "+kickoff(p.kickoff_utc),"muted"));
 const detail=el("div",undefined,"detail");
 detail.append(el("strong","BTTS "+p.side,"side"),el("span","Selected-side estimate "+probability(p.confidence)),el("span","YES "+probability(p.p_yes)+" · NO "+probability(p.p_no)));
 node.append(detail,el("div",(isStarredProbability(p)?"⭐ 🟨 VERY HIGH MODEL PROBABILITY · 70%+":q.probability_category)+" · descriptive, not validated reliability",isStarredProbability(p)?"star-label":""),
  el("div",q.selection_eligible?"Meets an applicable validated selection policy":"Experimental forecast · Not an approved bet selection"),
  el("div","Polymarket US: "+status(item.market?.status||"provider_unavailable")));
 if(g.status==="graded")node.append(el("div",`${g.result} · Final ${g.home_goals}–${g.away_goals} · Verified full-time`));
 else node.append(el("div","Outcome: "+status(g.status)));
 node.append(el("small",`Model ${p.model_version} · ${status(q.calibration_status)} · ${status(p.data_quality_status)}`));
 if(history)node.append(el("small",`Issued ${new Date(item.issued_at).toLocaleString()} · Revision ${p.revision}`));
 if(!q.selection_eligible&&item.deliveries.some(e=>e.kind==="top"))node.append(el("small","Previously highlighted experimentally; not a validated selection. Original record retained."));
 node.append(el("small",`Experimental paper prediction · ${p.fixture_id}`));return node;
}
function table(title,rows){
 const block=el("section"),wrap=el("div",undefined,"table-scroll"),t=el("table"),head=el("tr");block.append(el("h2",title));
 for(const h of ["Group","Graded","Pending","Accuracy","Coverage","YES precision","YES recall","NO precision","NO recall","Brier","Log loss"])head.append(el("th",h));
 const thead=el("thead");thead.append(head);t.append(thead);const tbody=el("tbody");
 for(const [name,s] of rows){const tr=el("tr");for(const v of [name,s.graded_predictions??s.n,s.pending_predictions,pct(s.accuracy),pct(s.prediction_coverage),pct(s.yes_precision),pct(s.yes_recall),pct(s.no_precision),pct(s.no_recall),s.brier?.toFixed(4)??"—",s.log_loss?.toFixed(4)??"—"])tr.append(el("td",String(v??"—")));tbody.append(tr);}
 t.append(tbody);wrap.append(t);block.append(wrap);return block;
}
function performance(){
 const m=data.records.some(r=>r.market?.status!=="verified_available")?null:data.metrics;if(!m){content.append(el("p","Verified-market performance is unavailable until the reporting snapshot is recalculated. Unmatched markets are excluded."));return;}
 const overall=league.value?m.by_league[league.value]:m.overall;if(!overall){content.append(el("p","No forward predictions recorded for this competition yet."));return;}
 const summary=el("div",undefined,"summary");
 for(const [name,v] of [["Predictions",overall.total_predictions],["Graded",overall.graded_predictions],["Pending",overall.pending_predictions],["Ungradable",overall.ungradable_predictions],["Accuracy",pct(overall.accuracy)],["Coverage",pct(league.value?overall.prediction_coverage:m.coverage.fraction)]]){const n=el("div",undefined,"metric");n.append(el("span",name),el("strong",String(v??"—")));summary.append(n);}
 content.append(summary,el("p",m.note,"muted"),table("Historical-prevalence comparison on identical graded fixtures",[["Model",overall.model_baseline_matched],["Prematch prevalence",overall.baseline_same_fixtures]]),
  table("Competition performance",Object.entries(m.by_league)),table("Model version",Object.entries(m.by_model_version)),
  table("Confidence ranges · descriptive only · separate YES/NO samples",Object.entries(m.by_confidence).flatMap(([range,v])=>["YES","NO"].map(side=>[(range==="0.75-1.01"?"75%+":range)+" · "+side,v[side]]))),table("Performance over time",Object.entries(m.by_month)));
}
function render(){
 if(!data)return;content.replaceChildren();document.querySelectorAll("nav button").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.view===view)));
 document.querySelector(".pagination").hidden=view==="performance";forecastFilter.disabled=view==="performance";
 if(view==="performance"){performance();return;}
 const all=views(data),chosen=view==="today"?all.today:view==="top"?all.top:all.history;
 const items=filterForecasts(chosen,forecastFilter.value,data.selection_policy).filter(r=>!league.value||r.prediction.league===league.value),p=page(items,number);number=p.current;
 document.querySelector("#pages").textContent=`Page ${p.current}/${p.pages} · ${p.total} forecasts`;
 document.querySelector("#previous").disabled=p.current===1;document.querySelector("#next").disabled=p.current===p.pages;
 if(view==="top")content.append(el("p","⭐ Every prediction with at least 70% model probability appears here, with no limit. This is not a validated reliability rating or a betting recommendation.","muted"));
 for(const item of p.items)content.append(card(item,view==="history"));
 if(!p.total)content.append(el("p",view==="top"?"No forecasts pass the applicable selection gate. All valid forecasts remain in Today's predictions.":"No issued forecasts in this filtered view. Future-day fixtures are not substituted."));
 if(view==="today"&&forecastFilter.value==="all")for(const item of all.unavailable.filter(r=>!league.value||r.league===league.value)){const n=el("article",undefined,"card");n.append(el("h3",item.home_team+" vs "+item.away_team),el("div",item.league+" · "+kickoff(item.kickoff_utc)),el("div","Prediction status: "+status(item.prediction_status)));content.append(n);}
}
for(const b of document.querySelectorAll("nav button"))b.addEventListener("click",()=>{view=b.dataset.view;number=1;render();});
for(const control of [league,forecastFilter])control.addEventListener("change",()=>{number=1;render();});
document.querySelector("#previous").addEventListener("click",()=>{number--;render();});document.querySelector("#next").addEventListener("click",()=>{number++;render();});
document.querySelector("#day").textContent=dayCentral()+" · America/Chicago";
try{
 const response=await fetch("/api/predictions",{cache:"no-store"});if(!response.ok)throw new Error();data=await response.json();
 for(const name of [...new Set([...data.records.map(r=>r.prediction.league),...(data.evaluated||[]).map(r=>r.league),...Object.keys(data.coverage?.[dayCentral()]||{})])].sort()){const option=el("option",name.replaceAll("_"," "));option.value=name;league.append(option);}
 const source=document.querySelector("#source");source.textContent="Canonical export updated "+new Date(data.generated_at).toLocaleString()+(data.stale?" · STALE: latest refresh unavailable":"");source.className=data.stale?"error":"muted";render();
}catch{const source=document.querySelector("#source");source.textContent="Verified public records are unavailable. No forecasts or outcomes have been substituted.";source.className="error";}
