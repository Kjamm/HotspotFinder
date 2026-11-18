"""Small SQLite repository shared by the API and its independent worker."""
import json
import fcntl
import os
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager, ExitStack

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('HOTSPOT_DATA', ROOT / '.hotspotfinder')).resolve()


def uid():
    return uuid.uuid4().hex


@contextmanager
def lock_engines(ids):
    """Serialize configuration, installation, and queue changes across processes."""
    folder = DATA / 'locks'
    folder.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        for id_ in sorted(set(ids)):
            handle = stack.enter_context((folder / (id_ + '.lock')).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / 'state.sqlite', timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


def init():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS documents (kind TEXT, id TEXT, value TEXT NOT NULL, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, analysis_id TEXT, engine TEXT, status TEXT NOT NULL, cancel INTEGER DEFAULT 0, pid INTEGER, created REAL, updated REAL, payload TEXT, result TEXT, error TEXT, dedupe TEXT UNIQUE);
        ''')


def save(kind, id_, value):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?)', (kind, id_, json.dumps(value, allow_nan=False)))


def get(kind, id_):
    with connect() as c:
        row = c.execute('SELECT value FROM documents WHERE kind=? AND id=?', (kind, id_)).fetchone()
    if row is None:
        raise KeyError(id_)
    return json.loads(row[0])


def listing(kind):
    with connect() as c:
        return [json.loads(r[0]) for r in c.execute('SELECT value FROM documents WHERE kind=? ORDER BY rowid DESC', (kind,))]


def job_dict(row):
    if row is None:
        raise KeyError('job')
    d = dict(row)
    d['payload'] = json.loads(d['payload'])
    d['result'] = json.loads(d['result']) if d['result'] else None
    return d


def job(id_):
    with connect() as c:
        return job_dict(c.execute('SELECT * FROM jobs WHERE id=?', (id_,)).fetchone())


def jobs(analysis_id=None):
    with connect() as c:
        rows = c.execute('SELECT * FROM jobs WHERE analysis_id=? ORDER BY created', (analysis_id,)) if analysis_id else c.execute('SELECT * FROM jobs ORDER BY created DESC')
        return [job_dict(r) for r in rows]


def enqueue(analysis_id, engine, payload, dedupe):
    id_, now = uid(), time.time()
    with connect() as c:
        c.execute('INSERT OR IGNORE INTO jobs(id,analysis_id,engine,status,created,updated,payload,dedupe) VALUES (?,?,?,?,?,?,?,?)', (id_, analysis_id, engine, 'queued', now, now, json.dumps(payload), dedupe))
        return c.execute('SELECT id FROM jobs WHERE dedupe=?', (dedupe,)).fetchone()[0]


def update_job(id_, **fields):
    allowed = {'status', 'cancel', 'pid', 'result', 'error', 'dedupe'}
    assert set(fields) <= allowed
    if 'result' in fields:
        fields['result'] = json.dumps(fields['result'], allow_nan=False)
    fields['updated'] = time.time()
    with connect() as c:
        c.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), id_))


def claim():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute("SELECT * FROM jobs WHERE status='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
        if row is None:
            return None
        c.execute("UPDATE jobs SET status='running', updated=? WHERE id=?", (time.time(), row['id']))
        return job_dict(row)
