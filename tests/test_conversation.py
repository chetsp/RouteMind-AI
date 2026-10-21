from copy import deepcopy
import json
import os
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.language import normalize_language
from app.optimizer import verify_plan
from app.schemas import Constraints


@pytest.fixture
def nlp(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EMBEDDING_BACKEND','hash')
    monkeypatch.delenv('ROUTEMIND_MODEL',raising=False)
    with TestClient(create_app(os.getenv('TEST_DATABASE_URL'))) as c: yield c


def plan(c,message='Ship a dozen pallets of delicate electronics from the Bay Area to Austin under four grand.'):
    state=c.post('/api/v1/plans',json={'message':message}).json()
    assert state['status']=='completed',state
    return state


def revise(c,state,message='',constraints=None):
    body={'message':message}
    if constraints is not None: body['constraints']=constraints
    result=c.post('/api/v1/plans/'+state['request_id']+'/revise',json=body)
    assert result.status_code==200,result.text
    return result.json()


def test_spelled_numbers(nlp):
    state=plan(nlp)
    assert state['constraints']['pallets']==12
    assert state['constraints']['max_budget_cents']==400000
    assert state['recommended_plan']['total_cost_cents']==198000
    assert '12 pallets' in state['interpretation']['normalized_message']
    assert state['constraints']['required_capabilities']==['fragile']
    assert normalize_language('twenty-five pallets under five hundred dollars')=='25 pallets under $500'


def test_revision_preserves_parent_and_unchanged_fields(nlp):
    parent=plan(nlp)
    original=deepcopy(parent)
    faster=revise(nlp,parent,'Make it faster, but keep the budget.')
    assert faster['status']=='completed'
    assert faster['parent_request_id']==parent['request_id']
    assert faster['request_id']!=parent['request_id']
    assert faster['constraints']['max_budget_cents']==400000
    assert faster['constraints']['required_capabilities']==['fragile']
    assert faster['recommended_plan']['total_cost_cents']==328000
    assert faster['comparison']['cost_delta_cents']==130000
    assert faster['comparison']['arrival_delta_minutes']==-480
    assert nlp.get('/api/v1/plans/'+parent['request_id']).json()==original
    smaller=revise(nlp,faster,'What if we ship only eight pallets?')
    assert smaller['status']=='completed' and smaller['constraints']['pallets']==8
    assert smaller['constraints']['optimization_goal']=='fastest'
    assert set(smaller['interpretation']['changes'])=={'pallets'}


def test_relative_earlier_limit_and_executable_suggestion(nlp):
    parent=plan(nlp)
    limited=revise(nlp,parent,'Can we arrive earlier without spending more than five hundred dollars extra?')
    assert limited['status']=='no_route',limited
    assert limited['constraints']['max_budget_cents']==248000
    assert limited['suggestions']
    budget=next(s for s in limited['suggestions'] if s['kind']=='budget')
    assert budget['changes']=={'max_budget_cents':328000}
    proof=Constraints.model_validate({**limited['constraints'],**budget['changes']})
    assert verify_plan(budget['plan'],nlp.app.state.db.network(),proof)
    applied=revise(nlp,limited,constraints=budget['changes'])
    assert applied['status']=='completed'
    assert applied['recommended_plan']['total_cost_cents']==328000
    # Parent constraints remain untouched until the user applies a suggestion.
    assert nlp.get('/api/v1/plans/'+limited['request_id']).json()['constraints']['max_budget_cents']==248000


def test_relative_cap_never_silently_raises_hard_budget(nlp):
    parent=plan(nlp)
    child=revise(nlp,parent,'Make it faster with up to $5,000 extra.')
    assert child['constraints']['max_budget_cents']==400000
    assert child['status']=='completed'


def test_budget_edit_and_explicit_clear(nlp):
    parent=plan(nlp)
    child=revise(nlp,parent,'Reduce the budget by five hundred dollars')
    assert child['constraints']['max_budget_cents']==350000
    assert child['status']=='completed'
    cleared=revise(nlp,child,'Remove the budget limit')
    assert cleared['constraints']['max_budget_cents'] is None
    assert cleared['status']=='completed'


def test_unresolvable_relative_and_unrecognized_revision(nlp):
    state=nlp.post('/api/v1/plans',json={'message':'15 pallets Fremont to Austin with up to $500 extra'}).json()
    assert state['status']=='needs_clarification'
    assert any('previous plan' in q for q in state['questions'])
    parent=plan(nlp)
    child=revise(nlp,parent,'Thanks!')
    assert child['status']=='needs_clarification'
    clarified=nlp.post('/api/v1/plans/'+child['request_id']+'/clarify',json={'message':'eight pallets'}).json()
    assert clarified['status']=='completed'


def test_soft_direct_preference(nlp):
    parent=plan(nlp,'15 pallets of fragile cargo Fremont to Austin under $4,000; prefer direct but one transfer is okay if it saves at least $1,500')
    assert parent['constraints']['max_stops']==1
    assert parent['constraints']['prefer_direct'] is True
    assert parent['recommended_plan']['leg_count']==1
    assert parent['recommended_plan']['total_cost_cents']==340000
    child=revise(nlp,parent,'Prefer direct but one transfer is okay if it saves at least $500')
    assert child['recommended_plan']['leg_count']==2
    assert child['recommended_plan']['total_cost_cents']==210000


def test_cargo_review_is_not_pharmaceutical_certification(nlp):
    state=nlp.post('/api/v1/plans',json={'message':'15 pallets of temperature-sensitive pharmaceuticals from Fremont to Austin'}).json()
    assert state['status']=='needs_clarification'
    assert state['evidence']
    state=nlp.post('/api/v1/plans/'+state['request_id']+'/clarify',json={'constraints':{'required_capabilities':['refrigerated']}}).json()
    assert state['status']=='completed'
    assert state['recommended_plan']['plan_id']=='plan-S008-S009'
    assert any('not modeled' in a for a in state['interpretation']['assumptions'])


def test_suggestions_never_relax_safety_or_multiple_constraints(nlp):
    state=nlp.post('/api/v1/plans',json={'message':'15 pallets of hazardous material Fremont to Austin under $100'}).json()
    assert state['status']=='no_route' and state['suggestions']==[]
    state=nlp.post('/api/v1/plans',json={'message':'15 pallets fragile Fremont to Austin under $500'}).json()
    assert state['status']=='no_route'
    suggestion=state['suggestions'][0]
    assert suggestion['kind']=='budget' and suggestion['changes']=={'max_budget_cents':210000}


def test_structured_budget_override_is_final(nlp):
    parent=plan(nlp)
    child=revise(nlp,parent,'Make it faster with up to $1500 extra',{'max_budget_cents':200000})
    assert child['constraints']['max_budget_cents']==200000
    assert child['recommended_plan']['total_cost_cents']==198000


def test_capabilities_are_additive_until_explicit_removal(nlp):
    parent=plan(nlp)
    secure=revise(nlp,parent,'Use secure handling as well')
    assert secure['constraints']['required_capabilities']==['fragile','secure']
    removed=revise(nlp,secure,'Not fragile; use secure handling only')
    assert removed['constraints']['required_capabilities']==['secure']


@pytest.mark.parametrize('text,expected',[('two dozen pallets',24),('half a dozen pallets',6),('twenty-five pallets',25)])
def test_compound_quantities(nlp,text,expected):
    state=nlp.post('/api/v1/plans',json={'message':text+' Fremont to Austin'}).json()
    assert state['constraints']['pallets']==expected


def test_unknown_budget_and_mixed_dates_require_clarification(nlp):
    state=nlp.post('/api/v1/plans',json={'message':'15 pallets Fremont to Austin under five million'}).json()
    assert state['status']=='needs_clarification'
    state=nlp.post('/api/v1/plans',json={'message':'15 pallets Fremont to Austin ready 2026-11-01T06:00:00Z arrive by Thursday'}).json()
    assert state['status']=='needs_clarification'


def test_explanation_uses_selected_carrier_profile(nlp):
    parent=plan(nlp)
    child=revise(nlp,parent,'Make it faster but keep the budget')
    profile=next(e for e in child['evidence'] if e['carrier_id']=='C04')
    assert profile['source_id'] in child['explanation']
