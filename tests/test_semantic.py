import os
from pathlib import Path
import pytest
from app.rag import Retriever


def test_auto_reports_offline_fallback(client,tmp_path,monkeypatch):
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
    def unavailable(*args,**kwargs): raise TimeoutError('download unavailable')
    monkeypatch.setattr(ONNXMiniLM_L6_V2,'__call__',unavailable)
    monkeypatch.setenv('EMBEDDING_BACKEND','auto')
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    retriever=Retriever(client.app.state.db)
    assert retriever.backend=='hash' and retriever.warning
    assert 'feature-hash' in retriever.model_version
    assert retriever.query('fragile electronics')[0]['embedding_version']==retriever.model_version
    monkeypatch.setenv('EMBEDDING_BACKEND','minilm')
    with pytest.raises(TimeoutError): Retriever(client.app.state.db)


@pytest.mark.skipif(os.getenv('RUN_SEMANTIC_TESTS')!='1',reason='Opt-in real MiniLM test requires verified model weights or download access')
def test_real_minilm_semantic_retrieval(client,tmp_path,monkeypatch):
    cache=Path(os.getenv('MODEL_CACHE_DIR','.data/models')).resolve()
    monkeypatch.setenv('MODEL_CACHE_DIR',str(cache))
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('EMBEDDING_BACKEND','minilm')
    r=Retriever(client.app.state.db)
    assert r.backend=='minilm' and r.warning is None
    hits=r.query('Breakable valuable electronic goods need protected gentle handling',mode='dense')
    assert hits and hits[0]['carrier_id'] in {'C01','C04','C07','C10'}
    assert all('MiniLM' in h['embedding_version'] for h in hits)
    a,b,c=r.embed(['Fragile goods need careful handling','Delicate freight requires gentle loading','Refrigerated chilled food needs cold trailers'])
    dot=lambda x,y:sum(u*v for u,v in zip(x,y))
    assert dot(a,b)>dot(a,c)
