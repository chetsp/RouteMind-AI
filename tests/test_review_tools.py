from copy import deepcopy
import csv
import json
from pathlib import Path
import pytest
from evaluations.quality import compare_parsers, human_review, ragas_review

ROOT=Path('evaluations/quality')


@pytest.fixture
def report():return json.loads((ROOT/'results-dev-minilm-offline.json').read_text())


@pytest.fixture
def live_report(report):
    report=deepcopy(report);report.update(live_model=True,model='simulated-test-model',provider='gemini')
    sample=report['policy_samples'][0];e=sample['result']['evidence'][0]
    sample['result'].update(status='answered',mode='model-assisted-extractive',findings=[{'source_id':e['source_id'],'quote':e['text']}])
    return report


def test_parser_comparison_offline_never_calls_model(tmp_path,monkeypatch):
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash');monkeypatch.setenv('GEMINI_API_KEY','test-only')
    monkeypatch.setattr(compare_parsers,'extract',lambda *a:pytest.fail('Offline means no model calls'))
    result=compare_parsers.run(limit=2,output=tmp_path/'comparison.json')
    assert result['rules']['cases']==2 and result['model_metrics'] is None and result['paired_difference'] is None
    assert all(s['model'] is None for s in result['samples'])


def test_parser_comparison_is_paired_without_fallback(tmp_path,monkeypatch):
    monkeypatch.setenv('ROUTEMIND_MODEL','gemini-2.5-flash');monkeypatch.setenv('GEMINI_API_KEY','test-only')
    called=[]
    def unavailable(message,*args):called.append(message);raise TimeoutError('must-not-leak')
    monkeypatch.setattr(compare_parsers,'extract',unavailable)
    result=compare_parsers.run(live=True,limit=3,output=tmp_path/'paired.json')
    assert called==[s['message'] for s in result['samples']]
    assert result['model_metrics']['failures']==3
    assert result['model_metrics']['f1']==0 and result['model_metrics']['clarification_accuracy']==0
    assert 'must-not-leak' not in json.dumps(result)


def test_parser_live_requires_credentials(monkeypatch):
    monkeypatch.delenv('ROUTEMIND_MODEL',raising=False)
    with pytest.raises(RuntimeError,match='requires'):compare_parsers.run(live=True,limit=1)


def test_ragas_excludes_offline_abstentions_and_bad_quotes(report,live_report):
    rows,excluded=ragas_review.prepare(report)
    assert not rows and len(excluded)==25
    rows,excluded=ragas_review.prepare(live_report)
    assert len(rows)==1 and rows[0]['response']==live_report['policy_samples'][0]['result']['findings'][0]['quote']
    assert len(excluded)==24
    live_report['policy_samples'][0]['result']['findings'][0]['quote']='Invented acceptance guarantee'
    rows,excluded=ragas_review.prepare(live_report)
    assert not rows and excluded[0]['reason']=='unverifiable_saved_citation'


def test_ragas_does_not_judge_without_explicit_flag(tmp_path,live_report,monkeypatch):
    path=tmp_path/'live.json';path.write_text(json.dumps(live_report))
    monkeypatch.setattr(ragas_review,'judge',lambda *a:pytest.fail('Not authorized to call judge'))
    result=ragas_review.run(path,tmp_path/'prepared.json')
    assert result['status']=='not_run' and result['scores'] is None and result['selected_answers']==1


def test_ragas_failed_metrics_are_not_zero_or_perfect(tmp_path,live_report,monkeypatch):
    path=tmp_path/'live.json';path.write_text(json.dumps(live_report))
    monkeypatch.setattr(ragas_review,'judge',lambda rows,*a:[{'id':rows[0]['id'],'faithfulness':None,'context_precision_without_reference':.5,'answer_relevance':1}])
    result=ragas_review.run(path,tmp_path/'scores.json',True,'gemini','simulated',1)
    assert result['status']=='completed_with_missing_scores'
    assert result['aggregate']['faithfulness']=={'mean':None,'scored':0,'failed_or_missing':1}


