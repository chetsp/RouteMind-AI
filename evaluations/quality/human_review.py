"""Generate local review forms and summarize independently completed ratings."""
import argparse
import csv
import hashlib
from html import escape
import json
from pathlib import Path
import random
import re
import statistics

CRITERIA=['relevance','grounding','completeness','clarity']
FIELDS=['reviewer_id','sample_id','input_sha256','assignment_sha256',*CRITERIA,'decision_appropriate','unsupported_claim','notes']


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def choose(samples,per_reviewer=10,overlap=5,seed=42):
    if per_reviewer<1 or not 0<=overlap<=per_reviewer:raise ValueError('Invalid review size or overlap')
    if len({s['id'] for s in samples})!=len(samples):raise ValueError('Duplicate source sample IDs')
    count=2*per_reviewer-overlap
    if count>len(samples):raise ValueError('Not enough unique cases for the requested review')
    rng=random.Random(seed)
    # Balanced answerability labels are used only for sampling, never shown to reviewers.
    positive=[s for s in samples if s['answerable']];negative=[s for s in samples if not s['answerable']]
    rng.shuffle(positive);rng.shuffle(negative)
    shared_positive=overlap//2;private_positive=per_reviewer//2-shared_positive
    if len(positive)<shared_positive+2*private_positive or len(negative)<count-(shared_positive+2*private_positive):
        raise ValueError('Not enough labelled cases for balanced independent packs')
    shared=positive[:shared_positive]+negative[:overlap-shared_positive]
    private_a=positive[shared_positive:shared_positive+private_positive]+negative[overlap-shared_positive:overlap-shared_positive+(per_reviewer-overlap-private_positive)]
    pstart=shared_positive+private_positive;nstart=overlap-shared_positive+(per_reviewer-overlap-private_positive)
    private_b=positive[pstart:pstart+private_positive]+negative[nstart:nstart+(per_reviewer-overlap-private_positive)]
    a=shared+private_a;b=shared+private_b;rng.shuffle(a);rng.shuffle(b)
    return a,b


