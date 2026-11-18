import json
import sqlite3
import sys
import pytest
from hotspotfinder.engines import evoef_score, foldx_score, flex_score, bude_scores, Runner, Cancelled

def test_evoef_does_not_accept_stability_or_nan():
    assert evoef_score('Binding energy details between chain(s) A and chain(s) B:\nTotal = -37.29\n') == -37.29
    for text in ('Total = -37.29', 'Binding energy details between chain(s) A\nTotal = nan', 'Binding energy details between chain(s) A\nTotal = 2\nTotal = 3'):
        with pytest.raises(ValueError):
            evoef_score(text)

def test_foldx_header_and_group_selection(tmp_path):
    p=tmp_path/'Interaction.fxout'
    p.write_text('FoldX report\nPdb\tGroup1\tGroup2\tInteraction Energy\nwt.pdb\tA\tBC\t-12.3\nwt.pdb\tA\tD\t-5.0\n')
    assert foldx_score(p,[['A'],['B','C']])==-12.3
    assert foldx_score(p,[['B','C'],['A']])==-12.3
    with pytest.raises(ValueError):
        foldx_score(p,[['A'],['Z']])
    p.write_text('Pdb\tTotal Energy\nwt\t-42\n')
    with pytest.raises(ValueError):
        foldx_score(p,[['A'],['B']])

def make_flex_db(path, incomplete=False):
    with sqlite3.connect(path) as c:
        c.executescript('CREATE TABLE batches(batch_id,name); CREATE TABLE score_types(batch_id,score_type_id,score_type_name); CREATE TABLE structure_scores(batch_id,struct_id,score_type_id,score_value); CREATE TABLE score_function_method_options(batch_id,score_function_name);')
        for i,(name,val) in enumerate([('bound_wt',-20),('unbound_wt',-10),('bound_mut',-16),('unbound_mut',-9)],1):
            c.execute('INSERT INTO batches VALUES (?,?)',(i,name+'_dbreport'))
            c.execute('INSERT INTO score_types VALUES (?,?,?)',(i,1,'total_score'))
            c.execute('INSERT INTO score_function_method_options VALUES (?,?)',(i,'talaris2014'))
            c.execute('INSERT INTO structure_scores VALUES (?,?,?,?)',(i,i,1,100*val))
            if not(incomplete and i==4):
                c.execute('INSERT INTO structure_scores VALUES (?,?,?,?)',(i,i+4,1,val))

def test_flex_final_checkpoint_only(tmp_path):
    p=tmp_path/'ddG.db3';make_flex_db(p)
    value,details=flex_score(p)
    assert value==3
    assert details['checkpoint_index']==1

def test_flex_incomplete_final_not_previous_checkpoint(tmp_path):
    p=tmp_path/'ddG.db3';make_flex_db(p,True)
    with pytest.raises(ValueError): flex_score(p)

def test_bude_mapping_units_and_missing(tmp_path):
    p=tmp_path/'scan.json';p.write_text(json.dumps({'ala_scan':[{'dG':-100,'1':[10,'SER','B',8.368,2,0]}]}))
    r={'key':'0|X|100|A','engine_chain':'B','engine_number':10,'wt':'S','name':'SER'}
    result=bude_scores([p],[r])[0]
    assert result['key']==r['key'] and result['value']==2
    assert result['raw_unit']=='kJ/mol'
    with pytest.raises(ValueError): bude_scores([p,p],[r])
    with pytest.raises(ValueError): bude_scores([p],[{**r,'engine_number':11}])

def test_runner_nonzero_and_cancel(tmp_path):
    runner=Runner(tmp_path)
    with pytest.raises(RuntimeError):runner.run([sys.executable,'-c','raise SystemExit(2)'])
    runner=Runner(tmp_path,stopped=lambda:True)
    with pytest.raises(Cancelled):runner.run([sys.executable,'-c','print(1)'])

def test_runner_timeout_kills_child(tmp_path):
    runner=Runner(tmp_path,timeout=.2)
    with pytest.raises(TimeoutError):runner.run([sys.executable,'-c','import time; time.sleep(20)'])
