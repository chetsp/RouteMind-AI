"""Paired rules / typed-model comparison. A model call requires --live-model."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from app.database import Database
from app.seed import seed, SCENARIO_START
from app.parser import demo_extract, extract, llm_configuration, normalize_hub
from app.schemas import Constraints
from evaluations.quality.run import ROOT, entities, prf, validate_splits


def score(fields, questions, hubs, case, failure=False):
    fields=deepcopy(fields)
    for key in ['origin','destination']:
        if fields.get(key): fields[key]=normalize_hub(fields[key],hubs)
    actual=entities(fields);gold=entities(case['expected_fields'])
    clarify=bool(questions) or any(not fields.get(key) for key in ['origin','destination','pallets'])
    if not clarify:
        try: Constraints.model_validate({**fields,'ready_at':fields.get('ready_at') or SCENARIO_START})
        except ValueError: clarify=True
    return {'fields':fields,'clarification':clarify,'counts':[len(actual&gold),len(actual-gold),len(gold-actual)],
            'exact_fields':actual==gold and not failure,
            'clarification_correct':clarify==case['needs_clarification'] and not failure}


def aggregate(samples):
    tp=fp=fn=0
    for sample in samples:
        a,b,c=sample['counts'];tp+=a;fp+=b;fn+=c
    n=len(samples)
    return {**prf(tp,fp,fn),'cases':n,'exact_field_accuracy':sum(s['exact_fields'] for s in samples)/n if n else None,
            'clarification_accuracy':sum(s['clarification_correct'] for s in samples)/n if n else None,
            'failures':sum(s['error'] is not None for s in samples),
            'p50_ms':statistics.median(s['latency_ms'] for s in samples) if samples else None}


def run(split='dev',live=False,limit=None,output=None):
    raw=(ROOT/'cases.json').read_bytes();dataset=json.loads(raw);validate_splits(dataset)
    config=llm_configuration()
    if live and not config['configured']: raise RuntimeError('--live-model requires configured Gemini/OpenAI credentials')
    cases=[c for c in dataset['nlp'] if c['split']==split][:limit]
    results=[];rules_samples=[];model_samples=[]
    with tempfile.TemporaryDirectory(prefix='routemind-parser-') as directory:
        db=Database(f'sqlite:///{directory}/parser.db')
        try:
            seed(db);hubs,_,_=db.network()
            for case in cases:
                paired={'id':case['id'],'group':case['group'],'message':case['message'],
                        'expected_fields':case['expected_fields'],'expected_clarification':case['needs_clarification']}
                for name,enabled in [('rules',True),('model',live)]:
                    if not enabled: paired[name]=None;continue
                    start=time.perf_counter();error=None
                    try:
                        fields,questions,*_=(*demo_extract(case['message'],hubs),'rules') if name=='rules' else extract(case['message'],hubs)
                    except Exception:
                        fields={};questions=[];error='model_or_parser_failure'
                    result=score(fields,questions,hubs,case,error is not None)
                    result.update(error=error,latency_ms=round((time.perf_counter()-start)*1000,3))
                    paired[name]=result
                    (rules_samples if name=='rules' else model_samples).append(result)
                results.append(paired)
        finally: db.engine.dispose()
    rules=aggregate(rules_samples);model=aggregate(model_samples) if live else None
    report={'dataset_sha256':hashlib.sha256(raw).hexdigest(),'dataset_version':dataset['version'],'split':split,
            'partial_run':limit is not None,'live_model_run':live,'provider':config['provider'] if live else None,
            'model':config['model'] if live else None,'rules':rules,'model_metrics':model,
            'paired_difference':{'entity_f1':model['f1']-rules['f1'],
                'clarification_accuracy':model['clarification_accuracy']-rules['clarification_accuracy']} if live else None,
            'limitations':['Same synthetic cases and gold fields for both parsers; shared templates limit generalization.',
                'No fallback parser hides model failures. A failed call cannot receive clarification credit.',
                'Single serial latency samples, not a production latency benchmark.',
                'Model metrics remain null unless explicitly run; do not claim superiority from offline rules results.'],
            'samples':results}
    if output:
        path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',choices=['dev','test'],default='dev');p.add_argument('--limit',type=int)
    p.add_argument('--live-model',action='store_true',help='Enable potentially billed model calls')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    if a.limit is not None and a.limit<1:p.error('--limit must be positive')
    run(a.split,a.live_model,a.limit,a.output)
