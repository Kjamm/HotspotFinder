import csv
import io
import math

import pytest

from hotspotfinder import analytics, store


def score(value, engine='foldx', **overrides):
    return {
        'value': value, 'unit': analytics.UNITS[engine], 'sd': None,
        'completed': 1, 'planned': 1, 'statuses': ['succeeded'],
        'fingerprint': 'fixture', **overrides,
    }


def dataset(columns):
    rows = []
    for index in range(len(next(iter(columns.values())))):
        rows.append({
            'key': f'0|A|{index + 1}|', 'chain': 'A', 'number': index + 1,
            'icode': '', 'wt': 'W',
            'scores': {engine: score(values[index], engine) for engine, values in columns.items() if values[index] is not None},
        })
    return {
        'rows': rows, 'thresholds': {},
        'jobs': [{'engine': engine, 'status': 'succeeded', 'payload': {'fingerprint': 'fixture'}} for engine in columns],
    }


def test_midranks_spearman_and_stable_mean_rank():
    assert analytics.average_ranks([5, 5, 1]) == [1.5, 1.5, 3]
    result = dataset({'foldx': [5, 5, 1], 'evoef': [9, 6, 3]})
    report = analytics.summarize('fixture', result)
    assert report['pairs'][0]['spearman'] == pytest.approx(math.sqrt(3) / 2)
    assert [r['mean_rank'] for r in report['rows']] == [1.25, 1.75, 3]
    reversed_scores = dataset({'foldx': [1, 2, 3], 'evoef': [3, 2, 1]})
    report = analytics.summarize('fixture', reversed_scores)
    assert report['pairs'][0]['spearman'] == pytest.approx(-1)
    assert [r['number'] for r in report['rows']] == [1, 2, 3]


def test_shared_three_engine_cohort_and_boundary_ties():
    result = dataset({'foldx': [5, 5, 1, 9], 'evoef': [5, 1, 5, 8], 'flex_ddg': [1, 3, 2, None]})
    report = analytics.summarize('fixture', result, ['foldx', 'evoef', 'flex_ddg'], top_k=1)
    assert report['common_count'] == 3 and report['excluded_count'] == 1
    assert all(pair['n'] == 3 for pair in report['pairs'])
    pair = report['pairs'][0]
    assert pair['left_top_count'] == pair['right_top_count'] == 2
    assert pair['jaccard'] == pytest.approx(1 / 3)
    assert pair['common_top_keys'] == ['0|A|1|']
    assert report['exclusions']['flex_ddg'] == {'not_calculated': 1}
    assert report['rows'][0]['mean_rank'] == pytest.approx(11 / 6)
    auto = analytics.summarize('fixture', result, top_k=100)
    assert auto['engines'] == ['foldx', 'evoef', 'flex_ddg']
    assert auto['top_k'] == 3
    assert analytics.summarize('fixture', result, ['foldx', 'evoef'], top_k=100)['top_k'] == 4


@pytest.mark.parametrize('values', [[], [-2, 0], [1, 1, 2, -1, 0], [math.nextafter(1, 0), 1]])
def test_sensitivity_exact_boundaries(values):
    points = analytics.sensitivity_curve(values)
    for point in points:
        expected = sum(value > 0 for value in values) if point['threshold'] == 0 else sum(value >= point['threshold'] for value in values)
        assert point['count'] == expected
    assert all(a['threshold'] <= b['threshold'] and a['count'] >= b['count'] for a, b in zip(points, points[1:]))
    if any(value > 0 for value in values):
        assert points[-1]['count'] == 0


@pytest.mark.parametrize('columns', [
    {'foldx': [], 'evoef': []},
    {'foldx': [1], 'evoef': [2]},
    {'foldx': [1, 1], 'evoef': [2, 3]},
])
def test_undefined_correlation_is_explicit(columns):
    report = analytics.summarize('fixture', dataset(columns), ['foldx', 'evoef'])
    assert report['pairs'][0]['spearman'] is None
    assert report['pairs'][0]['reason']
    if report['common_count'] <= 1:
        assert report['ranking_reason']
        assert all(row['mean_rank'] is None for row in report['rows'])


def test_single_engine_and_no_selection():
    result = dataset({'foldx': [1, 2]})
    single = analytics.summarize('fixture', result)
    assert single['ranking_reason'] and single['pairs'] == []
    assert all(row['mean_rank'] is None for row in single['rows'])
    empty = analytics.summarize('fixture', result, [])
    assert empty['engines'] == [] and empty['common_count'] == 0


def test_failures_configuration_and_provisional_cohort():
    result = dataset({'foldx': [1] * 7, 'evoef': [2] * 7})
    overrides = [
        {'statuses': ['failed'], 'completed': 0},
        {'statuses': ['cancelled'], 'completed': 0},
        {'statuses': ['running'], 'completed': 0},
        {'planned': 2},
        {'fingerprint': 'old'},
        {'unit': 'wrong'},
    ]
    for row, values in zip(result['rows'], overrides):
        row['scores']['foldx'].update(values)
    result['jobs'].append({'engine': 'foldx', 'status': 'running', 'payload': {'fingerprint': 'fixture'}})
    report = analytics.summarize('fixture', result)
    assert report['common_count'] == 1 and report['provisional']
    assert report['exclusions']['foldx'] == {
        'failed': 1, 'cancelled': 1, 'incomplete': 2,
        'previous_configuration': 1, 'invalid_result': 1,
    }


