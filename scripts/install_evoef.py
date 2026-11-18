#!/usr/bin/env python3
"""Build the pinned, MIT-licensed EvoEF in an isolated installation directory."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'third_party/sources.json').read_text())['evoef']
parser = argparse.ArgumentParser()
parser.add_argument('--destination', type=Path, default=ROOT / '.engines/EvoEF')
args = parser.parse_args()
destination = args.destination.resolve()
compiler = shutil.which('clang++') or shutil.which('g++')
if not compiler:
    raise SystemExit('C++ 컴파일러가 필요합니다. macOS는 Xcode Command Line Tools, Linux/WSL은 build-essential을 설치하세요.')
if not shutil.which('git'):
    raise SystemExit('EvoEF 소스를 받으려면 Git을 설치하세요.')
if not destination.exists():
    destination.parent.mkdir(parents=True, exist_ok=True)
    cached = ROOT / '.engines/EvoEF'
    source = LOCK['url']
    if (cached / '.git').is_dir():
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=cached, text=True).strip()
        if revision == LOCK['commit']:
            source = str(cached)
    subprocess.run(['git', 'clone', '--no-hardlinks', source, str(destination)], check=True)
    subprocess.run(['git', 'checkout', LOCK['commit']], cwd=destination, check=True)
actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
if actual != LOCK['commit']:
    raise SystemExit('기존 EvoEF revision이 다릅니다. 새 설치 폴더를 선택하세요.')
output = destination / 'EvoEF.building'
sources = [str(p.relative_to(destination)) for p in sorted((destination / 'src').glob('*.cpp'))]
subprocess.run([compiler, '-O3', '-Wno-deprecated-declarations', '-Wno-writable-strings', '-o', str(output), *sources], cwd=destination, check=True)
output.replace(destination / 'EvoEF')
print('설치 완료', destination / 'EvoEF', flush=True)
