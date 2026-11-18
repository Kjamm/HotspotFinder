import csv
import io

import pytest
from hotspotfinder import registry, saambe, store
from hotspotfinder.app import enqueue_tasks


def output(key='A 3 W A 0.80 Destabilizing'):
    return 'Structure_file Chain Position Wild Mutant ddG(kcal/mol) Type\ninput.pdb ' + key + '\n'


def test_parse_preserves_identity_and_direction(tmp_path):
    rows = [dict(engine_chain='A', engine_number=3, wt='W', key='0|X|12|B')]
    path = tmp_path / 'scores.out'
    path.write_text(output())
    result, = saambe.parse(path, rows)
    assert (result['key'], result['value'], result['raw_unit']) == ('0|X|12|B', .8, 'kcal/mol')
    for invalid in [output('B 3 W A 0.80 Destabilizing'), output('A 3 W A nan Destabilizing'),
                    output().splitlines()[0], output() + output().splitlines()[1], output().replace('kcal/mol', 'REU')]:
        path.write_text(invalid)
        with pytest.raises(ValueError):
            saambe.parse(path, rows)


def test_saambe_uses_one_job_and_exports(client, analysis, monkeypatch):
    monkeypatch.setattr(registry, 'fingerprint', lambda c: 'test')
    config = dict(id='saambe3d')
    rows = [r for r in analysis['rows'] if r['selected']][:2]
    job, = enqueue_tasks(analysis, config, rows, 1, 60)
    store.update_job(job, status='succeeded', result=[{'key': r['key'], 'value': v, 'unit': 'kcal/mol'} for r, v in zip(rows, [-.4, .8])])
    url = '/api/analyses/' + analysis['id'] + '/analytics'
    report = client.get(url + '?engines=saambe3d').json()
    assert report['common_count'] == 2
    data = client.get(url + '.csv?engines=saambe3d').text.lstrip('\ufeff')
    exported = list(csv.DictReader(io.StringIO(data)))
    assert {r['engine'] for r in exported} == {'saambe3d'}
    for groups, repeats in [([['A', 'C'], ['B']], 1), (analysis['groups'], 2)]:
        with pytest.raises(ValueError):
            enqueue_tasks({**analysis, 'groups': groups}, config, rows, repeats, 60)


def test_saambe_install_endpoint(client):
    reply = client.post('/api/engines/saambe3d/install')
    assert reply.status_code == 200
    job = store.job(reply.json()['jobs'][0])
    assert job['engine'] == 'saambe3d' and job['payload']['install']
    assert client.post('/api/engines/saambe3d/install').status_code == 409
