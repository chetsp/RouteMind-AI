import os
from fastapi.testclient import TestClient
from app.main import create_app


def test_health_and_ui(client):
    health=client.get('/health').json()
    assert health['status']=='ok' and health['evidence_documents']==58
    assert client.get('/').status_code==200
    assert 'RouteMind' in client.get('/').text
    assert client.get('/static/app.js').status_code==200
    assert len(client.get('/api/v1/hubs').json())==18


def test_end_to_end_with_rag(client):
    state=client.post('/api/v1/plans',json={'message':'Ship 15 pallets of fragile electronics from Fremont to Austin under $4,000; cheapest.'}).json()
    assert state['status']=='completed'
    assert state['recommended_plan']['total_cost_cents']==210000
    assert state['data_type']=='synthetic'
    assert state['evidence'] and all(e['source_id'] for e in state['evidence'])
    assert [t['node'] for t in state['trace']]==['parse','validate','retrieve','optimize','verify','explain']
    assert client.get('/api/v1/plans/'+state['request_id']).json()==state
    assert len(client.get('/api/v1/plans/'+state['request_id']+'/alternatives').json()['plans'])==3


def test_clarification_retains_constraints(client):
    state=client.post('/api/v1/plans',json={'message':'Fastest from Fremont to Austin under $4,000 with 97% on-time reliability.'}).json()
    assert state['status']=='needs_clarification'
    resumed=client.post('/api/v1/plans/'+state['request_id']+'/clarify',json={'message':'15 pallets'}).json()
    assert resumed['status']=='completed'
    assert resumed['constraints']['max_budget_cents']==400000
    assert resumed['constraints']['optimization_goal']=='fastest'
    assert resumed['constraints']['min_on_time_rate']==.97
    assert resumed['recommended_plan']['leg_count']==1
    assert client.post('/api/v1/plans/'+state['request_id']+'/clarify',json={'message':'20 pallets'}).status_code==409


def test_restart_resume(client):
    state=client.post('/api/v1/plans',json={'message':'From Fremont to Austin under $4,000'}).json()
    # Create a fresh app/graph, reading the same on-disk SQL and Chroma stores.
    with TestClient(create_app(os.getenv('TEST_DATABASE_URL'))) as restarted:
        assert restarted.get('/api/v1/plans/'+state['request_id']).json()['status']=='needs_clarification'
        checkpoint=restarted.app.state.workflow.get_state({'configurable':{'thread_id':state['request_id']}})
        assert checkpoint.values['status']=='needs_clarification'
        resumed=restarted.post('/api/v1/plans/'+state['request_id']+'/clarify',json={'message':'15 pallets'}).json()
        assert resumed['status']=='completed'
        assert resumed['constraints']['max_budget_cents']==400000


def test_structured_override_and_no_route(client):
    state=client.post('/api/v1/plans',json={'message':'Ship 15 pallets from Fremont to Austin','constraints':{'max_budget_cents':50000}}).json()
    assert state['status']=='no_route' and state['rejection_counts']['budget']>0
    assert state['recommended_plan'] is None


def test_vague_date_and_reliability(client):
    state=client.post('/api/v1/plans',json={'message':'Ship 15 pallets from Fremont to Austin tomorrow on a reliable carrier'}).json()
    assert state['status']=='needs_clarification'
    assert len(state['questions'])==2
    # Answering just one ambiguity must not silently clear the other.
    state=client.post('/api/v1/plans/'+state['request_id']+'/clarify',json={'constraints':{'min_on_time_rate':.97}}).json()
    assert state['status']=='needs_clarification'
    state=client.post('/api/v1/plans/'+state['request_id']+'/clarify',json={'constraints':{'ready_at':'2026-11-01T06:00:00Z'}}).json()
    assert state['status']=='completed'


def test_unknown_hubs_and_conflicts(client):
    a=client.post('/api/v1/plans',json={'message':'15 pallets from Atlantis to Austin'}).json()
    assert a['status']=='needs_clarification' and a['constraints']['origin'] is None
    b=client.post('/api/v1/plans',json={'message':'15 pallets from Fremont to Austin; cheapest and fastest'}).json()
    assert b['status']=='needs_clarification'
    fixed=client.post('/api/v1/plans/'+b['request_id']+'/clarify',json={'constraints':{'optimization_goal':'fastest'}}).json()
    assert fixed['status']=='completed'


def test_malformed_inputs(client):
    for constraints in [{'pallets':0},{'max_stops':3},{'ready_at':'2026-11-01T06:00:00'},{'required_capabilities':['magic']}]:
        assert client.post('/api/v1/plans',json={'message':'test','constraints':constraints}).status_code==422
    assert client.post('/api/v1/plans',content=b'x'*17000).status_code==413
    assert client.get('/api/v1/plans/missing').status_code==404


def test_model_failure_has_explicit_fallback(client, monkeypatch):
    import app.workflow as workflow
    def fail(*args): raise TimeoutError('model unavailable')
    monkeypatch.setattr(workflow,'extract',fail)
    state=client.post('/api/v1/plans',json={'message':'15 pallets from Fremont to Austin'}).json()
    assert state['status']=='completed' and state['warnings']
    assert 'unavailable' in state['parser_mode']


def test_retrieval_failure_does_not_fabricate_evidence(client, monkeypatch):
    def fail(*args,**kwargs): raise TimeoutError('index unavailable')
    monkeypatch.setattr(client.app.state.retriever,'query',fail)
    state=client.post('/api/v1/plans',json={'message':'15 pallets of fragile goods from Fremont to Austin'}).json()
    assert state['status']=='completed' and state['evidence']==[] and state['warnings']
    assert state['recommended_plan']['total_cost_cents']==210000
