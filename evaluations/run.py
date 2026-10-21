"""Small synthetic regression benchmarks, not a production accuracy claim."""
import json
import math
import os
import statistics
import time
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.optimizer import verify_plan
from app.parser import demo_extract
from app.schemas import Constraints

ROOT = Path(__file__).parent


def run():
    if os.getenv("ROUTEMIND_MODEL"):
        raise RuntimeError("This regression benchmark requires ROUTEMIND_MODEL unset; it never makes paid LLM calls.")
    report = {"dataset": "synthetic handcrafted/template regression fixtures v1", "limitations": [
        "Not a held-out human-labeled dataset. Related templates and near-duplicate profiles make retrieval scores optimistic.",
        "Demo parser results do not measure an LLM. Reranker is token coverage, not a cross-encoder.",
        "No Ragas/human grounding evaluation or production accuracy claim."
    ]}
    retrieval = json.loads((ROOT/'retrieval_queries.json').read_text())
    parsing = json.loads((ROOT/'planning_requests.json').read_text())
    with TestClient(create_app()) as client:
        db, r = client.app.state.db, client.app.state.retriever
        report['embedding_model'] = r.model_version
        report['retrieval'] = {}
        for mode in ['dense','bm25','hybrid','reranked']:
            recalls, reciprocal, ndcg = [], [], []
            for case in retrieval:
                hits = [e['source_id'] for e in r.query(case['query'],k=5,mode=mode)]
                gold=set(case['gold_source_ids'])
                recalls.append(len(gold & set(hits))/len(gold))
                reciprocal.append(next((1/(i+1) for i,x in enumerate(hits) if x in gold),0))
                dcg=sum(1/math.log2(i+2) for i,x in enumerate(hits) if x in gold)
                ideal=sum(1/math.log2(i+2) for i in range(min(5,len(gold))))
                ndcg.append(dcg/ideal)
            report['retrieval'][mode]={'queries':len(retrieval),'recall_at_5':round(statistics.mean(recalls),4),
                'mrr':round(statistics.mean(reciprocal),4),'ndcg_at_5':round(statistics.mean(ndcg),4)}
        hs,_,_=db.network()
        correct=0; routes_verified=0; completed=0; matched_status=0; times=[]
        for case in parsing:
            fields,questions=demo_extract(case['message'],hs)
            if all(fields.get(k)==v for k,v in case['expected_fields'].items()): correct+=1
            state={'request_id':str(uuid.uuid4()),'message':case['message'],'messages':[case['message']],
                'overrides':{},'constraints':{},'plans':[],'evidence':[],'warnings':[],'trace':[],'data_type':'synthetic'}
            start=time.perf_counter()
            result=client.app.state.workflow.invoke(state,config={"configurable":{"thread_id":state['request_id']}})
            times.append((time.perf_counter()-start)*1000)
            matched_status+=result['status']==case['expected_status']
            if result['status']=='completed':
                completed+=1
                for p in result['plans']:
                    verify_plan(p,db.network(),Constraints.model_validate(result['constraints']))
                    routes_verified+=1
        ordered=sorted(times)
        report['planning']={'requests':len(parsing),'parser_expected_field_matches':correct,
            'expected_status_matches':matched_status,'completed_requests':completed,'returned_routes_independently_verified':routes_verified,
            'workflow_p50_ms':round(statistics.median(times),2),'workflow_p95_ms':round(ordered[math.ceil(.95*len(times))-1],2)}
        # Actual HTTP samples are separate from direct workflow evaluation.
        http_times=[]
        for _ in range(12):
            start=time.perf_counter()
            response=client.post('/api/v1/plans',json={'message':'15 pallets from Fremont to Austin cheapest under $4,000'})
            assert response.status_code==200 and response.json()['status']=='completed'
            http_times.append((time.perf_counter()-start)*1000)
        report['http']={'samples':12,'p50_ms':round(statistics.median(http_times),2),'p95_ms':round(sorted(http_times)[-1],2),
            'transport':'in-process ASGI TestClient; includes SQL persistence, excludes real network'}
    (ROOT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': run()
