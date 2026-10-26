const $ = id => document.getElementById(id);
function el(tag,text,cls) { const n=document.createElement(tag); n.textContent=text; if(cls)n.className=cls; return n; }
async function json(url, options) {
  const r=await fetch(url,options);
  if(!r.ok) throw new Error(r.status===429 ? 'Too many requests. Please wait a minute and try again.' : `Unable to read policy information (${r.status}). Please try again.`);
  return r.json();
}
json('/api/v1/policies/carriers').then(carriers=>{
  for(const c of carriers) for(const id of ['carrier-one','carrier-two']) { const o=el('option',c.name);o.value=c.id;$(id).append(o); }
}).catch(()=>{ $('policy-error').textContent='Carrier choices could not load. You can still search all documents.'; $('policy-error').hidden=false; });
for(const button of document.querySelectorAll('[data-question]')) button.addEventListener('click',()=>{
  $('question').value=button.dataset.question;
  $('carrier-one').value=button.dataset.first || '';
  $('carrier-two').value=button.dataset.second || '';
  $('question').focus();
});
$('policy-form').addEventListener('submit',async event=>{
  event.preventDefault();
  $('ask').disabled=true; $('policy-status').textContent='Reading policy documents…';
  $('policy-error').hidden=true; $('policy-result').hidden=true;
  const question=$('question').value.trim();
  const carrier_ids=[...new Set([$('carrier-one').value,$('carrier-two').value].filter(Boolean))];
  try {
    const data=await json('/api/v1/policies/questions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,carrier_ids})});
    $('answer-title').textContent=data.status==='answered'?'What the documents say':data.status==='not_documented'?'Not answered by the retrieved documents':'Related passages · Review required';
    $('asked-question').textContent=data.question;
    $('mode').textContent=`${data.mode==='retrieval-only'?'Related-document search only':'Model-assisted passage selection'} · Embeddings: ${data.embedding_backend} · Synthetic evidence`;
    $('warnings').replaceChildren(...data.warnings.map(w=>el('p',w)));
    $('findings').replaceChildren();
    for(const f of data.findings) {
      const section=el('article','','policy-finding');section.append(el('h3',f.carrier_name),el('blockquote',f.quote));
      const a=el('a',`Source: ${f.source_id}`);a.href=`#source-${f.source_id}`;
      a.addEventListener('click',()=>{document.getElementById(`source-${f.source_id}`).open=true;});section.append(a);$('findings').append(section);
    }
    $('gaps').replaceChildren();
    if(data.unanswered_questions.length) {
      $('gaps').append(el('h3','Still unanswered in these documents'));
      const list=el('ul','');for(const gap of data.unanswered_questions)list.append(el('li',gap));$('gaps').append(list);
    }
    $('sources').replaceChildren();
    for(const s of data.evidence) {
      const d=el('details','','policy-source');d.id=`source-${s.source_id}`;
      d.append(el('summary',`${s.carrier_name} · ${s.source_id} · Version ${s.version}`),el('p',s.text),el('p',`${s.document_type} · ${s.provenance} · ${s.retrieval_method}`,'hint'));
      $('sources').append(d);
    }
    if(!data.evidence.length)$('sources').append(el('p','No policy passages are available.'));
    $('policy-boundary').textContent=data.boundary;
    $('policy-result').hidden=false;$('policy-status').textContent='Document review complete.';
    $('policy-result').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(error) { $('policy-error').textContent=error.message; $('policy-error').hidden=false; $('policy-status').textContent=''; }
  finally { $('ask').disabled=false; }
});
