"""Frozen group-split quality evaluation. Hosted calls require --live-model."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.parser import demo_extract, extract, normalize_hub, llm_configuration
from app.schemas import Constraints
from app.seed import SCENARIO_START

ROOT=Path(__file__).parent


def entities(fields):
    """One entity per scalar field/value or capability member; wrong values incur FP+FN."""
    return {(key,json.dumps(v,sort_keys=True,default=str)) for key,value in fields.items() if value is not None
            for v in (value if isinstance(value,list) else [value])}


def prf(tp,fp,fn):
    precision=tp/(tp+fp) if tp+fp else None
    recall=tp/(tp+fn) if tp+fn else None
    return {'precision':precision,'recall':recall,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
            'tp':tp,'fp':fp,'fn':fn}


def validate_splits(data):
    for kind in ['nlp','policies']:
        rows=data[kind]
        assert len({r['id'] for r in rows})==len(rows)
        assert {r['group'] for r in rows if r['split']=='dev'}.isdisjoint(
            {r['group'] for r in rows if r['split']=='test'}), f'{kind} group leakage'
        assert {r['split'] for r in rows}=={'dev','test'}


def run(split='test',backend='hash',live=False,limit=None,output=None):
    raw=(ROOT/'cases.json').read_bytes()
    data=json.loads(raw);validate_splits(data)
    if live and not llm_configuration()['configured']:
        raise RuntimeError('--live-model requires a configured Gemini/OpenAI model and its own key')
    config=llm_configuration()
    report={'dataset_version':data['version'],'dataset_sha256':hashlib.sha256(raw).hexdigest(),
        'split':split,'embedding_backend':backend,'live_model':live,'partial_run':limit is not None,
        'model':config['model'] if live else None,'provider':config['provider'] if live else None,'construction':data['construction'],
        'limitations':['Test labels are visible in the repository; do not tune on the test split.',
          'Synthetic shared templates, not independently human-labelled data or production accuracy.',
          'Exact entity matching and gold-source citation precision are proxies, not human faithfulness judgement.',
          'No live-model answer-quality metrics are populated without --live-model.'], 'nlp_samples':[],'policy_samples':[]}
    # Disposable SQLite/corpus; never seed or persist evaluation requests in user data.
    with tempfile.TemporaryDirectory(prefix='routemind-quality-') as directory:
        from unittest.mock import patch
        env={'DATA_DIR':directory,'DATABASE_URL':f'sqlite:///{directory}/evaluation.db',
             'EMBEDDING_BACKEND':backend,'MODEL_CACHE_DIR':str(Path(os.getenv('MODEL_CACHE_DIR','.data/models')).resolve())}
        with patch.dict(os.environ,env), TestClient(create_app()) as client:
            hubs,_,_=client.app.state.db.network()
            totals=[0,0,0]; per_field={}; clarify_correct=0; failures=0
            cases=[c for c in data['nlp'] if c['split']==split][:limit]
            for case in cases:
                error=None
                try:
                    fields,questions,*_=extract(case['message'],hubs) if live else (*demo_extract(case['message'],hubs),'rules')
                    for key in ['origin','destination']:
                        if fields.get(key): fields[key]=normalize_hub(fields[key],hubs)
                    predicted=entities(fields); gold=entities(case['expected_fields'])
                    clarification=bool(questions) or any(not fields.get(key) for key in ['origin','destination','pallets'])
                    if not clarification:
                        try: Constraints.model_validate({**fields,'ready_at':fields.get('ready_at') or SCENARIO_START})
                        except ValueError: clarification=True
                except Exception:
                    failures+=1;error='model_or_validation_failure';predicted=set();gold=entities(case['expected_fields']);fields={};clarification=True
                tp,fp,fn=len(predicted&gold),len(predicted-gold),len(gold-predicted)
                totals=[a+b for a,b in zip(totals,[tp,fp,fn])]
                for field in {k for k,_ in predicted|gold}:
                    ps={v for k,v in predicted if k==field};gs={v for k,v in gold if k==field}
                    old=per_field.setdefault(field,[0,0,0]);per_field[field]=[a+b for a,b in zip(old,[len(ps&gs),len(ps-gs),len(gs-ps)])]
                clarify_correct+=clarification==case['needs_clarification']
                report['nlp_samples'].append({'id':case['id'],'group':case['group'],'message':case['message'],
                    'expected':case['expected_fields'],'actual':fields,'expected_clarification':case['needs_clarification'],
                    'actual_clarification':clarification,'error':error})
            report['nlp']={**prf(*totals),'per_field':{k:prf(*v) for k,v in per_field.items()},'cases':len(cases),
                'clarification_accuracy':clarify_correct/len(cases) if cases else None,'failures':failures,
                'mode':'live-typed-extraction' if live else 'offline-rules'}
            # Offline mode must never invoke a hosted policy reader even if keys are present.
            with patch.dict(os.environ,{} if live else {'ROUTEMIND_MODEL':''}):
                citation_tp=citation_fp=answerable_total=abstain_total=abstain_correct=0
                model_samples=0;model_failures=0;retrieval_recalls=[];gate_correct=0
                cases=[c for c in data['policies'] if c['split']==split][:limit]
                for case in cases:
                    response=client.post('/api/v1/policies/questions',json={'question':case['question'],'carrier_ids':case['carrier_ids']})
                    if response.status_code!=200: raise RuntimeError(f'Policy evaluation failed with HTTP {response.status_code}')
                    result=response.json();gold=set(case['gold_source_ids']);found={e['source_id'] for e in result['evidence']}
                    if gold: retrieval_recalls.append(len(gold&found)/len(gold))
                    gate_passed=result['evidence_assessment']['status']=='sufficient_evidence'
                    gate_correct+=gate_passed==case['answerable']
                    model_used=result['mode']=='model-assisted-extractive'
                    if live:
                        if result['status'] not in {'insufficient_evidence','conflicting_evidence'} and not model_used: model_failures+=1
                        else:
                            model_samples+=1
                            ids=[f['source_id'] for f in result['findings']]
                            citation_tp+=sum(i in gold for i in ids);citation_fp+=sum(i not in gold for i in ids)
                            if case['answerable']: answerable_total+=bool(ids)
                            else:
                                abstain_total+=1;abstain_correct+=not ids
                    report['policy_samples'].append({'id':case['id'],'group':case['group'],'question':case['question'],
                        'answerable':case['answerable'],'gold_source_ids':case['gold_source_ids'],'result':result,
                        'human_review':{'relevant':None,'complete':None,'unsupported_claim':None,'notes':''}})
            report['policies']={'cases':len(cases),'answerable_retrieval_recall':sum(retrieval_recalls)/len(retrieval_recalls) if retrieval_recalls else None,
                'relevance_gate_accuracy_proxy':gate_correct/len(cases) if cases else None,
                'citation_precision':citation_tp/(citation_tp+citation_fp) if live and citation_tp+citation_fp else None,
                'unsupported_source_selections':citation_fp if live else None,
                'unanswerable_abstention_accuracy':abstain_correct/abstain_total if live and abstain_total else None,
                'answerable_questions_with_findings':answerable_total if live else None,
                'evaluated_live_or_gate_samples':model_samples if live else 0,'model_failures':model_failures if live else None,
                'human_grounding_review':'not performed; fill exported sample review fields'}
    target=Path(output) if output else ROOT/f'results-{split}-{backend}-{"live" if live else "offline"}.json'
    target.write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(json.dumps({k:v for k,v in report.items() if not k.endswith('_samples')},indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',choices=['dev','test'],default='test')
    parser.add_argument('--backend',choices=['hash','minilm'],default='hash')
    parser.add_argument('--live-model',action='store_true',help='Explicitly enable billed hosted model calls')
    parser.add_argument('--limit',type=int,help='Limit each dataset; marks the report as partial')
    parser.add_argument('--output')
    args=parser.parse_args()
    if args.limit is not None and args.limit<1: parser.error('--limit must be positive')
    run(args.split,args.backend,args.live_model,args.limit,args.output)
