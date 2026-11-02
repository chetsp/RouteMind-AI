import pytest
from app.policies import PolicyReading, Finding


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    from fastapi.testclient import TestClient
    from app.main import create_app
    with pytest.MonkeyPatch.context() as env:
        env.setenv("DATA_DIR", str(tmp_path_factory.mktemp("policy-tests")))
        env.setenv("EMBEDDING_BACKEND", "hash")
        env.delenv("ROUTEMIND_MODEL", raising=False)
        env.delenv("ROUTEMIND_PROVIDER", raising=False)
        with TestClient(create_app(os.getenv("TEST_DATABASE_URL"))) as c:
            yield c


def test_policy_retrieval_is_scoped_and_explicit(client):
    result = client.post('/api/v1/policies/questions', json={
        'question':'What handling is documented for delicate electronics?', 'carrier_ids':['C01']})
    assert result.status_code == 200
    data = result.json()
    assert data['mode'] == 'retrieval-only' and data['status'] == 'related_documents'
    assert data['warnings'] and not data['findings']
    assert data['evidence']
    assert all(e['carrier_id'] in [None,'C01'] for e in data['evidence'])
    assert all(e['document_type'] != 'planning_case' for e in data['evidence'])
    assert 'eligibility' in data['boundary']
    assert len(client.get('/api/v1/policies/carriers').json()) == 10
    assert client.get('/policies').status_code == 200


@pytest.mark.parametrize('body', [ {'question':'  '}, {'question':'a'*2001},
    {'question':'handling', 'carrier_ids':['unknown']},
    {'question':'handling', 'carrier_ids':['C01','C02','C03']} ])
def test_invalid_policy_questions(client, body):
    assert client.post('/api/v1/policies/questions',json=body).status_code == 422


def enable(monkeypatch):
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash')
    monkeypatch.setenv('GEMINI_API_KEY','test-only-not-a-real-key')


def test_verified_quotes_and_unanswered_parts(client, monkeypatch):
    enable(monkeypatch)
    def reading(question, evidence):
        e = next(e for e in evidence if e['carrier_id'] == 'C01')
        return PolicyReading(findings=[Finding(source_id=e['source_id'],quote=e['text'][:30])],
                             unanswered_questions=['What packaging is required?'])
    monkeypatch.setattr('app.policies.read_policies',reading)
    data=client.post('/api/v1/policies/questions',json={'question':'Fragile electronics handling and packaging?', 'carrier_ids':['C01']}).json()
    assert data['status']=='answered' and data['mode']=='model-assisted-extractive'
    assert data['unanswered_questions']==['What packaging is required?']
    f=data['findings'][0]
    assert f['quote']==next(e['text'] for e in data['evidence'] if e['source_id']==f['source_id'])


@pytest.mark.parametrize('kind',['invented_id','invented_quote','provider_failure'])
def test_unverifiable_or_failed_reading_falls_back(client,monkeypatch,kind):
    enable(monkeypatch)
    def reading(question,evidence):
        if kind=='provider_failure': raise RuntimeError('secret-key-must-not-leak')
        return PolicyReading(findings=[Finding(source_id='fake' if kind=='invented_id' else evidence[0]['source_id'],
            quote=evidence[0]['text'] if kind=='invented_id' else 'Guaranteed acceptance of every shipment')])
    monkeypatch.setattr('app.policies.read_policies',reading)
    response=client.post('/api/v1/policies/questions',json={'question':'What handling is described?'})
    data=response.json()
    assert data['status']=='related_documents' and not data['findings'] and data['warnings']
    assert 'secret-key-must-not-leak' not in response.text


