#!/usr/bin/env python3
"""Live API smoke test against an already-running local server and installed EvoEF."""
import json
import sys
import os
import re
import time
import zipfile
import io
import subprocess
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
with httpx.Client(base_url='http://127.0.0.1:8765',headers={'X-Hotspot-Client':'local-ui'},timeout=60) as c:
    def request(method,path,**kw):
        r=c.request(method,path,**kw);r.raise_for_status();return r
    assert request('GET','/api/health').json()['local_only']
    html=request('GET','/').text
    for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"',html):
        assert request('GET',asset).content
    if '--install' in sys.argv:
        installation = request('POST', '/api/engines/evoef/install').json()['jobs'][0]
        pending = [installation]
        for _ in range(600):
            entries = {j['id']: j for j in request('GET', '/api/jobs').json()}
            installed = entries[installation]
            if installed['status'] == 'succeeded':
                pending = [installation, *installed['result']['validation_jobs']]
            if any(entries[j]['status'] in ('failed', 'cancelled') for j in pending):
                raise AssertionError([entries[j] for j in pending])
            if len(pending) > 1 and all(entries[j]['status'] == 'succeeded' for j in pending):
                break
            time.sleep(.5)
        else:
            raise AssertionError('Automatic installation timed out')
        print('Automatic installation and functional validation passed', flush=True)
    engines=request('GET','/api/engines').json()
    evo=next(e for e in engines if e['id']=='evoef')
    if evo['status']!='ready':
        jobs=request('POST','/api/engines/evoef/validate').json()['jobs']
        for _ in range(180):
            entries={j['id']:j for j in request('GET','/api/jobs').json()}
            if all(entries[j]['status'] in ('succeeded','failed','cancelled') for j in jobs):break
            time.sleep(.5)
        assert all(entries[j]['status']=='succeeded' for j in jobs), entries[jobs[0]].get('error')
    source=request('POST','/api/example').json()
    a=request('POST','/api/analyses',json={'structure_id':source['id'],'group1':['A'],'group2':['B'],'scan_chains':['A'],'cutoff':5}).json()
    candidates=[r for r in a['rows'] if r['selected']][:2]
    body={'engines':['evoef'],'residues':[r['key'] for r in candidates],'repeats':1}
    ids=request('POST',f'/api/analyses/{a["id"]}/run',json=body).json()['jobs']
    assert request('POST',f'/api/analyses/{a["id"]}/run',json=body).json()['jobs']==ids
    for _ in range(180):
        res=request('GET',f'/api/analyses/{a["id"]}/results').json()
        if all(j['status'] in ('succeeded','failed','cancelled') for j in res['jobs']):break
        time.sleep(.5)
    assert all(j['status']=='succeeded' for j in res['jobs']),res['jobs']
    # Independent direct invocation over the same paired structures verifies adapter values.
    comparisons=[]
    for job in res['jobs']:
        directory=Path(os.environ.get('HOTSPOT_DATA', root / '.hotspotfinder'))/'jobs'/job['id']
        mutant=next(p for p in directory.glob('input_Repair_Model_*.pdb') if not p.stem.endswith('_WT'))
        wildtype=mutant.with_name(mutant.stem+'_WT.pdb')
        scores=[]
        for pdb in (wildtype,mutant):
            output=subprocess.check_output([evo['executable'],'--command=ComputeBinding',f'--pdb={pdb.name}','--split=A,B'],cwd=directory,text=True)
            scores.append(float(re.findall(r'^Total\s*=\s*([-+\d.]+)\s*$',output,re.M)[0]))
        expected=scores[1]-scores[0]
        actual=job['result'][0]['value']
        assert abs(expected-actual)<1e-10
        comparisons.append({'residue':job['payload']['residues'][0]['key'],'direct':expected,'app':actual,'unit':'EvoEF score'})
    archive=request('GET',f'/api/analyses/{a["id"]}/export.zip').content
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert 'residue_mapping.csv' in z.namelist()
        assert any(name.endswith('result.json') for name in z.namelist())
        import hashlib
        for path,digest in json.loads(z.read('file_hashes.json')).items():
            assert hashlib.sha256(z.read(path)).hexdigest()==digest
    print(json.dumps({'analysis_id':a['id'],'jobs':len(ids),'duplicate_submission':'deduplicated','static_assets':'HTTP 200','export':'verified ZIP and hashes','comparisons':comparisons},indent=2))
