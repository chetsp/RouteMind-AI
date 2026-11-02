import json
from pathlib import Path
import pytest
from evaluations.quality.run import entities, prf, validate_splits, run


def test_entity_f1_penalizes_wrong_values_and_extra_fields():
    actual=entities({'pallets':8,'required_capabilities':['fragile','secure']})
    gold=entities({'pallets':12,'required_capabilities':['fragile']})
    result=prf(len(actual&gold),len(actual-gold),len(gold-actual))
    assert result['tp']==1 and result['fp']==2 and result['fn']==1
    assert result['precision']==pytest.approx(1/3)
    assert result['recall']==.5 and result['f1']==.4


def test_frozen_groups_do_not_overlap():
    data=json.loads(Path('evaluations/quality/cases.json').read_text())
    validate_splits(data)
    assert len(data['nlp'])==64 and len(data['policies'])==50
    data['nlp'][0]['group']=next(r['group'] for r in data['nlp'] if r['split']=='test')
    with pytest.raises(AssertionError,match='leakage'): validate_splits(data)


def test_offline_evaluation_cannot_spend_on_a_configured_model(tmp_path,monkeypatch):
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash')
    monkeypatch.setenv('GEMINI_API_KEY','test-only-not-a-real-key')
    monkeypatch.setattr('app.policies.read_policies',lambda *a:pytest.fail('No hosted calls in offline evaluation'))
    monkeypatch.setattr('evaluations.quality.run.extract',lambda *a:pytest.fail('No hosted calls in offline evaluation'))
    target=tmp_path/'report.json'
    report=run(limit=1,output=target)
    assert report['partial_run'] and not report['live_model']
    assert report['policies']['citation_precision'] is None
    assert report['policies']['human_grounding_review'].startswith('not performed')
    assert target.exists()


def test_live_evaluation_requires_own_key(monkeypatch):
    monkeypatch.delenv('ROUTEMIND_MODEL',raising=False)
    with pytest.raises(RuntimeError,match='configured'): run(live=True,limit=1)
