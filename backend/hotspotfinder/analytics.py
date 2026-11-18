"""Descriptive comparisons over a shared, completed residue cohort."""
import csv
import io
import math
from collections import Counter
from itertools import combinations

import numpy as np

from . import registry

UNITS = {'saambe3d': 'kcal/mol', 'foldx': 'kcal/mol', 'evoef': 'EvoEF score', 'budealascan': 'kcal/mol', 'flex_ddg': 'REU'}


def average_ranks(values):
    """Descending ranks, assigning the mean position to exact ties."""
    ordered = sorted(range(len(values)), key=lambda index: values[index], reverse=True)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for index in ordered[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def correlation(left, right):
    if len(left) < 2:
        return None, '공통 잔기가 2개 이상 필요합니다.'
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    a, b = a - a.mean(), b - b.mean()
    scale = float(np.linalg.norm(a) * np.linalg.norm(b))
    if scale == 0:
        return None, '한 도구 이상의 점수가 모두 같습니다.'
    return max(-1.0, min(1.0, float(np.dot(a, b) / scale))), None


def exclusion_reason(score, fingerprint, unit):
    if not score:
        return 'not_calculated'
    if score['fingerprint'] != fingerprint:
        return 'previous_configuration'
    statuses = score['statuses']
    if 'failed' in statuses:
        return 'failed'
    if 'cancelled' in statuses:
        return 'cancelled'
    if score['completed'] != score['planned'] or not statuses or any(s != 'succeeded' for s in statuses):
        return 'incomplete'
    if score['value'] is None or not math.isfinite(score['value']) or score['unit'] != unit:
        return 'invalid_result'
    return None


def sensitivity_curve(values):
    positive = Counter(value for value in values if value > 0)
    count = sum(positive.values())
    # Zero denotes the limit as a positive threshold approaches zero.
    points = [{'threshold': 0.0, 'count': count}]
    for value in sorted(positive):
        points.append({'threshold': value, 'count': count})
        count -= positive[value]
        above = math.nextafter(value, math.inf)
        if math.isfinite(above):
            points.append({'threshold': above, 'count': count})
    return points


def ranking_reason(selected, count):
    if len(selected) < 2:
        return '평균 순위 비교에는 엔진이 2개 이상 필요합니다.'
    if count < 2:
        return '평균 순위 비교에는 공통 완료 잔기가 2개 이상 필요합니다.'
    return None


def summarize(analysis_id, result, selected=None, top_k=10):
    rows, jobs = result['rows'], result['jobs']
    latest = {}
    for job in jobs:
        latest[job['engine']] = job['payload']['fingerprint']
    available = []
    reasons = {}
    for engine in registry.IDS:
        engine_reasons = [exclusion_reason(row['scores'].get(engine), latest.get(engine), UNITS[engine]) for row in rows]
        reasons[engine] = engine_reasons
        available.append({
            'id': engine, 'name': registry.NAMES[engine], 'unit': UNITS[engine],
            'has_results': any(row['scores'].get(engine, {}).get('value') is not None for row in rows),
            'complete_count': engine_reasons.count(None),
            'fingerprint': latest.get(engine),
        })
    if selected is None:
        selected = [e['id'] for e in available if e['complete_count'] > 0]
    if len(selected) != len(set(selected)) or not set(selected) <= set(registry.IDS):
        raise ValueError('서로 다른 지원 엔진을 선택하세요.')
    if top_k < 1:
        raise ValueError('상위 후보 수는 1 이상이어야 합니다.')
    selected = [engine for engine in registry.IDS if engine in selected]
    cohort_indices = [index for index in range(len(rows)) if selected and all(reasons[e][index] is None for e in selected)]
    cohort = [rows[index] for index in cohort_indices]
    count = len(cohort)
    effective_k = min(top_k, count)
    ranks = {e: average_ranks([row['scores'][e]['value'] for row in cohort]) for e in selected}
    ranked_rows = []
    top_sets = {}
    sensitivities = {}
    for engine in selected:
        values = [row['scores'][engine]['value'] for row in cohort]
        cutoff = sorted(values, reverse=True)[effective_k - 1] if effective_k else None
        top_sets[engine] = {row['key'] for row in cohort if cutoff is not None and row['scores'][engine]['value'] >= cutoff}
        saved = result['thresholds'].get(engine)
        applicable = bool(saved and saved.get('value') is not None and saved.get('fingerprint') == latest.get(engine) and saved.get('unit') == UNITS[engine])
        sensitivities[engine] = {
            'unit': UNITS[engine], 'points': sensitivity_curve(values),
            'saved_threshold': saved, 'saved_applicable': applicable,
            'saved_count': sum(value >= saved['value'] for value in values) if applicable else None,
        }
    for index, row in enumerate(cohort):
        row_ranks = [ranks[e][index] for e in selected]
        values = [row['scores'][e]['value'] for e in selected]
        scores = {e: {key: row['scores'][e][key] for key in ('value', 'unit', 'sd', 'completed', 'planned', 'fingerprint')} for e in selected}
        for engine in selected:
            scores[engine].update(rank=ranks[engine][index], top_member=row['key'] in top_sets[engine])
        ranked_rows.append({
            **{key: row[key] for key in ('key', 'chain', 'number', 'icode', 'wt')}, 'scores': scores,
            'mean_rank': sum(row_ranks) / len(row_ranks) if count > 1 and len(selected) > 1 else None,
            'rank_spread': max(row_ranks) - min(row_ranks),
            'sign_conflict': min(values) < 0 < max(values),
        })
    ranked_rows.sort(key=lambda row: (row['mean_rank'] or 0, row['chain'], row['number'], row['icode']))
    pairs = []
    for left, right in combinations(selected, 2):
        rho, reason = correlation(ranks[left], ranks[right])
        common = top_sets[left] & top_sets[right]
        union = top_sets[left] | top_sets[right]
        pairs.append({
            'left': left, 'right': right, 'n': count, 'spearman': rho, 'reason': reason,
            'jaccard': len(common) / len(union) if union else None,
            'left_top_count': len(top_sets[left]), 'right_top_count': len(top_sets[right]),
            'common_top_keys': [row['key'] for row in ranked_rows if row['key'] in common],
        })
    return {
        'analysis_id': analysis_id, 'engines': selected, 'available': available,
        'total_count': len(rows), 'common_count': count,
        'excluded_count': len(rows) - count,
        'exclusions': {e: dict(Counter(reason for reason in reasons[e] if reason)) for e in selected},
        'top_k': effective_k, 'requested_top_k': top_k,
        'provisional': any(j['engine'] in selected and j['status'] in ('queued', 'running') for j in jobs),
        'ranking_reason': ranking_reason(selected, count),
        'rows': ranked_rows, 'pairs': pairs, 'sensitivity': sensitivities,
    }


def comparison_csv(report):
    buffer = io.StringIO()
    fields = ['analysis_id', 'selected_engines', 'common_count', 'excluded_count', 'top_k', 'provisional',
              'residue_key', 'chain', 'number', 'icode', 'wt', 'mean_rank', 'rank_spread', 'sign_conflict',
              'engine', 'value', 'unit', 'rank', 'top_member', 'sd', 'completed', 'planned', 'fingerprint']
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in report['rows']:
        for engine, score in row['scores'].items():
            writer.writerow({
                'analysis_id': report['analysis_id'], 'selected_engines': '|'.join(report['engines']),
                **{key: report[key] for key in ('common_count', 'excluded_count', 'top_k', 'provisional')},
                **{key: row[key] for key in ('chain', 'number', 'icode', 'wt', 'mean_rank', 'rank_spread', 'sign_conflict')},
                'residue_key': row['key'], 'engine': engine, **score,
            })
    return '\ufeff' + buffer.getvalue()
