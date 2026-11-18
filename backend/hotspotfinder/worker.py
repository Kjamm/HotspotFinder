"""Independent queue consumer. Work survives browser navigation and reloads."""
import concurrent.futures
import fcntl
import json
import signal
import sys
import time
import traceback
from . import store, engines, installers, registry

STOP = False


def process(job):
    id_, payload = job['id'], job['payload']
    directory = store.DATA / 'jobs' / id_
    try:
        runner = engines.Runner(directory, id_, payload['timeout'], lambda: STOP)
        if payload.get('install'):
            install(job, runner)
            return
        if registry.fingerprint(payload['config']) != payload['fingerprint']:
            raise ValueError('엔진 또는 의존 파일이 변경되었습니다. 다시 검증하세요.')
        analysis = store.get('analysis', job['analysis_id'])
        result = registry.execute(job['engine'], payload['config'], analysis, payload['residues'], payload['repeat'], runner, payload.get('validation', False))
        runner.check()
        manifest = {'engine': job['engine'], 'fingerprint': payload['fingerprint'], 'config': payload['config'], 'repeat': payload['repeat'], 'input_hash': analysis['normalized_hash'], 'result': result}
        (directory / 'result.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))
        with store.lock_engines([job['engine']]):
            if payload.get('validation'):
                config = store.get('engine', job['engine'])
                if registry.fingerprint(config) == payload['fingerprint']:
                    config.pop('error', None)
                    config.update(status='ready', fingerprint=payload['fingerprint'], validation={'job_id': id_, 'time': time.time(), 'kind': 'functional_smoke_test', 'note': '실제 입력·실행·파싱 통과. 예측 정확도는 별도 평가가 필요합니다.'})
                    store.save('engine', job['engine'], config)
            store.update_job(id_, status='succeeded', result=result)
    except engines.Cancelled as exc:
        store.update_job(id_, status='cancelled', error=str(exc))
    except Exception as exc:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'error.log').write_text(traceback.format_exc())
        with store.lock_engines([job['engine']]):
            if payload.get('validation'):
                config = store.get('engine', job['engine'])
                if config.get('status') != 'ready':
                    config.update(status='failed', error=str(exc), validation={'job_id': id_, 'time': time.time()})
                    store.save('engine', job['engine'], config)
            store.update_job(id_, status='failed', error=str(exc))


def install(job, runner):
    from .app import queue_validation

    engine = job['engine']
    destination = runner.directory / 'engine'
    if engine == 'saambe3d':
        runner.run([sys.executable, str(store.ROOT / 'scripts/install_saambe.py'), str(destination)], 'install.log')
        revision = json.loads((store.ROOT / 'third_party/sources.json').read_text())[engine]['commit']
        config = dict(id=engine, executable=str(destination / 'env/bin/python'), data_dir=str(destination / 'source'),
                      image='', version=revision, status='needs_validation', validation=None)
    elif engine == 'evoef':
        runner.run([sys.executable, str(store.ROOT / 'scripts/install_evoef.py'), '--destination', str(destination)], 'install.log')
        revision = json.loads((store.ROOT / 'third_party/sources.json').read_text())['evoef']['commit']
        config = {'id': engine, 'executable': str(destination / 'EvoEF'), 'data_dir': '', 'image': '', 'version': '1.1 ' + revision, 'status': 'needs_validation', 'validation': None}
    else:
        config = installers.install_archive(engine, job['payload']['archive'], destination, runner.check)
        (runner.directory / 'install.log').write_text('배포 파일 압축 해제 및 실행 파일 연결 완료\n' + config['executable'])
    runner.check()
    config['fingerprint'] = registry.fingerprint(config)
    with store.lock_engines([engine]):
        runner.check()
        store.save('engine', engine, config)
        validation = queue_validation(engine)
        store.update_job(job['id'], status='succeeded', result={'installation': 'complete', 'validation_jobs': validation['jobs']})


def main():
    global STOP
    store.init()
    lock = (store.DATA / 'worker.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    # A crashed run is never silently restarted or merged with new results.
    with store.connect() as c:
        c.execute("UPDATE jobs SET status='failed', error='Worker 중단: 로그를 확인하고 재시도하세요.', updated=? WHERE status='running'", (time.time(),))
    def stop(*_):
        global STOP
        STOP = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        active = []
        while not STOP:
            active = [f for f in active if not f.done()]
            try:
                limit = store.get('settings', 'runtime')['concurrency']
            except KeyError:
                limit = 1
            while len(active) < limit:
                job = store.claim()
                if not job:
                    break
                active.append(pool.submit(process, job))
            time.sleep(.3)
    lock.close()


if __name__ == '__main__':
    main()
