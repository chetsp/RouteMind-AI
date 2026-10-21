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


def test_llm_receives_reference_context_and_typed_operations(network,monkeypatch):
    import json
    import pydantic_ai.models.openai as openai
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    captured=[]
    def respond(messages,info):
        captured.extend(p.content for m in messages for p in m.parts if getattr(p,'part_kind',None)=='user-prompt')
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'constraints':{'max_extra_cost_cents':50000,'arrive_earlier':True},'ambiguities':[]})])
    monkeypatch.setattr(openai,'OpenAIChatModel',lambda *a,**k:FunctionModel(respond))
    monkeypatch.setenv('ROUTEMIND_MODEL','test-context')
    monkeypatch.setenv('ROUTEMIND_API_KEY','test-only-not-a-credential')
    previous={'origin':'FRE','destination':'AUS','pallets':12,'max_budget_cents':400000}
    baseline={'total_cost_cents':198000,'arrival_at':'2026-11-02T22:00:00+00:00'}
    fields,questions,_=extract('Earlier, at most $500 extra',network[0],previous,baseline)
    prompt=json.loads(captured[-1])
    assert prompt['previous_constraints']==previous and prompt['previous_verified_plan']==baseline
    assert fields=={'max_extra_cost_cents':50000,'arrive_earlier':True} and not questions