def test_review_assignments_are_balanced_overlap_and_blank(tmp_path,report):
    source=tmp_path/'report.json';source.write_text(json.dumps(report))
    output=tmp_path/'review';m=human_review.make(source,output)
    a,b=m['assignments'].values()
    assert len(a)==len(b)==10 and len({s['id'] for s in a}&{s['id'] for s in b})==5
    assert m['ratings_status']=='not_performed' and not m['source_live_model']
    for file in output.glob('*-blank.csv'):
        rows=list(csv.DictReader(file.open()))
        assert len(rows)==10 and all(not r['relevance'] for r in rows)
    content=(output/'Reviewer_1.html').read_text()
    assert 'gold_source_ids' not in content and 'answerable' not in content
    assert 'fetch(' not in content


def test_review_escapes_untrusted_source_text(tmp_path,report):
    for sample in report['policy_samples']:sample['question']='<script>alert("unsafe")</script>'
    p=tmp_path/'input.json';p.write_text(json.dumps(report));human_review.make(p,tmp_path/'review')
    text=(tmp_path/'review/Reviewer_1.html').read_text()
    assert '<script>alert' not in text and '&lt;script&gt;' in text


def test_blank_reviews_remain_unmeasured(tmp_path,report):
    p=tmp_path/'input.json';p.write_text(json.dumps(report));out=tmp_path/'review';human_review.make(p,out)
    summary=human_review.summarize(out/'manifest.json',list(out.glob('*-blank.csv')),tmp_path/'summary.json')
    assert summary['status']=='not_reviewed' and summary['completed_ratings']==0
    assert summary['unsupported_answer_rating_rate'] is None
    assert summary['ordinal_agreement']['relevance']['quadratic_weighted_kappa'] is None


def fill(path,manifest):
    rows=list(csv.DictReader(path.open()))
    for r in rows:
        meta=next(s for s in manifest['assignments'][r['reviewer_id']] if s['id']==r['sample_id'])
        for field in human_review.CRITERIA:r[field]='NA' if not meta['has_answer'] and field in ['grounding','completeness'] else '4'
        r['decision_appropriate']='yes';r['unsupported_claim']='no' if meta['has_answer'] else 'NA'
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=human_review.FIELDS);w.writeheader();w.writerows(rows)


def test_completed_reviews_agreement_and_duplicates(tmp_path,report):
    p=tmp_path/'input.json';p.write_text(json.dumps(report));out=tmp_path/'review';m=human_review.make(p,out)
    files=list(out.glob('*-blank.csv'))
    for f in files:fill(f,m)
    result=human_review.summarize(out/'manifest.json',files,tmp_path/'summary.json')
    assert result['status']=='completed' and result['completed_ratings']==20 and result['overlap_completed']==5
    assert result['decision_agreement']==1 and result['ordinal_agreement']['relevance']['exact_agreement']==1
    assert result['ordinal_agreement']['relevance']['quadratic_weighted_kappa'] is None
    with pytest.raises(ValueError,match='Duplicate'):human_review.summarize(out/'manifest.json',[files[0],files[0]],tmp_path/'duplicate.json')


def test_invalid_review_and_manifest_are_rejected(tmp_path,report):
    p=tmp_path/'input.json';p.write_text(json.dumps(report));out=tmp_path/'review';m=human_review.make(p,out)
    f=out/'Reviewer_1-blank.csv';text=f.read_text().replace('Reviewer_1','unknown');f.write_text(text)
    with pytest.raises(ValueError,match='assignment'):human_review.summarize(out/'manifest.json',[f],tmp_path/'bad.json')
    m['overlap']=1;(out/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='fingerprint'):human_review.summarize(out/'manifest.json',[],tmp_path/'bad.json')


def test_weighted_agreement_uses_disagreement_magnitude():
    # Observed squared disagreement is 0.5; independent expected is 4.0.
    assert human_review.kappa([(1,1),(2,3),(4,4),(5,4)])==pytest.approx(.875)
    assert human_review.kappa([(1,5),(5,1)])==pytest.approx(-1)
    assert human_review.kappa([]) is None
