// Pure view selection, shared by browser and offline completeness tests.
export function dayCentral(value=new Date()) {
  return new Intl.DateTimeFormat("en-CA",{timeZone:"America/Chicago",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(value));
}
export function views(data, day=dayCentral()) {
  const latest=new Map();
  for(const record of data.records) if(dayCentral(record.prediction.kickoff_utc)===day) {
    const id=record.prediction.fixture_id;
    if(!latest.has(id)||latest.get(id).prediction.revision<record.prediction.revision)latest.set(id,record);
  }
  const today=[...latest.values()].sort((a,b)=>a.prediction.kickoff_utc.localeCompare(b.prediction.kickoff_utc));
  const predicted=new Set(today.map(r=>r.prediction.fixture_id));
  const unavailable=(data.evaluated||[]).filter(r=>dayCentral(r.kickoff_utc)===day&&!predicted.has(r.fixture_id));
  const top=data.records.filter(r=>dayCentral(r.prediction.kickoff_utc)===day&&r.deliveries.some(e=>e.kind==="top"&&e.state==="reserved"));
  top.sort((a,b)=>Number(b.prediction.confidence)-Number(a.prediction.confidence));
  return {today,unavailable,top,history:[...data.records].sort((a,b)=>b.issued_at.localeCompare(a.issued_at))};
}
export function page(items,index=1,size=25) {
  const pages=Math.max(1,Math.ceil(items.length/size));
  const current=Math.max(1,Math.min(pages,index));
  return {items:items.slice((current-1)*size,current*size),current,pages,total:items.length};
}
