import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from pydantic_ai.models.test import TestModel
from app.parser import extract, llm_configuration


@pytest.mark.parametrize('provider',['gemini','google',''])
def test_gemini_typed_extraction(provider,network,monkeypatch):
    import pydantic_ai.models.google as google
    captured=[]
    model=TestModel(custom_output_args={'constraints':{'pallets':8,'max_extra_cost_cents':50000},'ambiguities':[]})
    def select(name,**kwargs):
        captured.append(name)
        return model
    monkeypatch.setattr(google,'GoogleModel',select)
    monkeypatch.setenv('ROUTEMIND_PROVIDER',provider)
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash')
    monkeypatch.setenv('GEMINI_API_KEY','test-only-not-a-real-key')
    monkeypatch.delenv('ROUTEMIND_API_KEY',raising=False)
    fields,questions,mode=extract('Only eight pallets, with up to $500 extra',network[0],{'max_budget_cents':400000},{'total_cost_cents':210000})
    assert fields=={'pallets':8,'max_extra_cost_cents':50000} and questions==[]
    assert mode=='pydantic-ai:gemini:gemini-2.5-flash'
    assert captured==['gemini-2.5-flash']
    assert llm_configuration()['configured'] is True


def test_gemini_requires_its_own_key(network,monkeypatch):
    monkeypatch.setenv('ROUTEMIND_PROVIDER','gemini')
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash')
    monkeypatch.setenv('ROUTEMIND_API_KEY','test-openai-key-is-not-a-gemini-key')
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    assert llm_configuration()['configured'] is False
    with pytest.raises(ValueError,match='GEMINI_API_KEY'):
        extract('15 pallets',network[0])


def test_invalid_provider_does_not_send_credentials(network,monkeypatch):
    monkeypatch.setenv('ROUTEMIND_PROVIDER','unknown')
    monkeypatch.setenv('ROUTEMIND_MODEL','some-model')
    assert llm_configuration()['configured'] is False
    with pytest.raises(ValueError,match='ROUTEMIND_PROVIDER'):
        extract('15 pallets',network[0])


@pytest.fixture
def gemini_env(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EMBEDDING_BACKEND','hash')
    monkeypatch.setenv('ROUTEMIND_PROVIDER','gemini')
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash')
    return monkeypatch


def test_gemini_api_uses_typed_result_and_redacts_key(gemini_env):
    import pydantic_ai.models.google as google
    gemini_env.setenv('GEMINI_API_KEY','test-only-not-a-real-key')
    model=TestModel(custom_output_args={'constraints':{'origin':'FRE','destination':'AUS','pallets':15,'required_capabilities':['fragile']},'ambiguities':[]})
    gemini_env.setattr(google,'GoogleModel',lambda *a,**k:model)
    with TestClient(create_app()) as c:
        health=c.get('/health')
        assert health.json()['llm_provider']=='gemini' and health.json()['llm_configured'] is True
        assert 'test-only-not-a-real-key' not in health.text
        result=c.post('/api/v1/plans',json={'message':'15 pallets of fragile goods Fremont to Austin'})
        state=result.json()
        assert state['status']=='completed' and state['recommended_plan']['total_cost_cents']==210000
        assert state['parser_mode']=='pydantic-ai:gemini:gemini-2.5-flash'
        assert 'test-only-not-a-real-key' not in result.text


def test_missing_gemini_key_falls_back_explicitly(gemini_env):
    gemini_env.delenv('GEMINI_API_KEY',raising=False)
    with TestClient(create_app()) as c:
        assert c.get('/health').json()['llm_configured'] is False
        state=c.post('/api/v1/plans',json={'message':'15 pallets Fremont to Austin'}).json()
        assert state['status']=='completed'
        assert 'LLM unavailable' in state['parser_mode'] and state['warnings']
