import pytest


def test_reference_browsing(client):
    summary = client.get('/api/v1/explorer').json()
    assert summary['read_only'] and summary['data_type'] == 'synthetic'
    assert summary['tables']['hubs'] == 18
    assert 'shipment_requests' not in summary['tables']
    first = client.get('/api/v1/explorer/tables/schedules?limit=7').json()
    second = client.get('/api/v1/explorer/tables/schedules?limit=7&offset=7').json()
    assert len(first['rows']) == len(second['rows']) == 7
    assert not ({r['id'] for r in first['rows']} & {r['id'] for r in second['rows']})
    assert first['total'] == summary['tables']['schedules']
    assert client.get('/api/v1/explorer/tables/hubs?q=fremont').json()['total'] >= 1
    assert client.get('/api/v1/explorer/tables/hubs?q=%25').json()['total'] == 0
    assert client.get('/api/v1/explorer/tables/hubs?offset=10000').json()['rows'] == []


def test_actual_chroma_records_and_embeddings(client):
    collection = client.app.state.retriever.collection
    data = client.get('/api/v1/explorer/vectors?limit=3').json()
    assert data['total'] == collection.count()
    row = data['rows'][0]
    stored = collection.get(ids=[row['source_id']], include=['documents', 'embeddings', 'metadatas'])
    detail = client.get('/api/v1/explorer/vectors/' + row['source_id']).json()
    assert detail['text'] == row['text'] == stored['documents'][0]
    assert detail['metadata'] == stored['metadatas'][0]
    assert detail['embedding'] == stored['embeddings'][0].tolist()
    assert detail['dimension'] == 384
    assert detail['norm'] == pytest.approx(1, abs=1e-5)
    assert client.get('/api/v1/explorer/vectors?q=' + row['source_id']).json()['total'] >= 1
    assert client.get('/api/v1/explorer/vectors/missing').status_code == 404


@pytest.mark.parametrize('path', ['tables/hubs?limit=101', 'vectors?offset=-1', 'vectors?limit=0', 'tables/hubs?q='+'a'*201])
def test_explorer_bounds(client, path):
    assert client.get('/api/v1/explorer/' + path).status_code == 422


def test_read_only_allowlist(client):
    assert client.get('/api/v1/explorer/tables/shipment_requests').status_code == 404
    before = client.get('/api/v1/explorer').json()
    for method in ['post', 'put', 'patch', 'delete']:
        assert client.request(method, '/api/v1/explorer/tables/hubs', json={'name':'changed'}).status_code == 405
    assert client.get('/api/v1/explorer').json() == before
    assert client.get('/explorer').status_code == 200
