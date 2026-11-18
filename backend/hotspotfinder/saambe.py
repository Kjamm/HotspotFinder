"""Local SAAMBE-3D regression model, one mutation list per two-chain complex."""
import hashlib
import json
import os
from pathlib import Path

from . import engines, store

NAME = 'SAAMBE-3D'
FILES = ('saambe-3d.py', 'regression_v01.model', 'utils/__init__.py', 'utils/protseqfeature.py')


def fingerprint(config):
    python = Path(config['executable'])
    source = Path(config['data_dir'])
    if not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError('SAAMBE-3D 전용 Python 실행 파일이 필요합니다.')
    try:
        files = {name: engines.sha(source / name) for name in FILES}
        files['python'] = engines.sha(python)
    except OSError as exc:
        raise ValueError('SAAMBE-3D 소스 또는 회귀 모델을 확인하세요.') from exc
    files['adapter'] = engines.sha(__file__)
    history = python.parent.parent / 'conda-meta' / 'history'
    if history.is_file():
        files['environment'] = engines.sha(history)
    return hashlib.sha256(json.dumps([str(python), str(source), config['version'], files], sort_keys=True).encode()).hexdigest()


def validate(groups, repeats):
    if len(groups) != 2 or any(len(group) != 1 for group in groups):
        raise ValueError('SAAMBE-3D는 각 파트너에 체인 하나씩을 선택해야 합니다.')
    if repeats != 1:
        raise ValueError('SAAMBE-3D는 결정론적 회귀 모델입니다. 반복 수를 1로 설정하세요.')


def parse(path, residues):
    lines = path.read_text().splitlines()
    header = 'Structure_file Chain Position Wild Mutant ddG(kcal/mol) Type'
    if not lines or lines[0].strip() != header:
        raise ValueError('SAAMBE-3D 회귀 모델 출력의 열 또는 단위가 잘못되었습니다.')
    expected = {(r['engine_chain'], str(r['engine_number']), r['wt']): r['key'] for r in residues}
    results = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) != 7 or parts[0] != 'input.pdb' or parts[4] != 'A':
            raise ValueError('SAAMBE-3D 변이 출력 형식이 잘못되었습니다.')
        key = expected.get(tuple(parts[1:4]))
        if key is None or key in results:
            raise ValueError('SAAMBE-3D 잔기 매핑이 일치하지 않습니다.')
        value = engines.finite(parts[5])
        if parts[6] not in ('Stabilizing', 'Destabilizing'):
            raise ValueError('SAAMBE-3D 예측 방향을 읽을 수 없습니다.')
        results[key] = dict(key=key, value=value, raw_value=value, unit='kcal/mol', raw_unit='kcal/mol',
                            direction=parts[6], conversion='reported ddG; positive = destabilizing')
    if len(results) != len(residues):
        raise ValueError('SAAMBE-3D 결과에 요청한 잔기가 누락되었습니다.')
    return [results[r['key']] for r in residues]


def execute(config, analysis, residues, runner):
    validate(analysis['groups'], 1)
    directory = runner.directory
    normalized = store.DATA / 'analyses' / analysis['id'] / 'normalized.pdb'
    original = store.DATA / 'structures' / analysis['input']['structure_id'] / 'original.pdb'
    # The model reads experimental conditions from fixed-column PDB remarks.
    remarks = [line for line in original.read_text().splitlines(keepends=True)
               if line.startswith(('REMARK   2 ', 'REMARK   3 ', 'REMARK 200 '))]
    (directory / 'input.pdb').write_text(''.join(remarks) + normalized.read_text())
    (directory / 'mutations.txt').write_text(''.join(
        f"{r['engine_chain']} {r['engine_number']} {r['wt']} A\n" for r in residues))
    runner.run([config['executable'], str(Path(config['data_dir']) / FILES[0]), '-i', 'input.pdb',
                '-f', 'mutations.txt', '-d', '1', '-o', 'scores.out'])
    return parse(directory / 'scores.out', residues)
