#!/usr/bin/env python3
"""Prepare the pinned CPU regression model and an isolated native runtime."""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

SOURCE = json.loads((Path(__file__).resolve().parents[1] / 'third_party/sources.json').read_text())['saambe3d']


def package_manager(directory):
    for name in ('conda', 'micromamba'):
        existing = shutil.which(name)
        if existing:
            return existing
    systems = {('Darwin', 'arm64'): 'osx-arm64', ('Darwin', 'x86_64'): 'osx-64',
               ('Linux', 'x86_64'): 'linux-64', ('Linux', 'aarch64'): 'linux-aarch64'}
    target = systems.get((platform.system(), platform.machine()))
    if not target:
        raise ValueError('이 플랫폼에 맞는 Conda 설치가 필요합니다.')
    hashes = {
        "linux-64": "e7274528ceb9c20d048a428d6c22d7e02e268f8ffb762c4c365422347c8b8ba2",
        "linux-aarch64": "02ed4fe982c8ecbf9c5b1759c07ee29063994842b65fdaab439db77b9b00510a",
        "osx-64": "49c2375bc7553287404f3e348494f3dc7f7987bcd99fe996d2099a654b384b95",
        "osx-arm64": "bd5b8d3f151c3ad2d92f0fb918806543d713c7f67895c020db4041097a7f004d"
    }
    url = f'https://conda.anaconda.org/conda-forge/{target}/micromamba-2.3.3-0.tar.bz2'
    binary = directory / 'micromamba'
    with tempfile.TemporaryFile() as package, urllib.request.urlopen(url, timeout=120) as response:
        shutil.copyfileobj(response, package)
        package.seek(0)
        if hashlib.sha256(package.read()).hexdigest() != hashes[target]:
            raise ValueError('패키지 관리자 다운로드 해시가 일치하지 않습니다.')
        package.seek(0)
        with tarfile.open(fileobj=package, mode='r:bz2') as archive:
            entry = archive.getmember('bin/micromamba')
            if not entry.isfile():
                raise ValueError('패키지 관리자 파일을 확인하세요.')
            with archive.extractfile(entry) as src, binary.open('wb') as dst:
                shutil.copyfileobj(src, dst)
    binary.chmod(0o700)
    return str(binary)


def install(directory):
    directory.mkdir(parents=True)
    source, env = directory / 'source', directory / 'env'
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', 'fetch', '--depth=1', SOURCE['url'], SOURCE['commit']], cwd=source, check=True)
    subprocess.run(['git', 'checkout', '--detach', SOURCE['commit']], cwd=source, check=True)
    manager = package_manager(directory)
    settings = os.environ.copy()
    if Path(manager).name == 'micromamba':
        settings['MAMBA_ROOT_PREFIX'] = str(directory / 'mamba')
    subprocess.run([manager, 'create', '-y', '--prefix', str(env), '--override-channels', '-c', 'conda-forge',
                    'python=3.11', 'numpy=1.26.4', 'py-xgboost=1.7.6=cpu*', 'pyparsing=3.1.1', 'biopython=1.83',
                    'scipy=1.11', 'setuptools=75.8.2', 'wheel', 'pip'], check=True, env=settings)
    python = str(env / 'bin/python')
    # The noarch ProDy distribution contains a Linux-only spatial search extension.
    subprocess.run([python, '-m', 'pip', 'install', '--no-deps', '--no-build-isolation', 'prody==2.4.1'], check=True)
    subprocess.run([python, str(source / 'saambe-3d.py'), '-i', str(source / '1a22.pdb'),
                    '-c', 'A', '-r', '182', '-w', 'C', '-m', 'A', '-d', '1', '-o', str(directory / 'reference.out')], check=True)
    reference = (directory / 'reference.out').read_text().split()
    if reference != ['0.80', 'Destabilizing']:
        raise ValueError('공식 예제 C182A 시험 결과를 확인하세요.')
    print('1A22 C182A:', *reference, flush=True)


if __name__ == '__main__':
    install(Path(sys.argv[1]).resolve())