def test_sign_conflict_zero_and_threshold_provenance():
    result = dataset({'foldx': [-1, 0, 2], 'evoef': [1, 1, 2]})
    result['thresholds']['foldx'] = {'value': 2, 'unit': 'kcal/mol', 'fingerprint': 'fixture', 'evidence': 'fixture'}
    report = analytics.summarize('fixture', result)
    assert {row['number'] for row in report['rows'] if row['sign_conflict']} == {1}
    assert report['sensitivity']['foldx']['saved_count'] == 1
    result['thresholds']['foldx']['fingerprint'] = 'old'
    report = analytics.summarize('fixture', result)
    assert not report['sensitivity']['foldx']['saved_applicable']
    assert report['sensitivity']['foldx']['saved_count'] is None


def test_csv_preserves_scores_units_mapping_and_ranking():
    result = dataset({'foldx': [2, 3], 'evoef': [4, 1]})
    result['rows'][0].update(key='0|A|-2|B', number=-2, icode='B')
    report = analytics.summarize('fixture', result)
    output = analytics.comparison_csv(report)
    assert output.startswith('\ufeff')
    rows = list(csv.DictReader(io.StringIO(output.lstrip('\ufeff'))))
    assert len(rows) == 4
    assert rows[0]['number'] == '-2' and rows[0]['icode'] == 'B'
    assert rows[0]['fingerprint'] == 'fixture'
    assert {row['unit'] for row in rows} == {'kcal/mol', 'EvoEF score'}
    assert rows[0]['mean_rank'] == '1.5'


def enqueue_result(analysis, engine, residues, values, repeat=1, planned=1, fingerprint='fixture', status='succeeded'):
    payload = {'residues': residues, 'repeat': repeat, 'planned_repeats': planned, 'fingerprint': fingerprint, 'config': {}}
    job = store.enqueue(analysis['id'], engine, payload, store.uid())
    store.update_job(job, status=status, result=[{'key': row['key'], 'value': value, 'unit': analytics.UNITS[engine]} for row, value in zip(residues, values)] if status == 'succeeded' else None)
    return job


def test_api_retry_latest_protocol_and_export(client, analysis):
    residues = [r for r in analysis['rows'] if r['selected']][:2]
    enqueue_result(analysis, 'foldx', residues, [4, 6], planned=2)
    enqueue_result(analysis, 'foldx', residues, [], repeat=2, planned=2, status='failed')
    enqueue_result(analysis, 'evoef', residues, [1, 3])
    url = f"/api/analyses/{analysis['id']}/analytics"
    assert client.get(url).json()['engines'] == ['evoef']
    assert client.get(url + '?engines=foldx&engines=evoef').json()['common_count'] == 0
    enqueue_result(analysis, 'foldx', residues, [2, 4], repeat=2, planned=2)
    report = client.get(url).json()
    assert report['common_count'] == 2
    scores = {row['key']: row['scores']['foldx'] for row in report['rows']}
    assert scores[residues[0]['key']]['value'] == 3
    assert scores[residues[0]['key']]['sd'] == pytest.approx(math.sqrt(2))
    assert scores[residues[0]['key']]['completed'] == 2
    exported = client.get(url + '.csv?engines=foldx&engines=evoef&top_k=1')
    assert exported.status_code == 200 and 'fingerprint' in exported.text
    enqueue_result(analysis, 'foldx', residues[:1], [9], fingerprint='changed')
    report = client.get(url).json()
    assert report['common_count'] == 1
    assert report['exclusions']['foldx']['previous_configuration'] == 1
    assert report['rows'][0]['scores']['foldx']['value'] == 9


def test_api_validation_and_empty_data(client, analysis):
    url = f"/api/analyses/{analysis['id']}/analytics"
    assert client.get(url).json()['common_count'] == 0
    assert client.get(url + '?engines=').json()['engines'] == []
    for params in ['engines=unknown', 'engines=foldx&engines=foldx', 'top_k=0', 'top_k=1.5']:
        assert client.get(url + '?' + params).status_code == 422
    assert client.get('/api/analyses/missing/analytics').status_code == 404


def test_existing_decimal_binding_scores_tie_at_threshold(client, analysis):
    residues = [r for r in analysis['rows'] if r['selected']][:2]
    payload = {'residues': residues, 'repeat': 1, 'planned_repeats': 1, 'fingerprint': 'fixture'}
    job = store.enqueue(analysis['id'], 'evoef', payload, store.uid())
    old_results = [
        {'key': row['key'], 'wt_binding': wt, 'mutant_binding': mut,
         'value': mut - wt, 'unit': 'EvoEF score'}
        for row, (wt, mut) in zip(residues, [(1.1, 1.3), (0.2, 0.4)])
    ]
    assert old_results[0]['value'] < old_results[1]['value']
    store.update_job(job, status='succeeded', result=old_results)
    url = f"/api/analyses/{analysis['id']}"
    client.put(url + '/threshold', json={'engine': 'evoef', 'value': 0.2, 'unit': 'EvoEF score', 'evidence': 'fixture'})
    report = client.get(url + '/analytics?engines=evoef&top_k=1').json()
    assert report['sensitivity']['evoef']['saved_count'] == 2
    for row in report['rows']:
        assert row['scores']['evoef']['rank'] == 1.5
        assert row['scores']['evoef']['top_member']
    assert store.job(job)['result'] == old_results
