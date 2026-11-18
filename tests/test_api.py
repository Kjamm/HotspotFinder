import io
import json
import zipfile
import pytest
from hotspotfinder import store,engines
from hotspotfinder.app import results

def test_upload_selection_and_exports(client,analysis):
    a=analysis
    assert any(r['selected'] for r in a['rows'])
    assert client.get('/api/analyses/'+a['id']+'/pdb').status_code==200
    csv=client.get('/api/analyses/'+a['id']+'/export.csv').text
    assert 'not_selected' in csv
    z=zipfile.ZipFile(io.BytesIO(client.get('/api/analyses/'+a['id']+'/export.zip').content))
    assert {'original.pdb','normalized.pdb','residue_mapping.csv','analysis.json','results.json'}<=set(z.namelist())
    assert json.loads(z.read('results.json'))['rows'][0]['eligible_count']==0

def test_unknown_and_malformed_requests(client):
    assert client.get('/api/analyses/does-not-exist').status_code==404
    assert client.post('/api/structures',json={'name':'x.pdb','pdb':'garbage'}).status_code==422
    assert client.post('/api/example',headers={'X-Hotspot-Client':''}).status_code==403
    assert client.post('/api/example',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==403

def test_unavailable_engines_do_not_make_predictions(client,analysis):
    row=next(r for r in analysis['rows'] if r['selected'])
    response=client.post('/api/analyses/'+analysis['id']+'/run',json={'engines':['foldx'],'residues':[row['key']]})
    assert response.status_code==422
    assert store.jobs(analysis['id'])==[]
    assert all(not r['scores'] for r in results(analysis['id'])['rows'])

def test_validation_invalidation(tmp_path,client):
    exe=tmp_path/'engine';exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o755)
    body={'executable':str(exe),'version':'test'}
    assert client.put('/api/engines/foldx',json=body).status_code==200
    c=store.get('engine','foldx');c['status']='ready';store.save('engine','foldx',c)
    assert next(e for e in engines.configs() if e['id']=='foldx')['status']=='ready'
    exe.write_text('#!/bin/sh\nexit 1\n')
    assert next(e for e in engines.configs() if e['id']=='foldx')['status']=='needs_validation'

def payload(row,repeat=1):
    return {'residues':[row],'repeat':repeat,'planned_repeats':2,'fingerprint':'test-fixture','config':{}}

def test_dedup_cancel_and_missing_results(client,analysis):
    row=next(r for r in analysis['rows'] if r['selected'])
    j=store.enqueue(analysis['id'],'foldx',payload(row),'unique')
    assert store.enqueue(analysis['id'],'foldx',payload(row),'unique')==j
    assert client.post('/api/jobs/'+j+'/cancel').json()['status']=='cancelled'
    result=next(r for r in results(analysis['id'])['rows'] if r['key']==row['key'])
    assert result['scores']['foldx']['value'] is None
    assert result['eligible_count']==0 and not result['consensus']

def test_retries_replace_repeat_and_partial_not_vote(client,analysis):
    row=next(r for r in analysis['rows'] if r['selected'])
    a=analysis;a['thresholds']={'foldx':{'value':2,'unit':'kcal/mol','evidence':'fixture','fingerprint':'test-fixture'}};store.save('analysis',a['id'],a)
    j=store.enqueue(a['id'],'foldx',payload(row),'1')
    store.update_job(j,status='succeeded',result=[{'key':row['key'],'value':4,'unit':'kcal/mol'}])
    out=next(r for r in results(a['id'])['rows'] if r['key']==row['key'])
    assert out['scores']['foldx']['value']==4 and out['eligible_count']==0
    j2=store.enqueue(a['id'],'foldx',payload(row,2),'2')
    store.update_job(j2,status='failed',error='fixture')
    j3=store.enqueue(a['id'],'foldx',payload(row,2),'retry')
    store.update_job(j3,status='succeeded',result=[{'key':row['key'],'value':2,'unit':'kcal/mol'}])
    out=next(r for r in results(a['id'])['rows'] if r['key']==row['key'])
    assert out['scores']['foldx']['value']==3 and out['scores']['foldx']['completed']==2
    assert out['support_count']==1 and out['eligible_count']==1 and not out['consensus']

def test_threshold_requires_units_evidence_and_finite(client,analysis):
    url='/api/analyses/'+analysis['id']+'/threshold'
    assert client.put(url,json={'engine':'flex_ddg','value':2,'unit':'kcal/mol','evidence':'x'}).status_code==422
    assert client.put(url,json={'engine':'foldx','value':2,'unit':'kcal/mol','evidence':''}).status_code==422
    assert client.put(url,json={'engine':'foldx','value':2,'unit':'kcal/mol','evidence':'validated local benchmark'}).status_code==422
    row=next(r for r in analysis['rows'] if r['selected'])
    j=store.enqueue(analysis['id'],'foldx',payload(row),'threshold-fixture')
    store.update_job(j,status='succeeded',result=[{'key':row['key'],'value':4,'unit':'kcal/mol'}])
    response=client.put(url,json={'engine':'foldx','value':2,'unit':'kcal/mol','evidence':'validated local benchmark'})
    assert response.status_code==200
    assert response.json()['thresholds']['foldx']['fingerprint']=='test-fixture'
