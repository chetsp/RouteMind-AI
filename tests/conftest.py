import os
import pytest
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("routemind")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("DATA_DIR", str(data))
        env.setenv("EMBEDDING_BACKEND", "hash")
        env.delenv("ROUTEMIND_MODEL", raising=False)
        with TestClient(create_app(os.getenv("TEST_DATABASE_URL"))) as c:
            yield c


@pytest.fixture
def network(client):
    return client.app.state.db.network()
