const $ = id => document.getElementById(id);
let requestId = null, hubMap = {}, waiting = false;
const examples = {
  cheapest: 'Ship 15 pallets of fragile electronics from Fremont to Austin under $4,000. Find the cheapest route.',
  fastest: 'Find the fastest route for 15 pallets from Fremont to Austin under $4,000 with 97% on-time reliability.',
  clarify: 'Find the cheapest route from Fremont to Austin under $4,000.',
  'no-route': 'Ship 15 pallets of fragile electronics from Fremont to Austin under $500. Find the cheapest route.'
};
function node(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
const money = cents => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(cents/100);
function date(value, hub) {
  const zone = hubMap[hub]?.timezone || 'UTC';
  return new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit', timeZone:zone, timeZoneName:'short'}).format(new Date(value));
}
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join('; ') : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}
function reset() {
  requestId = null; waiting = false;
  localStorage.removeItem('routemind-request');
  $('new-request').hidden = true;
  $('submit').replaceChildren(node('span', 'Find feasible routes'), node('span', '→'));
  $('message').placeholder = 'Describe your shipment…';
}
function render(state) {
  requestId = state.request_id;
  localStorage.setItem('routemind-request', requestId);
  waiting = state.status === 'needs_clarification';
  const area = $('results'); area.replaceChildren();
  $('new-request').hidden = false;
  $('result-count').textContent = state.status === 'completed' ? `${state.plans.length} validated options` : state.status.replaceAll('_',' ');
  $('parser-mode').textContent = `Parser: ${state.parser_mode || 'unavailable'} · Synthetic data`;
  if (!waiting) $('message').value = (state.messages || []).filter(Boolean).join('\n');
  $('submit').replaceChildren(node('span', waiting ? 'Submit clarification' : 'Find feasible routes'), node('span','→'));
  if (waiting) {
    const card = node('div', undefined, 'card clarification');
    card.append(node('h3', 'A few details before we route.'));
    const list = node('ul');
    state.questions.forEach(q => list.append(node('li', q)));
    card.append(list, node('p','Reply in the shipment box or use structured constraints. Previously accepted constraints are retained.'));
    area.append(card);
    $('message').value = '';
    $('message').placeholder = 'For example: 15 pallets';
    $('constraints-panel').open = true;
  } else if (state.status === 'error') {
    area.append(node('div', `${state.error} Request ID: ${state.request_id}`, 'error'));
  } else if (state.status === 'no_route') {
    const card = node('div', undefined, 'card no-route');
    card.append(node('h3','No feasible route found.'), node('p',state.explanation));
    area.append(card);
  } else {
    state.plans.forEach((plan, i) => {
      const card = node('article',undefined,`card ${i===0?'recommended':'alternative'}`);
      const top = node('div',undefined,'card-top');
      const cost = node('div', money(plan.total_cost_cents), 'cost'); cost.append(node('small','USD'));
      top.append(node('span',i===0?'RECOMMENDED':`ALTERNATIVE ${i+1}`,'tag'), cost);
      const route = node('div',undefined,'route');
      plan.route.forEach((hub,index) => { if(index) route.append(node('span','→')); route.append(document.createTextNode(hub)); });
      const metrics = node('div',undefined,'metrics');
      [['ARRIVAL',date(plan.arrival_at,plan.hub_ids.at(-1))],['TRANSIT',`${plan.transit_hours} hours`],['HANDLING',`${plan.leg_count-1} ${plan.leg_count===2?'stop':'stops'}`]].forEach(([label,value])=>{
        const item = node('div'); item.append(node('b',label),document.createTextNode(value)); metrics.append(item);
      });
      const detail = node('details'); detail.append(node('summary','Legs & cost breakdown'));
      plan.legs.forEach(leg => {
        const line = node('div',undefined,'leg');
        line.append(node('strong', `${hubMap[leg.origin]?.name || leg.origin} → ${hubMap[leg.destination]?.name || leg.destination} · ${leg.carrier_name}`),
          node('p', `${date(leg.departure_at,leg.origin)} → ${date(leg.arrival_at,leg.destination)}`),
          node('p', `${money(leg.base_cost_cents)} base + ${state.constraints.pallets} × ${money(leg.per_pallet_cents)} = ${money(leg.transport_cost_cents)} · Transfer ${money(leg.transfer_cost_cents)}`),
          node('p', `${leg.capacity_pallets} pallets available · ${(leg.on_time_rate*100).toFixed(1)}% carrier on-time · Verified: ${leg.verified_capabilities.join(', ') || 'general freight only'} · ${leg.id}`));
        detail.append(line);
      });
      detail.append(node('p',`Transport ${money(plan.transport_cost_cents)} + transfers ${money(plan.transfer_cost_cents)} = ${money(plan.total_cost_cents)}`,'hint'));
      card.append(top,route,metrics,detail); area.append(card);
    });
    const explanation = node('div',undefined,'explanation');
    explanation.append(node('h3','Why this route'), node('div',state.explanation)); area.append(explanation);
  }
  (state.warnings || []).forEach(w => area.append(node('div',w,'warning')));
  if (state.evidence?.length) {
    const evidence = node('details',undefined,'evidence');
    evidence.append(node('summary',`Carrier evidence · ${state.evidence.length} sources`));
    state.evidence.forEach(e => {
      const source = node('div',undefined,'source');
      source.append(node('code',`${e.source_id} · v${e.version} · ${e.document_type} · SYNTHETIC`),node('p',e.text),node('small',`${e.retrieval_method} · ${e.embedding_version}`));
      evidence.append(source);
    }); area.append(evidence);
  }
  const diagnostics = node('details',undefined,'diagnostics');
  diagnostics.append(node('summary','Constraints & audit trail'),node('pre',JSON.stringify({constraints:state.constraints,rejected_transitions:state.rejection_counts,feasible_paths:state.feasible_route_count,workflow:state.trace?.map(t=>t.node),latency_ms:state.latency_ms},null,2)));
  area.append(diagnostics,node('p',`Request ${state.request_id} · Persisted locally on the server`,'request-meta'));
}
document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
  reset(); $('planner').reset(); $('message').value=examples[button.dataset.example]; $('error').hidden=true;
}));
$('new-request').addEventListener('click',()=>{ reset(); $('planner').reset(); $('message').focus(); });
$('planner').addEventListener('submit',async event=>{
  event.preventDefault(); $('error').hidden=true;
  const c={};
  const mappings={origin:'origin',destination:'destination',pallets:'pallets',goal:'optimization_goal',stops:'max_stops',reliability:'min_on_time_rate'};
  for (const [id,key] of Object.entries(mappings)) if($(id).value!=='') c[key]=['pallets','stops','reliability'].includes(id)?Number($(id).value):$(id).value;
  if($('budget').value!=='') c.max_budget_cents=Math.round(Number($('budget').value)*100);
  if($('capability').value) c.required_capabilities=[$('capability').value];
  for (const [id,key] of [['ready','ready_at'],['deadline','delivery_deadline']]) if($(id).value) c[key]=$(''+id).value+':00Z';
  const body={message:$('message').value}; if(Object.keys(c).length) body.constraints=c;
  const path=waiting?`/api/v1/plans/${requestId}/clarify`:'/api/v1/plans';
  $('submit').disabled=true;
  const area=$('results'); const previous=Array.from(area.childNodes); area.replaceChildren();
  const loading=node('div',undefined,'loading');loading.append(node('span',undefined,'spinner'),node('div','Checking schedules, connections & carrier evidence…'));area.append(loading);
  try {render(await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));}
  catch(error){area.replaceChildren(...previous);$('error').textContent=error.message;$('error').hidden=false;}
  finally{$('submit').disabled=false;}
});
async function init(){
  try{
    const [health,hubs]=await Promise.all([api('/health'),api('/api/v1/hubs')]);
    hubMap=Object.fromEntries(hubs.map(h=>[h.id,h]));
    for(const id of ['origin','destination']) hubs.forEach(h=>{const option=node('option',h.name);option.value=h.id;$(id).append(option);});
    $('connection').textContent=`${hubs.length} hubs · Network ready`;
    $('parser-mode').textContent=`Parser: ${health.parser} · ${health.evidence_documents} evidence passages`;
    const saved=localStorage.getItem('routemind-request');
    if(saved) {try{render(await api(`/api/v1/plans/${saved}`));}catch{localStorage.removeItem('routemind-request');}}
  }catch(error){$('connection').textContent='Network unavailable';$('error').textContent=error.message;$('error').hidden=false;}
}
init();
