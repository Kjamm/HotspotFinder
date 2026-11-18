#!/usr/bin/env python3
"""Launch API, worker, and the locally built UI from one command."""
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / 'backend'))
# Inherit the package path into the independent worker process.
os.environ['PYTHONPATH'] = str(root / 'backend') + os.pathsep + os.environ.get('PYTHONPATH', '')
if not (root / 'frontend/dist/index.html').exists():
    sys.exit('먼저 frontend에서 npm ci && npm run build를 실행하세요.')
import uvicorn
print('HotspotFinder: http://127.0.0.1:8765', flush=True)
def open_when_ready():
    for _ in range(100):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=1) as response:
                if response.status == 200:
                    webbrowser.open('http://127.0.0.1:8765')
                    return
        except OSError:
            time.sleep(.2)


if '--open' in sys.argv:
    threading.Thread(target=open_when_ready, daemon=True).start()
uvicorn.run('hotspotfinder.app:app', host='127.0.0.1', port=8765, access_log=False)
