"""Real local engine adapters. No simulated affinity predictions."""
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import time
from decimal import Decimal
from pathlib import Path

from . import store

IDS = ('foldx', 'evoef', 'budealascan', 'flex_ddg')
NAMES = dict(zip(IDS, ('FoldX', 'EvoEF', 'BudeAlaScan', 'Flex ddG')))
PROTOCOL = Path(__file__).parent / 'protocols/flex-ddg.xml'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('유한하지 않은 엔진 출력값입니다.')
    return result


def binding_difference(mutant, wild_type):
    """Subtract the decimal energies printed by FoldX and EvoEF."""
    return float(Decimal(str(mutant)) - Decimal(str(wild_type)))


def fingerprint(config):
    payload = {k: v for k, v in config.items() if k not in ('status', 'validation', 'fingerprint', 'error')}
    path = Path(config.get('executable', ''))
    if not path.is_file():
        raise ValueError('실행 파일의 절대 경로를 설정하세요.')
    if not os.access(path, os.X_OK):
        raise ValueError('실행 권한이 없는 파일입니다.')
    payload['binary_sha256'] = sha(path)
    payload['platform'] = platform.system() + '-' + platform.machine()
    payload['adapter_sha256'] = sha(__file__)
    payload['protocol_sha256'] = sha(PROTOCOL)
    library = path.parent / 'library' if config['id'] == 'evoef' else Path(config.get('data_dir') or path.parent)
    if config['id'] in ('evoef', 'foldx'):
        files = sorted(library.rglob('*')) if config['id'] == 'evoef' else sorted(library.glob('*.txt'))
        payload['library_hashes'] = {str(f.relative_to(library)): sha(f) for f in files if f.is_file()}
    if config['id'] == 'budealascan':
        image = config.get('image', '')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
            raise ValueError('Docker image inspect로 확인한 로컬 sha256 이미지 ID를 입력하세요.')
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def configs():
    saved = {c['id']: c for c in store.listing('engine')}
    out = []
    for id_ in IDS:
        c = saved.get(id_, {'id': id_, 'executable': '', 'version': '', 'data_dir': '', 'image': '', 'status': 'not_installed', 'validation': None})
        if not c['executable'] and id_ == 'evoef':
            guess = store.ROOT / '.engines/EvoEF/EvoEF'
            if guess.exists():
                c['executable'] = str(guess)
                c['version'] = '1.1 (locally built)'
                c['status'] = 'needs_validation'
        if c.get('status') == 'ready':
            try:
                if fingerprint(c) != c['fingerprint']:
                    c['status'] = 'needs_validation'
            except ValueError:
                c['status'] = 'needs_validation'
        out.append({**c, 'name': NAMES[id_], 'platform': platform.system() + '-' + platform.machine()})
    return out


class Cancelled(Exception):
    pass