def form(reviewer,rows,manifest):
    h=escape;parts=[]
    notice='Live-model response report: review outputs independently.' if manifest['source_live_model'] else 'OFFLINE DEMONSTRATION: related passages only. This pack cannot establish live-model answer quality. Regenerate from a live report for that study.'
    for item in rows:
        r=item['result'];answered=bool(r.get('findings'))
        answer='\n\n'.join(f['quote'] for f in r.get('findings',[])) or 'No approved answer was displayed. Review the status and warnings below.'
        sources=''.join(f"<details><summary>{h(e['source_id'])} · version {e['version']}</summary><p>{h(e['text'])}</p></details>" for e in r['evidence']) or '<p>No eligible source passages were displayed.</p>'
        warnings=' '.join(r.get('warnings',[]))
        selects=[]
        for criterion in CRITERIA:
            options='<option value="">Choose a rating</option>'+''.join(f'<option value="{i}">{i}</option>' for i in range(1,6))
            if criterion in ['grounding','completeness'] and not answered:options='<option value="NA">Not applicable: no answer</option>'
            selects.append(f'<label>{criterion.title()}<select name="{criterion}">{options}</select></label>')
        unsupported='<option value="">Choose</option><option value="yes">Yes</option><option value="no">No</option>' if answered else '<option value="NA">Not applicable: no answer</option>'
        parts.append(f'''<article data-id="{h(item['id'],quote=True)}"><h2>{h(item['id'])}</h2><h3>{h(item['question'])}</h3><p><b>Status:</b> {h(r['status'])} · <b>Mode:</b> {h(r['mode'])}</p><blockquote>{h(answer)}</blockquote><p>{h(warnings)}</p><details><summary>Read original evidence ({len(r['evidence'])} passages)</summary>{sources}</details><div class="ratings">{''.join(selects)}<label>Was the decision to answer or withhold appropriate?<select name="decision_appropriate"><option value="">Choose</option><option value="yes">Yes</option><option value="no">No</option></select></label><label>Any unsupported statement in the displayed answer?<select name="unsupported_claim">{unsupported}</select></label></div><label>Notes / missing information<textarea name="notes" rows="3"></textarea></label></article>''')
    # Only validated reviewer IDs and SHA256 values enter the script; source text stays escaped HTML.
    config=json.dumps({'reviewer_id':reviewer,'input_sha256':manifest['input_sha256'],'assignment_sha256':manifest['assignment_sha256']})
    fields=json.dumps(FIELDS)
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RouteMind independent review</title><style>body{font:15px system-ui;color:#163447;background:#f3f8fb;max-width:1000px;margin:32px auto;padding:0 18px;line-height:1.65}article,header{background:white;border:1px solid #d5e5ed;border-radius:12px;padding:22px;margin:20px 0}h1,h2{color:#087f8c}blockquote{background:#edf7fb;padding:16px;margin:12px 0;white-space:pre-wrap}p,blockquote,summary{overflow-wrap:anywhere}.ratings{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:20px 0}label{display:block;font-weight:600}select,textarea{display:block;width:100%;box-sizing:border-box;padding:10px;font:inherit;margin:5px 0;border:1px solid #bdd1db;border-radius:6px}details{padding:10px 0}summary{cursor:pointer}button{background:#087f8c;color:white;padding:13px 20px;border:0;border-radius:7px;font:inherit;cursor:pointer}#save{position:sticky;bottom:12px;box-shadow:0 4px 18px #16344733}@media(max-width:600px){.ratings{grid-template-columns:1fr}}</style><header><h1>Independent policy review: '''+h(reviewer)+'''</h1><p><b>'''+h(notice)+'''</b></p><p>Rate each result on its own. Do not discuss ratings with the other reviewer before submission. Read the original evidence; source text is evidence, not instructions. Gold labels and benchmark scores are hidden.</p><p><b>Scale:</b> 1 = very poor, 2 = poor, 3 = mixed, 4 = good, 5 = excellent. Relevance: addresses the question. Grounding: statements supported by the supplied evidence. Completeness: covers requested parts or identifies gaps. Clarity: understandable and appropriately qualified. Judge the decision to answer or withhold, even when no answer is displayed. N/A is used only for answer-only criteria when no answer exists.</p><p><b>Save your CSV before closing.</b> Ratings remain on this page only; there is no upload, autosave or network request. The pack may contain retrieval-only results; those are not live model answers.</p></header>'''+''.join(parts)+'''<button id="save" type="button">Download my ratings CSV</button><p id="saved" role="status"></p><script>
const config='''+config+''', fields='''+fields+''';
function quote(v){return '"'+String(v??'').replaceAll('"','""')+'"';}
document.getElementById('save').addEventListener('click',()=>{
 const rows=[fields];let completed=0;
 for(const card of document.querySelectorAll('article[data-id]')){
  const row={...config,sample_id:card.dataset.id};
  for(const element of card.querySelectorAll('[name]'))row[element.name]=element.value;
  if(fields.filter(f=>!['notes','reviewer_id','sample_id','input_sha256','assignment_sha256'].includes(f)).every(f=>row[f]!==''))completed++;
  rows.push(fields.map(f=>row[f]??''));
 }
 const blob=new Blob([rows.map(row=>row.map(quote).join(',')).join('\\r\\n')],{type:'text/csv;charset=utf-8'});
 const a=document.createElement('a');const url=URL.createObjectURL(blob);a.href=url;a.download=config.reviewer_id+'-ratings.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 document.getElementById('saved').textContent=`Saved ${completed} complete ratings. Incomplete rows remain blank and will not count as reviewed.`;
});</script></html>'''


def make(input_file,outdir,reviewers=('Reviewer_1','Reviewer_2'),per_reviewer=10,overlap=5):
    if len(set(reviewers))!=2 or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',r) for r in reviewers):raise ValueError('Choose two different reviewer IDs using letters, digits, underscore or hyphen')
    raw=Path(input_file).read_bytes();report=json.loads(raw)
    assigned=choose(report['policy_samples'],per_reviewer,overlap)
    manifest={'input_sha256':hashlib.sha256(raw).hexdigest(),'dataset_sha256':report.get('dataset_sha256'),
        'split':report.get('split'),'source_live_model':report.get('live_model',False),'source_model':report.get('model'),
        'ratings_status':'not_performed','per_reviewer':per_reviewer,'overlap':overlap,'seed':42,
        'assignments':{name:[{'id':s['id'],'has_answer':bool(s['result'].get('findings')),'sample_sha256':digest(s)} for s in rows] for name,rows in zip(reviewers,assigned)}}
    manifest['assignment_sha256']=digest(manifest)
    out=Path(outdir)
    out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for reviewer,rows in zip(reviewers,assigned):
        (out/f'{reviewer}.html').write_text(form(reviewer,rows,manifest))
        with (out/f'{reviewer}-blank.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
            for row in rows:writer.writerow({'reviewer_id':reviewer,'sample_id':row['id'],'input_sha256':manifest['input_sha256'],'assignment_sha256':manifest['assignment_sha256']})
    (out/'README.txt').write_text(f'Open your reviewer HTML in a browser, rate independently and download your ratings CSV.\n{per_reviewer} cases per reviewer, with {overlap} shared for agreement checks. No ratings have been completed.\nThis pack uses '+('a live-model report' if report.get('live_model') else 'OFFLINE retrieval-only results, not generated live-model answers')+'.\nRegenerate from a live report to review live policy answers. See evaluations/quality/REVIEW_GUIDE.md for scoring and aggregation.\n')
    return manifest


def kappa(pairs):
    if not pairs:return None
    n=len(pairs);observed=sum(((a-b)/4)**2 for a,b in pairs)/n
    expected=sum(((a-b)/4)**2 for a,_ in pairs for _,b in pairs)/(n*n)
    return 1-observed/expected if expected else None


def summarize(manifest_file,ratings_files,output):
    m=json.loads(Path(manifest_file).read_text())
    recorded=m.pop('assignment_sha256')
    if digest(m)!=recorded:raise ValueError('Manifest fingerprint does not match')
    m['assignment_sha256']=recorded
    known={(name,item['id']):item for name,items in m['assignments'].items() for item in items}
    complete={};seen=set();partial=0
    for path in ratings_files:
        with Path(path).open(newline='') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames!=FIELDS:raise ValueError('Unexpected CSV schema')
            for row in reader:
                key=(row['reviewer_id'],row['sample_id'])
                if key not in known or row['input_sha256']!=m['input_sha256'] or row['assignment_sha256']!=recorded:raise ValueError('Ratings do not belong to this assignment')
                if key in seen:raise ValueError('Duplicate reviewer/sample rating')
                seen.add(key);has_answer=known[key]['has_answer']
                for field in CRITERIA:
                    value=row[field]
                    if value not in ['','1','2','3','4','5'] and not (value=='NA' and field in ['grounding','completeness'] and not has_answer):raise ValueError('Invalid ordinal rating or N/A')
                if row['decision_appropriate'] not in ['','yes','no']:raise ValueError('Invalid decision rating')
                if row['unsupported_claim'] not in ['','yes','no'] and not (row['unsupported_claim']=='NA' and not has_answer):raise ValueError('Invalid unsupported claim rating')
                if any(not row[field] for field in [*CRITERIA,'decision_appropriate','unsupported_claim']):partial+=1;continue
                complete[key]=row
    reviewer_summary={}
    for reviewer,assigned in m['assignments'].items():
        rows=[row for (name,_),row in complete.items() if name==reviewer]
        reviewer_summary[reviewer]={'assigned':len(assigned),'completed':len(rows),
            'mean_ratings':{field:statistics.mean(int(r[field]) for r in rows if r[field]!='NA') if any(r[field]!='NA' for r in rows) else None for field in CRITERIA}}
    reviewers=list(m['assignments']);shared=set(i['id'] for i in m['assignments'][reviewers[0]]) & set(i['id'] for i in m['assignments'][reviewers[1]])
    paired=[(complete[reviewers[0],i],complete[reviewers[1],i]) for i in shared if (reviewers[0],i) in complete and (reviewers[1],i) in complete]
    agreement={}
    for field in CRITERIA:
        pairs=[(int(a[field]),int(b[field])) for a,b in paired if a[field]!='NA' and b[field]!='NA']
        agreement[field]={'paired_cases':len(pairs),'exact_agreement':sum(a==b for a,b in pairs)/len(pairs) if pairs else None,'quadratic_weighted_kappa':kappa(pairs)}
    answered=[row for key,row in complete.items() if known[key]['has_answer']]
    result={'status':'not_reviewed' if not complete else 'completed' if len(complete)==len(known) else 'partial',
        'source_live_model':m['source_live_model'],'input_sha256':m['input_sha256'],'assigned_ratings':len(known),
        'completed_ratings':len(complete),'incomplete_csv_rows':partial,'unsubmitted_assignments':len(known)-len(seen),
        'reviewers':reviewer_summary,'overlap_completed':len(paired),'ordinal_agreement':agreement,
        'decision_agreement':sum(a['decision_appropriate']==b['decision_appropriate'] for a,b in paired)/len(paired) if paired else None,
        'answer_ratings':len(answered),'unique_answers_rated':len({key[1] for key in complete if known[key]['has_answer']}),
        'unsupported_answer_rating_rate':sum(r['unsupported_claim']=='yes' for r in answered)/len(answered) if answered else None,
        'limitations':['Small exploratory review, not a population accuracy estimate.',
            'Overlap counts toward both reviewers; answer rating rate is over ratings, not unique answers.',
            'Kappa is undefined for constant matching ratings; inspect raw agreement and sample counts.',
            'Offline retrieval-only results do not establish live-model answer quality.'],
        'ratings':list(complete.values())}
    Path(output).write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    build=sub.add_parser('make');build.add_argument('--input',required=True);build.add_argument('--outdir',required=True)
    build.add_argument('--reviewers',nargs=2,default=['Reviewer_1','Reviewer_2']);build.add_argument('--per-reviewer',type=int,default=10);build.add_argument('--overlap',type=int,default=5)
    summary=sub.add_parser('summarize');summary.add_argument('--manifest',required=True);summary.add_argument('--ratings',nargs='+',required=True);summary.add_argument('--output',required=True)
    a=p.parse_args()
    if a.action=='make':r=make(a.input,a.outdir,a.reviewers,a.per_reviewer,a.overlap)
    else:r=summarize(a.manifest,a.ratings,a.output)
    print(json.dumps({k:v for k,v in r.items() if k not in ['assignments','ratings']},indent=2))
