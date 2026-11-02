"""Prepare or explicitly run Ragas judging on saved live policy responses."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

METRICS=['faithfulness','context_precision_without_reference','answer_relevance']


def prepare(report):
    rows=[];excluded=[]
    for sample in report.get('policy_samples',[]):
        result=sample['result'];reason=None
        if not report.get('live_model'): reason='not_a_live_model_report'
        elif result.get('status')!='answered' or result.get('mode')!='model-assisted-extractive':reason='abstention_or_retrieval_only_not_scored_as_an_answer'
        elif not result.get('findings'):reason='no_answer_text'
        if reason:
            excluded.append({'id':sample['id'],'reason':reason});continue
        sources={e['source_id']:e['text'] for e in result['evidence']}
        findings=result['findings']
        if any(f['source_id'] not in sources or f['quote'] not in sources[f['source_id']] for f in findings):
            excluded.append({'id':sample['id'],'reason':'unverifiable_saved_citation'});continue
        # Judge the source paragraphs actually displayed to the user, not an invented answer.
        response='\n\n'.join(f['quote'] for f in findings)
        rows.append({'id':sample['id'],'user_input':sample['question'],
                     'response':response,'retrieved_contexts':list(sources.values())})
    return rows,excluded


def clean(value):
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,list):return [clean(v) for v in value]
    return value


def judge(rows,provider,model):
    """Ragas 0.2.15 adapter; no default keys, judges or embedding calls."""
    if not model:raise ValueError('Specify a judge model explicitly')
    key_name='GEMINI_API_KEY' if provider=='gemini' else 'ROUTEMIND_API_KEY'
    if not os.getenv(key_name):raise ValueError(f'Set {key_name} for the selected judge')
    os.environ['RAGAS_DO_NOT_TRACK']='true'
    try:
        from importlib.metadata import version
        if version('ragas') != '0.2.15':
            raise RuntimeError('Use the pinned Ragas 0.2.15 judge environment')
        from ragas import evaluate, EvaluationDataset
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference, AspectCritic
        from ragas.run_config import RunConfig
        if provider=='gemini':
            from langchain_google_genai import ChatGoogleGenerativeAI
            client=ChatGoogleGenerativeAI(model=model,google_api_key=os.environ[key_name],temperature=0,
                                         max_retries=1,timeout=45,max_output_tokens=2048)
        else:
            from langchain_openai import ChatOpenAI
            client=ChatOpenAI(model=model,api_key=os.environ[key_name],temperature=0,max_retries=1,timeout=45,max_tokens=2048)
    except ImportError as exc:
        raise RuntimeError('Install evaluations/quality/requirements-ragas.txt in a separate judge environment') from exc
    llm=LangchainLLMWrapper(client)
    metrics=[Faithfulness(llm=llm),LLMContextPrecisionWithoutReference(llm=llm),
             AspectCritic(name='answer_relevance',definition='Does the response address the user question using applicable information, without merely mentioning the same topic?',llm=llm,strictness=1)]
    dataset=EvaluationDataset.from_list([{k:v for k,v in row.items() if k!='id'} for row in rows])
    evaluated=evaluate(dataset=dataset,metrics=metrics,llm=llm,
        run_config=RunConfig(timeout=60,max_retries=1,max_workers=1),raise_exceptions=False,show_progress=False)
    scores=evaluated.to_pandas().to_dict(orient='records')
    if len(scores)!=len(rows):raise RuntimeError('Judge result count does not match the input')
    return [{'id':row['id'],**{label:clean(score.get(metric.name)) for label,metric in zip(METRICS,metrics)}} for row,score in zip(rows,scores)]


def run(input_file,output,allow_paid=False,provider=None,model=None,limit=10):
    raw=Path(input_file).read_bytes();report=json.loads(raw)
    rows,excluded=prepare(report)
    if limit<1:raise ValueError('limit must be positive')
    selected=rows[:limit]
    result={'input_sha256':hashlib.sha256(raw).hexdigest(),'dataset_sha256':report.get('dataset_sha256'),
        'split':report.get('split'),'source_model':report.get('model'),'source_provider':report.get('provider'),
        'judge_provider':provider if allow_paid else None,'judge_model':model if allow_paid else None,
        'status':'not_run','required_ragas_version':'0.2.15','eligible_answers':len(rows),'selected_answers':len(selected),
        'excluded':excluded,'not_selected_due_to_limit':[r['id'] for r in rows[limit:]],'scores':None,
        'aggregate':None,'samples':selected,
        'limitations':['Judge scores are not human validation. Use a different model family where feasible to limit self-judging bias.',
            'Faithfulness can be near-perfect by construction for verbatim quotations; relevance and completeness still need human review.',
            'No reference-answer recall or correctness is claimed. Abstentions are excluded, not assigned perfect scores.',
            'answer_relevance is a binary AspectCritic judgement, not the embedding-based Ragas answer relevancy metric.',
            'Context precision is judged relative to the displayed answer, not complete policy coverage.',
            'This evaluation sends questions, passages and answers to the explicitly selected hosted judge.']}
    if allow_paid:
        if provider not in {'gemini','openai'} or not model:raise ValueError('Paid judging requires explicit --judge-provider and --judge-model')
        if selected:
            scores=judge(selected,provider,model)
            result.update(scores=scores,status='completed')
            result['aggregate']={}
            for metric in METRICS:
                valid=[s[metric] for s in scores if s[metric] is not None]
                result['aggregate'][metric]={'mean':sum(valid)/len(valid) if valid else None,'scored':len(valid),'failed_or_missing':len(scores)-len(valid)}
            if any(s[m] is None for s in scores for m in METRICS):result['status']='completed_with_missing_scores'
        else:result['status']='no_eligible_live_answers'
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(result),indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'samples','excluded'}},indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    p.add_argument('--limit',type=int,default=10)
    p.add_argument('--allow-paid-judge',action='store_true')
    p.add_argument('--judge-provider',choices=['gemini','openai']);p.add_argument('--judge-model')
    a=p.parse_args();run(a.input,a.output,a.allow_paid_judge,a.judge_provider,a.judge_model,a.limit)