class Runner:
    def __init__(self, directory, job_id=None, timeout=7200, stopped=lambda: False):
        self.directory, self.job_id, self.timeout, self.stopped = Path(directory), job_id, timeout, stopped
        self.directory.mkdir(parents=True, exist_ok=True)
        self.start = time.monotonic()
        self.steps = 0

    def check(self):
        if self.stopped() or (self.job_id and store.job(self.job_id)['cancel']):
            raise Cancelled('사용자가 계산을 취소했습니다.')
        if time.monotonic() - self.start > self.timeout:
            raise TimeoutError('작업 시간 제한을 초과했습니다.')

    def run(self, args, filename=None):
        self.check()
        self.steps += 1
        logfile = self.directory / (filename or f'{self.steps:02d}-{Path(args[0]).name}.log')
        with (self.directory / 'commands.jsonl').open('a') as f:
            f.write(json.dumps({'argv': args, 'time': time.time(), 'log': logfile.name}) + '\n')
        with logfile.open('w') as log:
            proc = subprocess.Popen(args, cwd=self.directory, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'})
            if self.job_id:
                store.update_job(self.job_id, pid=proc.pid)
            try:
                while proc.poll() is None:
                    self.check()
                    time.sleep(.15)
                if proc.returncode:
                    raise RuntimeError(f'종료 코드 {proc.returncode}: {logfile.name}\n' + logfile.read_text(errors='replace')[-1200:])
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                if self.job_id:
                    store.update_job(self.job_id, pid=None)
        return logfile.read_text(errors='replace')


def evoef_score(text):
    if 'Binding energy details between chain(s)' not in text:
        raise ValueError('EvoEF binding energy 출력이 아닙니다.')
    matches = re.findall(r'^Total\s*=\s*([-+\d.eE]+)\s*$', text, re.M)
    if len(matches) != 1:
        raise ValueError('EvoEF의 선택한 파트너 binding score를 유일하게 식별하지 못했습니다.')
    return finite(matches[0])


def foldx_score(path, groups):
    lines = Path(path).read_text(errors='replace').splitlines()
    for i, line in enumerate(lines):
        header = [x.strip().lower() for x in line.split('\t')]
        if all(x in header for x in ('group1', 'group2', 'interaction energy')):
            hits = []
            for data in lines[i+1:]:
                cells = [x.strip() for x in data.split('\t')]
                if len(cells) != len(header):
                    continue
                row = dict(zip(header, cells))
                pair = {frozenset(row['group1']), frozenset(row['group2'])}
                if pair == {frozenset(g) for g in groups}:
                    hits.append(finite(row['interaction energy']))
            if len(hits) == 1:
                return hits[0]
            raise ValueError('FoldX 파트너 그룹에 대응하는 Interaction Energy가 유일하지 않습니다.')
    raise ValueError('FoldX binding output header가 없습니다. 접힘 에너지 파일은 허용하지 않습니다.')


def flex_score(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as c:
        count = c.execute('SELECT max(batch_id) FROM batches').fetchone()[0]
        rows = c.execute('''SELECT batches.name,structure_scores.struct_id,structure_scores.score_value,score_function_method_options.score_function_name
        FROM structure_scores JOIN batches ON batches.batch_id=structure_scores.batch_id
        JOIN score_types ON score_types.batch_id=structure_scores.batch_id AND score_types.score_type_id=structure_scores.score_type_id
        JOIN score_function_method_options ON score_function_method_options.batch_id=batches.batch_id
        WHERE score_types.score_type_name='total_score' ''').fetchall()
    checkpoints = {}
    for name, struct, value, scorefn in rows:
        checkpoint = (struct - 1) // count
        state = name.removesuffix('_dbreport')
        block = checkpoints.setdefault((checkpoint, scorefn), {})
        if state in block:
            raise ValueError('Flex ddG 중복 state 출력입니다.')
        block[state] = finite(value)
    if not checkpoints:
        raise ValueError('Flex ddG 결과가 없습니다.')
    latest = max(k[0] for k in checkpoints)
    blocks = [(k, v) for k, v in checkpoints.items() if k[0] == latest]
    if len(blocks) != 1:
        raise ValueError('Flex ddG score function이 모호합니다.')
    (checkpoint, fn), v = blocks[0]
    if set(v) != {'bound_mut', 'bound_wt', 'unbound_mut', 'unbound_wt'}:
        raise ValueError('Flex ddG 최종 checkpoint에 네 상태가 모두 필요합니다.')
    wt, mut = v['bound_wt'] - v['unbound_wt'], v['bound_mut'] - v['unbound_mut']
    return mut - wt, {'states': v, 'score_function': fn, 'checkpoint_index': checkpoint, 'wt_binding': wt, 'mutant_binding': mut}


def bude_scores(files, residues):
    lookup = {(r['engine_chain'], r['engine_number']): r for r in residues}
    results = {}
    for path in files:
        content = json.loads(Path(path).read_text())
        if len(content['ala_scan']) != 1:
            raise ValueError('BudeAlaScan 단일 모델 결과만 지원합니다.')
        for key, row in content['ala_scan'][0].items():
            if key == 'dG':
                continue
            residue = lookup.get((str(row[2]), int(row[0])))
            if residue:
                if row[1] not in (residue['wt'], residue['name']):
                    raise ValueError('BudeAlaScan WT 잔기 매핑이 일치하지 않습니다.')
                if residue['key'] in results:
                    raise ValueError('BudeAlaScan 중복 잔기 출력입니다.')
                raw = finite(row[3])
                results[residue['key']] = {'key': residue['key'], 'value': raw / 4.184, 'unit': 'kcal/mol', 'raw_value': raw, 'raw_unit': 'kJ/mol', 'conversion': 'mutant_minus_wt; kJ/mol / 4.184'}
    if set(results) != {r['key'] for r in residues}:
        raise ValueError('BudeAlaScan 결과에 요청한 잔기가 누락되었습니다.')
    return list(results.values())


def execute(engine, config, analysis, residues, repeat, runner, smoke=False):
    directory = runner.directory
    source = store.DATA / 'analyses' / analysis['id'] / 'normalized.pdb'
    shutil.copyfile(source, directory / 'input.pdb')
    exe, groups = config['executable'], analysis['groups']
    split = ','.join(''.join(g) for g in groups)
    if engine == 'budealascan':
        name = 'hotspot-' + (runner.job_id or store.uid())
        args = [exe, 'run', '--pull=never', '--rm', '--network=none', '--cpus=1', '--name', name, '-e', 'MPLBACKEND=Agg', '-v', f'{directory}:/work', '-w', '/work', '--entrypoint', '/root/bin/budeAlaScan.py', config['image'], 'scan', '-p', 'input.pdb', '-r', *groups[0], '-l', *groups[1], '-t']
        try:
            runner.run(args)
        finally:
            subprocess.run([exe, 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return bude_scores(list(directory.glob('replot/*_scan*.json')), residues)
    residue = residues[0]
    c, n, wt = residue['engine_chain'], residue['engine_number'], residue['wt']
    if engine == 'evoef':
        runner.run([exe, '--command=RepairStructure', '--pdb=input.pdb'])
        repaired = directory / 'input_Repair.pdb'
        if not repaired.is_file():
            raise ValueError('EvoEF 수선 구조가 생성되지 않았습니다.')
        (directory / 'individual_list.txt').write_text(f'{wt}{c}{n}A;\n')
        runner.run([exe, '--command=BuildMutant', '--pdb=input_Repair.pdb', '--mutant_file=individual_list.txt'])
        mutants = [p for p in directory.glob('input_Repair_Model_*.pdb') if not p.stem.endswith('_WT')]
        if len(mutants) != 1:
            raise ValueError('EvoEF mutant 구조가 유일하지 않습니다.')
        paired_wt = mutants[0].with_name(mutants[0].stem + '_WT.pdb')
        if not paired_wt.is_file():
            raise ValueError('EvoEF 대응 WT 구조가 없습니다. 지원 버전의 BuildMutant 출력을 확인하세요.')
        wt_score = evoef_score(runner.run([exe, '--command=ComputeBinding', f'--pdb={paired_wt.name}', f'--split={split}']))
        mut_score = evoef_score(runner.run([exe, '--command=ComputeBinding', f'--pdb={mutants[0].name}', f'--split={split}']))
        value, unit, detail = binding_difference(mut_score, wt_score), 'EvoEF score', {'wt_binding': wt_score, 'mutant_binding': mut_score, 'wt_structure': paired_wt.name, 'unit_note': '공식 구현 원시 점수; kcal/mol로 보정하지 않음'}
    elif engine == 'foldx':
        data_dir = Path(config.get('data_dir') or Path(exe).parent)
        for file in data_dir.glob('*.txt'):
            shutil.copyfile(file, directory / file.name)
        runner.run([exe, '--command=RepairPDB', '--pdb=input.pdb'])
        (directory / 'individual_list.txt').write_text(f'{wt}{c}{n}A;\n')
        runner.run([exe, '--command=BuildModel', '--pdb=input_Repair.pdb', '--mutant-file=individual_list.txt', '--numberOfRuns=1', '--out-pdb=true'])
        wts = list(directory.glob('WT_input_Repair_*.pdb'))
        muts = [p for p in directory.glob('input_Repair_*.pdb') if p.name != 'input_Repair.pdb']
        if len(wts) != 1 or len(muts) != 1:
            raise ValueError('FoldX 대응 WT/mutant PDB 쌍이 유일하지 않습니다.')
        scores = []
        for label, pdb in zip(('wt', 'mut'), (wts[0], muts[0])):
            runner.run([exe, '--command=AnalyseComplex', f'--pdb={pdb.name}', f'--analyseComplexChains={split}', f'--output-file={label}'])
            files = list(directory.glob(f'Interaction_{label}*.fxout'))
            if len(files) != 1:
                raise ValueError('FoldX Interaction 출력 파일이 유일하지 않습니다.')
            scores.append(foldx_score(files[0], groups))
        value, unit, detail = binding_difference(scores[1], scores[0]), 'kcal/mol', {'wt_binding': scores[0], 'mutant_binding': scores[1]}
    elif engine == 'flex_ddg':
        shutil.copyfile(PROTOCOL, directory / 'protocol.xml')
        (directory / 'mutation.resfile').write_text(f'NATAA\nstart\n{n} {c} PIKAA A\n')
        steps = 10 if smoke else 35000
        args = [exe, '-s', 'input.pdb', '-parser:protocol', 'protocol.xml', '-parser:script_vars', 'chainstomove=' + ','.join(groups[1]), 'mutate_resfile_relpath=mutation.resfile', f'number_backrub_trials={steps}', f'backrub_trajectory_stride={steps}', f'max_minimization_iter={5 if smoke else 5000}', 'abs_score_convergence_thresh=1.0', '-restore_talaris_behavior', '-in:file:fullatom', '-ignore_zero_occupancy', 'false', '-ex1', '-ex2', '-constant_seed', '-jran', str(10000 + repeat)]
        if config.get('data_dir'):
            args += ['-database', config['data_dir']]
        log = runner.run(args, 'rosetta.out')
        if 'reported success in' not in log:
            raise ValueError('Rosetta 성공 완료 기록이 없습니다.')
        value, detail = flex_score(directory / 'ddG.db3')
        unit = 'REU'
        detail.update(backrub_steps=steps, seed=10000 + repeat, protocol_sha256=sha(PROTOCOL))
    else:
        raise ValueError('지원하지 않는 엔진입니다.')
    return [{'key': residue['key'], 'value': finite(value), 'unit': unit, 'raw_value': finite(value), 'raw_unit': unit, 'conversion': 'mutant_minus_wt', **detail}]