def test_unknown_policy_is_not_a_negative_claim(client,monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr('app.policies.read_policies',lambda *args: PolicyReading(unanswered_questions=['Are refunds guaranteed?']))
    data=client.post('/api/v1/policies/questions',json={'question':'Are refunds guaranteed?'}).json()
    assert data['status']=='insufficient_evidence' and not data['findings']


@pytest.mark.parametrize('provider', ['gemini','openai'])
def test_actual_typed_agent_path(client,monkeypatch,provider):
    from pydantic_ai.models.test import TestModel
    import pydantic_ai.models.google as google
    import pydantic_ai.models.openai as openai
    monkeypatch.setenv('ROUTEMIND_PROVIDER',provider)
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash' if provider=='gemini' else 'gpt-4.1-mini')
    monkeypatch.setenv('GEMINI_API_KEY','test-only-not-a-real-key')
    monkeypatch.setenv('ROUTEMIND_API_KEY','test-only-not-a-real-key')
    model=TestModel(custom_output_args={'findings':[], 'unanswered_questions':['What temperature range is specified?']})
    monkeypatch.setattr(google,'GoogleModel',lambda *a,**k:model)
    monkeypatch.setattr(openai,'OpenAIChatModel',lambda *a,**k:model)
    data=client.post('/api/v1/policies/questions',json={'question':'What exact refrigerated temperature range is specified?'}).json()
    assert data['status']=='not_documented' and data['mode']=='model-assisted-extractive'


def test_comparison_includes_both_carriers(client):
    data=client.post('/api/v1/policies/questions',json={
        'question':'Compare handling for fragile electronics', 'carrier_ids':['C01','C04']}).json()
    assert {'C01','C04'} <= {e['carrier_id'] for e in data['evidence']}
    assert all(e['carrier_id'] in {None,'C01','C04'} for e in data['evidence'])


def test_policy_model_conflict_blocks_answers(client,monkeypatch):
    from app.policies import PolicyConflict
    enable(monkeypatch)
    def read(question,evidence):
        selected=[e for e in evidence if e['carrier_id']=='C01'][:2]
        return PolicyReading(conflicts=[PolicyConflict(passages=[Finding(source_id=e['source_id'],quote=e['text']) for e in selected])])
    monkeypatch.setattr('app.policies.read_policies',read)
    data=client.post('/api/v1/policies/questions',json={'question':'Fragile handling', 'carrier_ids':['C01']}).json()
    assert data['status']=='conflicting_evidence' and data['conflicts'] and not data['findings']


def test_policy_metadata_conflict_skips_model(client,monkeypatch):
    original=client.app.state.retriever.assess
    def conflicting(*args):
        result=original(*args)
        result.update(status='conflicting_evidence',conflicts=[{'source_ids':['profile-C01-1'],'reason':'reviewed_claim_disagrees_with_sql'}])
        return result
    monkeypatch.setattr(client.app.state.retriever,'assess',conflicting)
    monkeypatch.setattr('app.policies.read_policies',lambda *a:pytest.fail('Must not call a model for conflicting reviewed evidence'))
    data=client.post('/api/v1/policies/questions',json={'question':'fragile cargo'}).json()
    assert data['status']=='conflicting_evidence' and not data['findings']


def test_stored_effective_dates_exclude_expired_carrier_passages(client):
    from app.database import document_reviews
    ids=[f'profile-C01-{i}' for i in range(1,6)]
    db=client.app.state.db
    if any(r['source_id'] in ids for r in db.all(document_reviews)):
        pytest.skip('This fixture requires unreviewed source IDs in a dedicated test database')
    inserted=False
    try:
        with db.engine.begin() as conn:
            conn.execute(document_reviews.insert(),[{'source_id':i,'logical_id':i,
                'effective_until':'2000-01-01T00:00:00+00:00','claims_json':'{}'} for i in ids])
        inserted=True
        result=client.post('/api/v1/policies/questions',json={'question':'Fragile cargo handling', 'carrier_ids':['C01']}).json()
        assert not any(e['carrier_id']=='C01' for e in result['evidence'])
        assert set(ids) <= {e['source_id'] for e in result['evidence_assessment']['excluded'] if e['reason']=='expired'}
    finally:
        if inserted:
            with db.engine.begin() as conn:
                conn.execute(document_reviews.delete().where(document_reviews.c.source_id.in_(ids)))
