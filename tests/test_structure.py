import pytest
from hotspotfinder import structure

def atom(serial, chain, number, x, name='CA', res='SER', icode=' ', alt=' ', occ=1):
    return f'ATOM  {serial:5d} {name:^4s}{alt}{res:3s} {chain}{number:4d}{icode}   {x:8.3f}{0.:8.3f}{0.:8.3f}{occ:6.2f}{10.:6.2f}           C\n'

def residue(start, chain, number, x, **kwargs):
    return ''.join(atom(start+i, chain, number, x, name=n, **kwargs) for i,n in enumerate(('N','CA','C','O','CB')))

def test_chain_insertion_negative_and_cutoff():
    pdb=residue(1,'A',-1,0)+residue(6,'A',100,0)+residue(11,'A',100,20,icode='A')+residue(16,'B',100,5)
    p=structure.prepare(pdb,0,['A'],['B'],['A'],5)
    assert [r['key'] for r in p['rows']]==['0|A|-1|','0|A|100|','0|A|100|A']
    assert [r['interface'] for r in p['rows']]==[True,True,False]
    assert [r['engine_number'] for r in p['rows']]==[1,102,103]
    assert len(structure.read_pdb(p['pdb'])[0][0]['residues'])==4
    assert not structure.prepare(pdb,0,['A'],['B'],['A'],4.99)['rows'][0]['interface']

def test_no_model_mixing():
    pdb='MODEL        1\n'+residue(1,'A',1,0)+residue(6,'B',1,5)+'ENDMDL\nMODEL        2\n'+residue(1,'A',1,0)+residue(6,'B',1,10)+'ENDMDL\n'
    assert structure.prepare(pdb,0,['A'],['B'],['A'],5)['rows'][0]['interface']
    assert not structure.prepare(pdb,1,['A'],['B'],['A'],5)['rows'][0]['interface']

def test_same_residue_altloc_is_consistent():
    pdb=''.join(atom(i+1,'A',1,0,name=n,alt='A',occ=.7) + atom(i+20,'A',1,30,name=n,alt='B',occ=.3) for i,n in enumerate(('N','CA','C','O','CB')))+residue(50,'B',1,5)
    p=structure.prepare(pdb,0,['A'],['B'],['A'],5)
    assert p['rows'][0]['altloc']=='A'
    assert p['rows'][0]['interface']
    assert len([l for l in p['pdb'].splitlines() if l.startswith('ATOM')])==10

def test_alanine_glycine_and_missing_backbone():
    pdb=residue(1,'A',1,0,res='ALA')+residue(6,'A',2,0,res='GLY')+atom(11,'A',3,0)+residue(12,'B',1,3)
    a=structure.prepare(pdb,0,['A'],['B'],['A'],5)
    assert [r['eligible'] for r in a['rows']]==[False,False,False]
    assert structure.prepare(pdb,0,['A'],['B'],['A'],5,True)['rows'][1]['eligible']

@pytest.mark.parametrize('g1,g2,scan', [(['A'],['A'],['A']),([],['B'],['B']),(['A'],['Z'],['A']),(['A'],['B'],['Z'])])
def test_invalid_partner_selection(g1,g2,scan):
    with pytest.raises(ValueError):
        structure.prepare(residue(1,'A',1,0)+residue(6,'B',1,5),0,g1,g2,scan,5)

def test_invalid_input():
    with pytest.raises(ValueError):
        structure.inspect('not a PDB')
