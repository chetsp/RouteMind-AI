"""Exercise the pinned real Ragas API with deterministic fake chat; no hosted calls.

Run in the separate requirements-ragas.txt environment. Fixture scores are not
project answer-quality results and are deliberately not written to reports.
"""
import json
import os
from unittest.mock import patch
from langchain_core.language_models.fake_chat_models import SimpleChatModel
from evaluations.quality.ragas_review import judge, METRICS


class FixtureChat(SimpleChatModel):
    @property
    def _llm_type(self):return 'routemind-offline-fixture'

    def _call(self,messages,stop=None,run_manager=None,**kwargs):
        prompt='\n'.join(str(m.content) for m in messages)
        if 'Break down each sentence' in prompt:return json.dumps({'statements':['The carrier uses padded loading.']})
        if 'judge the faithfulness of a series' in prompt:
            return json.dumps({'statements':[{'statement':'The carrier uses padded loading.','reason':'Stated in the fixture.','verdict':1}]})
        return json.dumps({'reason':'Deterministic adapter fixture, not a live quality judgement.','verdict':1})


rows=[{'id':'adapter-fixture','user_input':'What handling is described?',
       'response':'The carrier uses padded loading.',
       'retrieved_contexts':['The carrier uses padded loading.']}]
# Test both provider constructors. Every generated response comes from FixtureChat.
for provider,module,key in [('openai','langchain_openai.ChatOpenAI','ROUTEMIND_API_KEY'),
                            ('gemini','langchain_google_genai.ChatGoogleGenerativeAI','GEMINI_API_KEY')]:
    with patch.dict(os.environ,{key:'test-only-not-a-real-key','RAGAS_DO_NOT_TRACK':'true'}),patch(module,return_value=FixtureChat()):
        scores=judge(rows,provider,'adapter-fixture')
    assert len(scores)==1 and scores[0]['id']=='adapter-fixture'
    assert all(scores[0][metric] is not None for metric in METRICS),scores
print('Pinned Ragas adapter, all three metric columns, both provider wrappers: passed with fixture chat only.')
