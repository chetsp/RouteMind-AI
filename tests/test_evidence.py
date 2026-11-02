from datetime import datetime, timezone
import json
import pytest
from app.evidence import assess_evidence
from app.policies import PolicyReading, PolicyConflict, Finding

NOW = datetime(2026,11,1,tzinfo=timezone.utc)


def passage(ident='a', version=1, text='Fragile cargo uses padded loading.', carrier='C01'):
    return dict(source_id=ident, version=version, text=text, carrier_id=carrier,
                document_type='carrier_profile', provenance='synthetic')


def test_unrelated_names_and_hash_collisions_do_not_pass():
    e=passage(text='Cobalt Secure Ground: refrigerated handling.')
    e.update(embedding_backend='hash', dense_similarity=.99)
    r=assess_evidence('Does Cobalt Secure Ground refund cancellations?', [e], carrier_names=['Cobalt Secure Ground'])
    assert r['status']=='insufficient_evidence' and not r['evidence']
    assert r['excluded'][0]['reason']=='below_relevance_gate'


def test_learned_paraphrase_gate_and_unknown_freshness():
    e=passage(text='Padded cargo loading.',carrier='C01')
    e.update(embedding_backend='minilm',dense_similarity=.7)
    r=assess_evidence('Protect breakable goods', [e])
    assert r['status']=='sufficient_evidence'
    assert r['evidence'][0]['relevance_basis']=='semantic_similarity'
    assert r['freshness_unknown']==['a']


def test_versions_expiration_future_and_no_fallback_to_expired_revision():
    docs=[passage('old'),passage('new',2),passage('future',3)]
    reviews={'old':{'logical_id':'same'},'new':{'logical_id':'same','effective_until':'2026-10-30T00:00:00+00:00'},
             'future':{'logical_id':'same','effective_from':'2026-12-01T00:00:00+00:00'}}
    result=assess_evidence('fragile handling',docs,reviews=reviews,as_of=NOW)
    assert result['status']=='insufficient_evidence'
    assert {e['reason'] for e in result['excluded']}=={'superseded','expired','not_yet_effective'}
    reviews['new']['effective_until']='2026-11-30T00:00:00+00:00'
    result=assess_evidence('fragile handling',docs,reviews=reviews,as_of=NOW)
    assert [e['source_id'] for e in result['evidence']]==['new']


def test_different_sections_and_carriers_are_not_versions_of_each_other():
    docs=[passage('a',1),passage('b',8),passage('c',2,carrier='C02')]
    result=assess_evidence('fragile',docs,reviews={'a':{'logical_id':'first'},'c':{'logical_id':'first'}})
    assert len(result['evidence'])==3


def test_reviewed_claim_conflicts_and_sql_disagreement():
    docs=[passage('a'),passage('b',text='Fragile cargo not accepted.')]
    reviews={'a':{'claims_json':json.dumps({'fragile':True})},'b':{'claims_json':json.dumps({'fragile':False})}}
    result=assess_evidence('fragile',docs,reviews=reviews)
    assert result['status']=='conflicting_evidence'
    assert result['conflicts'][0]['source_ids']==['a','b']
    result=assess_evidence('fragile',[docs[0]],reviews=reviews,capabilities={'C01':set()})
    assert result['conflicts'][0]['reason']=='reviewed_claim_disagrees_with_sql'
    # Unknown/absent annotations are not interpreted as a negative policy.
    assert assess_evidence('fragile',docs)['conflicts']==[]


def test_old_install_gets_additive_review_table(client):
    from app.database import document_reviews
    assert client.app.state.db.all(document_reviews)==[]


def test_planning_survives_insufficient_evidence(client,monkeypatch):
    monkeypatch.setattr(client.app.state.retriever,'query',lambda *a,**kw:[])
    data=client.post('/api/v1/plans',json={'message':'15 pallets of fragile electronics Fremont to Austin under $4000'}).json()
    assert data['status']=='completed' and data['recommended_plan']['total_cost_cents']==210000
    assert data['evidence_assessment']['status']=='insufficient_evidence'
    assert not data['evidence']


def test_empty_corpus_starts_and_abstains(client,tmp_path,monkeypatch):
    from app.database import documents
    from app.rag import Retriever
    db=client.app.state.db
    original=db.all
    monkeypatch.setattr(db,'all',lambda table: [] if table is documents else original(table))
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EMBEDDING_BACKEND','hash')
    r=Retriever(db)
    assert r.collection.count()==0
    assert r.query('fragile cargo')==[]
    assert r.assess('fragile cargo',[])['status']=='insufficient_evidence'
