import csv
import hashlib
import io
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engines, store, structure, analytics, registry, saambe


@asynccontextmanager
async def lifespan(app):
    store.init()
    worker = None
    if os.environ.get('HOTSPOT_NO_WORKER') != '1':
        log = (store.DATA / 'worker.log').open('a')
        worker = subprocess.Popen([sys.executable, '-m', 'hotspotfinder.worker'], stdout=log, stderr=log)
    yield
    if worker:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
        log.close()


app = FastAPI(title='HotspotFinder local API', lifespan=lifespan)


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.url.hostname
    if host not in ('localhost', '127.0.0.1', '::1', 'testserver'):
        return JSONResponse({'detail': 'Local host only'}, status_code=403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if request.headers.get('x-hotspot-client') != 'local-ui':
            return JSONResponse({'detail': 'Missing local client header'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Cross-origin request rejected'}, status_code=403)
    return await call_next(request)


@app.exception_handler(KeyError)
async def not_found(request, exc):
    return JSONResponse({'detail': '요청한 기록을 찾을 수 없습니다.'}, status_code=404)


@app.exception_handler(ValueError)
async def bad_input(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    pdb: str = Field(min_length=1, max_length=20_000_000)


class Selection(BaseModel):
    structure_id: str
    model: int = 0
    group1: List[str]
    group2: List[str]
    scan_chains: List[str]
    cutoff: float = Field(default=5, ge=2, le=12, allow_inf_nan=False)
    include_gly: bool = False


class EngineConfig(BaseModel):
    executable: str = ''
    version: str = Field(default='', max_length=150)
    data_dir: str = ''
    image: str = ''


class Run(BaseModel):
    engines: List[str]
    residues: List[str]
    repeats: int = Field(default=1, ge=1, le=50)
    timeout: int = Field(default=7200, ge=30, le=604800)


class Runtime(BaseModel):
    concurrency: int = Field(ge=1, le=8)


class Threshold(BaseModel):
    engine: str
    value: Optional[float] = Field(default=None, allow_inf_nan=False)
    unit: str = ''
    evidence: str = Field(default='', max_length=1000)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '0.1.0', 'local_only': True}


@app.post('/api/structures')
def upload(body: Upload):
    try:
        metadata = structure.inspect(body.pdb)
    except Exception as exc:
        raise ValueError(f'PDB를 읽을 수 없습니다: {exc}') from exc
    id_ = store.uid()
    folder = store.DATA / 'structures' / id_
    folder.mkdir(parents=True)
    (folder / 'original.pdb').write_text(body.pdb)
    record = {'id': id_, 'name': Path(body.name).name, 'sha256': engines.sha(folder / 'original.pdb'), **metadata}
    store.save('structure', id_, record)
    return record


@app.post('/api/example')
def example():
    return upload(Upload(name='1JTG_AB.pdb', pdb=(store.ROOT / 'examples/1JTG_AB.pdb').read_text()))


@app.post('/api/analyses')
def create_analysis(body: Selection):
    source = store.get('structure', body.structure_id)
    pdb = (store.DATA / 'structures' / body.structure_id / 'original.pdb').read_text()
    prepared = structure.prepare(pdb, body.model, body.group1, body.group2, body.scan_chains, body.cutoff, body.include_gly)
    id_ = store.uid()
    folder = store.DATA / 'analyses' / id_
    folder.mkdir(parents=True)
    (folder / 'normalized.pdb').write_text(prepared.pop('pdb'))
    record = {'id': id_, 'name': source['name'], 'created': time.time(), 'input': body.model_dump(), 'source_sha256': source['sha256'], 'normalized_hash': engines.sha(folder / 'normalized.pdb'), 'thresholds': {}, **prepared}
    store.save('analysis', id_, record)
    (folder / 'manifest.json').write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return record


@app.get('/api/analyses')
def analyses():
    return [{'id': a['id'], 'name': a['name'], 'created': a['created'], 'candidates': sum(r['selected'] for r in a['rows'])} for a in store.listing('analysis') if not a.get('validation')]


@app.get('/api/analyses/{id_}')
def analysis(id_: str):
    return store.get('analysis', id_)


@app.get('/api/analyses/{id_}/pdb')
def pdb(id_: str):
    store.get('analysis', id_)
    return FileResponse(store.DATA / 'analyses' / id_ / 'normalized.pdb', media_type='chemical/x-pdb')


@app.get('/api/engines')
def engine_list():
    return registry.configs()


def ensure_engine_idle(id_):
    if any(j['engine'] == id_ and j['status'] in ('queued', 'running') for j in store.jobs()):
        raise HTTPException(409, '해당 엔진의 작업이 끝난 뒤 설치하세요.')


def ensure_no_installation(id_):
    if any(j['engine'] == id_ and j['payload'].get('install') and j['status'] in ('queued', 'running') for j in store.jobs()):
        raise HTTPException(409, '엔진 설치가 진행 중입니다. 완료 후 다시 실행하세요.')


def queue_installation(id_, archive=None):
    ensure_engine_idle(id_)
    payload = {'install': True, 'archive': archive, 'residues': [], 'repeat': 1, 'planned_repeats': 1, 'timeout': 7200}
    return {'jobs': [store.enqueue('installation', id_, payload, 'install-' + store.uid())]}


@app.post('/api/engines/{id_}/install')
def install_engine(id_: str):
    if id_ not in ('evoef', 'saambe3d'):
        raise ValueError('자동 설치를 지원하지 않는 엔진입니다.')
    with store.lock_engines([id_]):
        return queue_installation(id_)


@app.post('/api/engines/{id_}/install-archive')
async def install_archive(id_: str, request: Request):
    if id_ not in ('foldx', 'flex_ddg'):
        raise ValueError('FoldX 또는 Rosetta의 배포 압축 파일을 선택하세요.')
    ensure_engine_idle(id_)
    folder = store.DATA / 'installations' / store.uid()
    folder.mkdir(parents=True)
    archive = folder / 'package.archive'
    try:
        size = 0
        with archive.open('wb') as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 8 * 1024**3:
                    raise ValueError('배포 압축 파일은 최대 8 GB입니다. 큰 패키지는 고급 설정에서 연결하세요.')
                out.write(chunk)
        if not size:
            raise ValueError('빈 배포 파일입니다.')
        with store.lock_engines([id_]):
            return queue_installation(id_, str(archive))
    except BaseException:
        archive.unlink(missing_ok=True)
        folder.rmdir()
        raise


@app.put('/api/engines/{id_}')
def engine_save(id_: str, body: EngineConfig):
    if id_ not in registry.IDS:
        raise ValueError('알 수 없는 엔진')
    with store.lock_engines([id_]):
        if any(j['engine'] == id_ and j['status'] in ('queued', 'running') for j in store.jobs()):
            raise HTTPException(409, '작업이 끝난 뒤 엔진 설정을 변경하세요.')
        record = {'id': id_, **body.model_dump(), 'status': 'not_installed', 'validation': None}
        if body.executable:
            path = Path(body.executable).expanduser()
            if not path.is_absolute():
                raise ValueError('실행 파일은 절대 경로여야 합니다.')
            record['executable'] = str(path.resolve())
            if body.data_dir:
                record['data_dir'] = str(Path(body.data_dir).expanduser().resolve())
            record['fingerprint'] = registry.fingerprint(record)
            record['status'] = 'needs_validation'
        store.save('engine', id_, record)
        return record


def enqueue_tasks(a, config, residues, repeats, timeout, validation=False):
    if a['blocking_hetero']:
        raise ValueError('비표준 잔기 또는 보조인자가 있습니다. 원본을 검토해 지원 가능한 구조를 준비하세요.')
    if any('주사슬 원자 누락' in r['warnings'] for r in a['mapping']):
        raise ValueError('선택한 구조에 주사슬 원자 누락이 있습니다. 구조를 먼저 수선하세요.')
    fp = registry.fingerprint(config)
    id_ = config['id']
    if id_ == 'budealascan' and repeats != 1:
        raise ValueError('BudeAlaScan은 단일 scan으로 실행하세요.')
    if id_ == 'saambe3d':
        saambe.validate(a['groups'], repeats)
    work = [residues] if id_ in ('budealascan', 'saambe3d') else [[r] for r in residues]
    ids = []
    for subset in work:
        for repeat in range(1, repeats + 1):
            payload = {'config': config, 'fingerprint': fp, 'residues': subset, 'repeat': repeat, 'planned_repeats': repeats, 'timeout': timeout, 'validation': validation}
            key = hashlib.sha256(json.dumps([a['id'], id_, fp, [r['key'] for r in subset], repeat, repeats, validation], sort_keys=True).encode()).hexdigest()
            ids.append(store.enqueue(a['id'], id_, payload, key))
    return ids


@app.post('/api/engines/{id_}/validate')
def validate_engine(id_: str):
    if id_ not in registry.IDS:
        raise ValueError('알 수 없는 엔진')
    with store.lock_engines([id_]):
        ensure_no_installation(id_)
        return queue_validation(id_)


def queue_validation(id_):
    config = next((c for c in registry.configs() if c['id'] == id_), None)
    if not config:
        raise ValueError('알 수 없는 엔진')
    registry.fingerprint(config)
    for existing in store.jobs():
        if existing['engine'] == id_ and existing['payload'].get('validation') and existing['status'] in ('queued', 'running'):
            return {'jobs': [existing['id']]}
    store.save('engine', id_, config)
    src = example()
    a = create_analysis(Selection(structure_id=src['id'], group1=['A'], group2=['B'], scan_chains=['A']))
    a['validation'] = True
    store.save('analysis', a['id'], a)
    residue = next(r for r in a['rows'] if r['selected'])
    return {'jobs': enqueue_tasks(a, config, [residue], 1, 1800, validation=True)}


@app.post('/api/analyses/{id_}/run')
def run(id_: str, body: Run):
    with store.lock_engines(registry.IDS):
        a = store.get('analysis', id_)
        if not body.engines or len(set(body.engines)) != len(body.engines) or not set(body.engines) <= set(registry.IDS):
            raise ValueError('실행할 엔진을 선택하세요.')
        if not body.residues or len(set(body.residues)) != len(body.residues):
            raise ValueError('서로 다른 잔기를 선택하세요.')
        residues = [r for r in a['rows'] if r['key'] in body.residues]
        if len(residues) != len(body.residues) or any(not r['eligible'] for r in residues):
            raise ValueError('선택한 분석에서 계산할 수 없는 잔기입니다.')
        if 'flex_ddg' in body.engines and body.engines != ['flex_ddg']:
            raise ValueError('Flex ddG는 별도의 선택 후보 분석으로 실행하세요.')
        configs = {c['id']: c for c in registry.configs()}
        for engine in body.engines:
            ensure_no_installation(engine)
            if configs[engine]['status'] != 'ready':
                raise ValueError(f'{registry.NAMES[engine]}의 실제 시험 계산을 먼저 완료하세요.')
        # Validate everything before registering any tasks.
        if a['blocking_hetero'] or any('주사슬 원자 누락' in r['warnings'] for r in a['mapping']):
            raise ValueError('지원하지 않는 보조인자 또는 주사슬 누락이 있습니다.')
        if 'budealascan' in body.engines and body.repeats != 1:
            raise ValueError('BudeAlaScan은 반복 수 1로 별도 실행하세요.')
        if 'saambe3d' in body.engines:
            saambe.validate(a['groups'], body.repeats)
        jobs = []
        for engine in body.engines:
            jobs.extend(enqueue_tasks(a, configs[engine], residues, body.repeats, body.timeout))
        return {'jobs': jobs}


@app.get('/api/jobs')
def job_list(analysis_id: Optional[str] = None):
    return store.jobs(analysis_id)


@app.post('/api/jobs/{id_}/cancel')
def cancel(id_: str):
    j = store.job(id_)
    if j['status'] == 'queued':
        store.update_job(id_, cancel=1, status='cancelled')
    elif j['status'] == 'running':
        store.update_job(id_, cancel=1)
    return store.job(id_)


@app.post('/api/jobs/{id_}/retry')
def retry(id_: str):
    j = store.job(id_)
    if j['status'] not in ('failed', 'cancelled'):
        raise HTTPException(409, '실패하거나 취소한 작업만 재시도할 수 있습니다.')
    if j['pid']:
        try:
            os.kill(j['pid'], 0)
        except ProcessLookupError:
            pass
        else:
            raise HTTPException(409, '이전 계산 프로세스가 살아 있습니다. 종료를 확인한 뒤 재시도하세요.')
    with store.lock_engines([j['engine']]):
        ensure_no_installation(j['engine'])
        if j['payload'].get('install'):
            ensure_engine_idle(j['engine'])
        elif registry.fingerprint(j['payload']['config']) != j['payload']['fingerprint']:
            raise ValueError('엔진 변경: 다시 검증한 뒤 새 분석을 실행하세요.')
        return {'jobs': [store.enqueue(j['analysis_id'], j['engine'], j['payload'], 'retry-' + j['id'])]}


@app.get('/api/jobs/{id_}/logs')
def logs(id_: str):
    store.job(id_)
    folder = store.DATA / 'jobs' / id_
    return {'text': '\n\n'.join('── ' + p.name + ' ──\n' + p.read_text(errors='replace')[-20000:] for p in sorted(folder.glob('*.log')))[-80000:]}


@app.get('/api/runtime')
def runtime():
    try:
        return store.get('settings', 'runtime')
    except KeyError:
        return {'concurrency': 1}


@app.put('/api/runtime')
def runtime_set(body: Runtime):
    store.save('settings', 'runtime', body.model_dump())
    return body


@app.put('/api/analyses/{id_}/threshold')
def threshold_set(id_: str, body: Threshold):
    a = store.get('analysis', id_)
    units = analytics.UNITS
    if body.engine not in units or (body.value is not None and (body.value <= 0 or body.unit != units[body.engine] or not body.evidence.strip())):
        raise ValueError('양수 임계값, 엔진 단위 및 검증 근거가 필요합니다.')
    completed = [j for j in store.jobs(id_) if j['engine'] == body.engine and j['status'] == 'succeeded']
    if body.value is not None and not completed:
        raise ValueError('해당 엔진의 계산 결과가 나온 뒤 프로토콜에 맞는 판정 기준을 저장하세요.')
    a['thresholds'][body.engine] = {**body.model_dump(), 'fingerprint': completed[-1]['payload']['fingerprint'] if completed else None}
    store.save('analysis', id_, a)
    return a


def results(id_):
    a, jobs_ = store.get('analysis', id_), store.jobs(id_)
    output = []
    for row in a['rows']:
        scores = {}
        for engine in registry.IDS:
            relevant = [j for j in jobs_ if j['engine'] == engine and row['key'] in [r['key'] for r in j['payload']['residues']]]
            if not relevant:
                continue
            # Latest configuration/repeat plan only; retries replace the same repetition.
            latest = relevant[-1]['payload']
            relevant = [j for j in relevant if j['payload']['fingerprint'] == latest['fingerprint'] and j['payload']['planned_repeats'] == latest['planned_repeats']]
            reps = {j['payload']['repeat']: j for j in relevant}
            values = []
            for j in reps.values():
                if j['status'] == 'succeeded':
                    values.extend(r for r in j['result'] if r['key'] == row['key'])
            statuses = [j['status'] for j in reps.values()]
            unit = values[0]['unit'] if values else None
            if any(v['unit'] != unit for v in values):
                raise ValueError('서로 다른 점수 단위가 한 실행에 포함되었습니다.')
            # Older runs used binary subtraction on the same printed decimal energies.
            numbers = [
                engines.binding_difference(v['mutant_binding'], v['wt_binding'])
                if engine in ('foldx', 'evoef') and 'mutant_binding' in v and 'wt_binding' in v
                else v['value']
                for v in values
            ]
            score = {'value': statistics.mean(numbers) if numbers else None, 'sd': statistics.stdev(numbers) if len(numbers) > 1 else None, 'unit': unit, 'completed': len(numbers), 'planned': latest['planned_repeats'], 'statuses': statuses, 'details': values, 'jobs': [j['id'] for j in reps.values()], 'fingerprint': latest['fingerprint'], 'support': None}
            threshold = a['thresholds'].get(engine)
            complete = len(numbers) == latest['planned_repeats'] and all(s == 'succeeded' for s in statuses)
            if complete and threshold and threshold['value'] is not None and threshold['unit'] == unit and threshold.get('fingerprint') == latest['fingerprint']:
                score['support'] = score['value'] >= threshold['value']
            scores[engine] = score
        supports = [s['support'] for s in scores.values() if s['support'] is not None]
        output.append({**row, 'scores': scores, 'support_count': sum(supports), 'eligible_count': len(supports), 'selected_count': len(scores), 'consensus': len(supports) >= 2 and sum(supports) / len(supports) >= 2/3, 'provisional': any(any(st != 'succeeded' for st in s['statuses']) for s in scores.values())})
    return {'rows': output, 'jobs': jobs_, 'thresholds': a['thresholds']}


@app.get('/api/analyses/{id_}/analytics')
def analysis_analytics(id_: str, engines: Optional[List[str]] = Query(default=None), top_k: int = Query(default=10, ge=1)):
    selected = [] if engines == [''] else engines
    return analytics.summarize(id_, results(id_), selected, top_k)


@app.get('/api/analyses/{id_}/analytics.csv')
def analysis_analytics_csv(id_: str, engines: Optional[List[str]] = Query(default=None), top_k: int = Query(default=10, ge=1)):
    report = analysis_analytics(id_, engines, top_k)
    return Response(analytics.comparison_csv(report), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="comparison.csv"'})


@app.get('/api/analyses/{id_}/results')
def get_results(id_: str):
    return results(id_)


def csv_data(id_):
    buf = io.StringIO()
    fields = ['chain', 'number', 'icode', 'wt', 'engine', 'value', 'unit', 'sd', 'completed', 'planned', 'status', 'support']
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for r in results(id_)['rows']:
        for e in registry.IDS:
            s = r['scores'].get(e, {})
            writer.writerow({**{k: r[k] for k in ('chain', 'number', 'icode', 'wt')}, 'engine': e, **{k: s.get(k) for k in ('value', 'unit', 'sd', 'completed', 'planned', 'support')}, 'status': '/'.join(s.get('statuses', ['not_selected']))})
    return '\ufeff' + buf.getvalue()


@app.get('/api/analyses/{id_}/export.csv')
def export_csv(id_: str):
    return Response(csv_data(id_), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="hotspots.csv"'})


@app.get('/api/analyses/{id_}/export.zip')
def export_zip(id_: str):
    a = store.get('analysis', id_)
    zip_path = store.DATA / 'analyses' / id_ / 'export.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('analysis.json', json.dumps(a, ensure_ascii=False, indent=2))
        z.writestr('results.json', json.dumps(results(id_), ensure_ascii=False, indent=2))
        z.writestr('results.csv', csv_data(id_))
        mapbuf = io.StringIO()
        fields = ['key', 'chain', 'number', 'icode', 'wt', 'altloc', 'engine_chain', 'engine_number']
        writer = csv.DictWriter(mapbuf, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(a['mapping'])
        z.writestr('residue_mapping.csv', mapbuf.getvalue())
        z.write(store.DATA / 'structures' / a['input']['structure_id'] / 'original.pdb', 'original.pdb')
        z.write(store.DATA / 'analyses' / id_ / 'normalized.pdb', 'normalized.pdb')
        hashes = {}
        for j in store.jobs(id_):
            for p in (store.DATA / 'jobs' / j['id']).rglob('*'):
                if p.is_file() and not p.is_symlink():
                    name = 'jobs/' + j['id'] + '/' + str(p.relative_to(store.DATA / 'jobs' / j['id']))
                    digest = hashlib.sha256()
                    remaining = p.stat().st_size
                    with p.open('rb') as source, z.open(name, 'w') as dest:
                        while remaining:
                            chunk = source.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                break
                            dest.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                    hashes[name] = digest.hexdigest()
        z.writestr('file_hashes.json', json.dumps(hashes, indent=2))
    return FileResponse(zip_path, filename='hotspotfinder-' + id_[:8] + '.zip')


DIST = store.ROOT / 'frontend/dist'
if DIST.exists():
    app.mount('/', StaticFiles(directory=DIST, html=True), name='ui')
