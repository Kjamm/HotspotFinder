#!/usr/bin/env python3
"""Prepare project dependencies when needed, then launch the local application."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

root = Path(__file__).resolve().parents[1]
os.chdir(root)
python = root / '.venv/bin/python'
if sys.platform == 'win32':
    sys.exit('Windows에서는 WSL2 안에서 이 앱을 실행하세요.')
if not python.exists():
    print('앱 실행 환경을 준비하고 있습니다.', flush=True)
    venv.EnvBuilder(with_pip=True).create(root / '.venv')
check = subprocess.run([str(python), '-c', 'import fastapi, uvicorn, Bio, numpy, multipart'], capture_output=True)
if check.returncode:
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)
if not (root / 'frontend/dist/index.html').exists():
    npm = shutil.which('npm')
    if not npm:
        sys.exit('첫 화면 빌드에는 Node.js와 npm이 필요합니다. 설치한 뒤 다시 실행하세요.')
    subprocess.run([npm, 'ci'], cwd=root / 'frontend', check=True)
    subprocess.run([npm, 'run', 'build'], cwd=root / 'frontend', check=True)
os.execv(str(python), [str(python), str(root / 'scripts/run.py'), '--open'])
