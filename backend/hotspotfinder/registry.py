"""Dispatch to separately fingerprinted engine implementations."""
import platform
from . import engines, saambe, store

IDS = (*engines.IDS, 'saambe3d')
NAMES = {**engines.NAMES, 'saambe3d': saambe.NAME}


def configs():
    try:
        config = store.get('engine', 'saambe3d')
    except KeyError:
        config = dict(id='saambe3d', executable='', data_dir='', image='', version='',
                      status='not_installed', validation=None)
    if config['status'] == 'ready':
        try:
            valid = saambe.fingerprint(config) == config.get('fingerprint')
        except ValueError:
            valid = False
        if not valid:
            config['status'] = 'needs_validation'
    return [*engines.configs(), {**config, 'name': saambe.NAME, 'platform': f'{platform.system()}-{platform.machine()}'}]


def fingerprint(config):
    return saambe.fingerprint(config) if config['id'] == 'saambe3d' else engines.fingerprint(config)


def execute(engine, config, analysis, residues, repeat, runner, smoke=False):
    if engine == 'saambe3d':
        return saambe.execute(config, analysis, residues, runner)
    return engines.execute(engine, config, analysis, residues, repeat, runner, smoke)
