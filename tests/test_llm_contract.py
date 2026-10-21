from pydantic_ai.models.test import TestModel
from app.parser import extract


def test_pydantic_ai_typed_extraction_without_network(network, monkeypatch):
    import pydantic_ai.models.openai as openai
    model=TestModel(custom_output_args={"constraints":{"pallets":15},"ambiguities":[]})
    monkeypatch.setattr(openai,'OpenAIChatModel',lambda *args,**kwargs:model)
    monkeypatch.setenv('ROUTEMIND_MODEL','test-model')
    monkeypatch.setenv('ROUTEMIND_API_KEY','test-only-not-a-credential')
    fields, questions, mode=extract('15 pallets',network[0],{'optimization_goal':'fastest','max_budget_cents':400000})
    assert fields=={'pallets':15} and questions==[]
    assert mode=='pydantic-ai:test-model'
