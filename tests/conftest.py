import pytest
from fastapi.testclient import TestClient
from hotspotfinder import store
from hotspotfinder.app import app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setenv('HOTSPOT_NO_WORKER', '1')
    with TestClient(app, headers={'X-Hotspot-Client': 'local-ui'}) as c:
        yield c

@pytest.fixture
def analysis(client):
    source = client.post('/api/example').json()
    response = client.post('/api/analyses', json={'structure_id': source['id'], 'group1': ['A'], 'group2': ['B'], 'scan_chains': ['A']})
    assert response.status_code == 200, response.text
    return response.json()
