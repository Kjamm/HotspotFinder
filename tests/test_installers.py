import io
import stat
import tarfile
import zipfile

import pytest

from hotspotfinder import engines, installers, store, worker


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


@pytest.mark.parametrize('name', ['../outside', '/outside', 'folder/../../outside', 'C:\\outside'])
def test_archive_rejects_escaping_paths(tmp_path, name):
    source = tmp_path / 'bad.zip'
    source.write_bytes(zip_bytes({name: b'bad'}))
    with pytest.raises(ValueError):
        installers.safe_extract(source, tmp_path / 'output')
    assert not (tmp_path / 'outside').exists()


def test_archive_skips_links_and_rejects_devices(tmp_path):
    source = tmp_path / 'links.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        link = zipfile.ZipInfo('link')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, '../outside')
        archive.writestr('normal/data', 'ok')
    destination = tmp_path / 'out'
    installers.safe_extract(source, destination)
    assert not (destination / 'link').exists()
    assert (destination / 'normal/data').read_text() == 'ok'
    source = tmp_path / 'device.tar'
    with tarfile.open(source, 'w') as archive:
        device = tarfile.TarInfo('device')
        device.type = tarfile.CHRTYPE
        archive.addfile(device)
    with pytest.raises(ValueError, match='특수'):
        installers.safe_extract(source, tmp_path / 'other')


def test_archive_size_limit_and_cancellation(tmp_path, monkeypatch):
    source = tmp_path / 'test.zip'
    source.write_bytes(zip_bytes({'file': b'1234'}))
    monkeypatch.setattr(installers, 'MAX_EXPANDED', 3)
    with pytest.raises(ValueError, match='제한'):
        installers.safe_extract(source, tmp_path / 'out')
    monkeypatch.setattr(installers, 'MAX_EXPANDED', 100)
    def cancel():
        raise engines.Cancelled('cancelled')
    with pytest.raises(engines.Cancelled):
        installers.safe_extract(source, tmp_path / 'cancelled', cancel)


def test_foldx_archive_discovery(tmp_path):
    source = tmp_path / 'foldx.zip'
    source.write_bytes(zip_bytes({'foldx5Mac': b'\xcf\xfa\xed\xfe' + b'fixture', 'data/rotabase.txt': b'fixture'}))
    config = installers.install_archive('foldx', source, tmp_path / 'installed')
    assert config['executable'].endswith('foldx5Mac')
    assert config['data_dir'].endswith('/data')
    assert config['status'] == 'needs_validation'
    assert config['validation'] is None


def test_rosetta_archive_requires_database(tmp_path):
    source = tmp_path / 'rosetta.zip'
    source.write_bytes(zip_bytes({'bin/rosetta_scripts.default.linuxgccrelease': b'\x7fELFfixture'}))
    with pytest.raises(ValueError, match='database'):
        installers.install_archive('flex_ddg', source, tmp_path / 'missing')
    source.write_bytes(zip_bytes({'bin/rosetta_scripts.default.linuxgccrelease': b'\x7fELFfixture', 'database/scoring/weights/test.wts': b'fixture'}))
    config = installers.install_archive('flex_ddg', source, tmp_path / 'complete')
    assert config['data_dir'].endswith('/database')


def test_installation_queue_excludes_other_engine_actions(client, analysis):
    response = client.post('/api/engines/evoef/install')
    assert response.status_code == 200
    job_id = response.json()['jobs'][0]
    assert store.job(job_id)['payload']['install']
    assert client.post('/api/engines/evoef/install').status_code == 409
    assert client.post('/api/engines/evoef/validate').status_code == 409
    assert client.put('/api/engines/evoef', json={}).status_code == 409
    residue = next(r for r in analysis['rows'] if r['selected'])
    assert client.post('/api/analyses/' + analysis['id'] + '/run', json={'engines': ['evoef'], 'residues': [residue['key']]}).status_code == 409
    client.post('/api/jobs/' + job_id + '/cancel')
    retry = client.post('/api/jobs/' + job_id + '/retry')
    assert retry.status_code == 200
    assert store.job(retry.json()['jobs'][0])['payload']['install']


def test_archive_worker_queues_real_validation(client, tmp_path, monkeypatch):
    package = zip_bytes({'foldx': b'\x7fELFfixture'})
    response = client.post('/api/engines/foldx/install-archive', content=package)
    job = store.claim()
    assert job['id'] == response.json()['jobs'][0]
    worker.process(job)
    completed = store.job(job['id'])
    assert completed['status'] == 'succeeded', completed['error']
    assert store.get('engine', 'foldx')['status'] == 'needs_validation'
    validation = store.job(completed['result']['validation_jobs'][0])
    assert validation['payload']['validation']
    assert validation['status'] == 'queued'
    assert validation['payload']['residues']


def test_bad_archive_fails_without_changing_configuration(client):
    before = client.get('/api/engines').json()
    response = client.post('/api/engines/foldx/install-archive', content=b'invalid')
    worker.process(store.claim())
    job = store.job(response.json()['jobs'][0])
    assert job['status'] == 'failed'
    assert client.get('/api/engines').json() == before
    assert client.post('/api/engines/foldx/install-archive', content=b'').status_code == 422
