"""PDB validation, residue identity, conformer selection and interface geometry."""
import io
import math
import string
import warnings
from pathlib import Path

import numpy as np
from Bio.PDB import PDBParser, NeighborSearch
from Bio.Data.IUPACData import protein_letters_3to1

AA = {k.upper(): v for k, v in protein_letters_3to1.items()}


def read_pdb(text):
    if not text.strip() or len(text.encode()) > 20_000_000:
        raise ValueError('PDB가 비어 있거나 20 MB를 초과합니다.')
    with warnings.catch_warnings(record=True) as messages:
        structure = PDBParser(PERMISSIVE=False, QUIET=False).get_structure('input', io.StringIO(text))
    models = []
    for mi, model in enumerate(structure):
        residues, hetero = [], []
        for chain in model:
            for residue in chain:
                if residue.is_disordered() == 2:
                    raise ValueError('동일 위치의 서로 다른 잔기 conformer는 먼저 명시적으로 정리해 주세요.')
                if residue.id[0] != ' ' or residue.resname not in AA:
                    hetero.append({'chain': chain.id, 'number': residue.id[1], 'name': residue.resname})
                    continue
                # A single conformer for the entire residue; blank-altloc atoms are shared.
                unpacked = residue.get_unpacked_list()
                alternatives = sorted({a.altloc for a in unpacked if a.altloc != ' '})
                alt = max(alternatives, key=lambda k: (sum((a.occupancy or 0) for a in unpacked if a.altloc == k), k == 'A')) if alternatives else ' '
                atoms = [a for a in unpacked if a.altloc in (' ', alt) and (a.occupancy is None or a.occupancy > 0) and a.element not in ('H', 'D')]
                if not atoms:
                    continue
                if any(not np.isfinite(a.coord).all() for a in atoms):
                    raise ValueError('유한하지 않은 원자 좌표가 있습니다.')
                names = {a.name for a in atoms}
                notes = []
                if alternatives:
                    notes.append(f'altloc {alt} 선택 (잔기 occupancy 합 기준)')
                if not {'N', 'CA', 'C', 'O'}.issubset(names):
                    notes.append('주사슬 원자 누락')
                if residue.resname == 'PRO':
                    notes.append('Pro: 주사슬 구조 변화 가능')
                if residue.resname == 'CYS':
                    notes.append('Cys: 이황화결합 여부 확인 필요')
                key = f'{mi}|{chain.id}|{residue.id[1]}|{residue.id[2].strip()}'
                residues.append({'key': key, 'chain': chain.id, 'number': residue.id[1], 'icode': residue.id[2].strip(), 'name': residue.resname, 'wt': AA[residue.resname], 'altloc': alt.strip(), 'warnings': notes, '_atoms': atoms})
        if residues:
            models.append({'index': mi, 'serial': model.serial_num, 'residues': residues, 'hetero': hetero})
    if not models:
        raise ValueError('표준 단백질 ATOM 좌표를 찾을 수 없습니다. mmCIF는 지원하지 않습니다.')
    return models, list(dict.fromkeys(str(x.message) for x in messages))[:20]


def inspect(text):
    models, warnings_ = read_pdb(text)
    return {'models': [{'index': m['index'], 'serial': m['serial'], 'chains': [{'id': c, 'count': sum(r['chain'] == c for r in m['residues'])} for c in dict.fromkeys(r['chain'] for r in m['residues'])], 'hetero': m['hetero']} for m in models], 'warnings': warnings_}


def prepare(text, model_index, group1, group2, scan_chains, cutoff, include_gly=False):
    if not math.isfinite(cutoff) or not 2 <= cutoff <= 12:
        raise ValueError('거리 cutoff는 2–12 Å 범위여야 합니다.')
    models, notes = read_pdb(text)
    model = next((m for m in models if m['index'] == model_index), None)
    if model is None:
        raise ValueError('선택한 모델이 없습니다.')
    groups = [set(group1), set(group2)]
    all_chains = {r['chain'] for r in model['residues']}
    if not all(groups) or groups[0] & groups[1] or not (groups[0] | groups[1]) <= all_chains:
        raise ValueError('존재하는 서로 겹치지 않는 두 파트너 그룹을 선택하세요.')
    if not scan_chains or not set(scan_chains) <= (groups[0] | groups[1]):
        raise ValueError('분석 체인은 선택한 파트너에 포함되어야 합니다.')
    selected = [r for r in model['residues'] if r['chain'] in groups[0] | groups[1]]
    chain_map = {c: string.ascii_uppercase[i] for i, c in enumerate(sorted(groups[0] | groups[1]))} if len(groups[0] | groups[1]) <= 26 else None
    if chain_map is None:
        raise ValueError('최대 26개 체인을 지원합니다.')
    mapping, pdb, counts, previous, serial = [], [], {}, {}, 1
    for r in selected:
        c = r['chain']
        increment = max(1, r['number'] - previous[c]) if c in previous else 1
        if increment > 1:
            r['warnings'].append(f'앞 잔기와 PDB 번호 공백 {increment - 1}개; loop를 생성하지 않음')
        counts[c] = counts.get(c, 0) + increment
        previous[c] = r['number']
        mapped = {k: v for k, v in r.items() if not k.startswith('_')}
        mapped.update(engine_chain=chain_map[c], engine_number=counts[c])
        mapping.append(mapped)
        for atom in r['_atoms']:
            x, y, z = atom.coord
            pdb.append(f'ATOM  {serial:5d} {atom.fullname:4s} {r["name"]:3s} {chain_map[c]}{counts[c]:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{1.:6.2f}{float(atom.bfactor):6.2f}          {atom.element:>2s}')
            serial += 1
    if serial > 99999 or max(counts.values()) > 9999:
        raise ValueError('PDB 원자/잔기 번호 표현 한계를 초과했습니다.')
    neighbors = [NeighborSearch([a for r in selected if r['chain'] in g for a in r['_atoms']]) for g in groups]
    rows = []
    for r, mapped in zip(selected, mapping):
        if r['chain'] not in scan_chains:
            continue
        other = neighbors[1 if r['chain'] in groups[0] else 0]
        distances = [float(np.linalg.norm(a.coord - b.coord)) for a in r['_atoms'] for b in other.search(a.coord, cutoff)]
        distance = min(distances) if distances else None
        eligible = r['wt'] != 'A' and (include_gly or r['wt'] != 'G') and '주사슬 원자 누락' not in r['warnings']
        rows.append({**mapped, 'distance': round(distance, 3) if distance is not None else None, 'interface': distance is not None, 'eligible': eligible, 'selected': eligible and distance is not None})
    hetero = [h for h in model['hetero'] if h['chain'] in groups[0] | groups[1]]
    if hetero:
        notes.append('선택 파트너의 물·비표준 잔기·보조인자가 정규화 구조에 포함되지 않았습니다. 원본을 확인하세요.')
    notes.append('중원자만 유지; 체인 및 잔기를 엔진용으로 재번호 매김. 원본 매핑 및 번호 공백 보존; 결손 loop는 모델링하지 않음.')
    return {'rows': rows, 'mapping': mapping, 'pdb': '\n'.join(pdb) + '\nEND\n', 'groups': [[chain_map[c] for c in sorted(g)] for g in groups], 'warnings': notes, 'blocking_hetero': [h for h in hetero if h['name'] not in ('HOH', 'WAT', 'DOD')]}
