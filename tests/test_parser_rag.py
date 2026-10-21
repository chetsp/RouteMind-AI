from app.parser import demo_extract
from app.rag import hash_vector


def test_parser_no_budget_from_stops(network):
    fields, questions=demo_extract('15 pallets Fremont to Austin at most 1 stop',network[0])
    assert fields['max_stops']==1 and 'max_budget_cents' not in fields
    assert not questions


def test_parser_currency_and_dates(network):
    fields, questions=demo_extract('15 pallets Fremont to Austin budget $2,100.50 ready 2026-11-01T06:00:00Z by 2026-11-03T12:00:00-06:00',network[0])
    assert fields['max_budget_cents']==210050 and not questions
    assert fields['ready_at'].utcoffset().total_seconds()==0
    assert fields['delivery_deadline'].utcoffset().total_seconds()==-21600


def test_hash_repeatability():
    assert hash_vector('fragile electronics')==hash_vector('fragile electronics')
    assert abs(sum(v*v for v in hash_vector('secure trailers'))-1)<1e-8


def test_rag_ids_metadata_and_no_pruning(client):
    r=client.app.state.retriever
    for mode in ['dense','bm25','hybrid','reranked']:
        hits=r.query('Cobalt fragile electronics secure sealed trailers',mode=mode)
        assert hits and hits[0]['carrier_id']=='C01'
        assert all(h['source_id'] in r.by_id and h['version']==1 for h in hits)
    filtered=r.query('fragile secure',carrier_ids={'C04'})
    assert all(h['carrier_id'] in {None,'C04'} for h in filtered)
