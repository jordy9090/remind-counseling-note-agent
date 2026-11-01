"""Read-only dependency and GPU inventory for an isolated synthetic STT job."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess

packages = {}
for name in ('torch', 'torchaudio', 'faster-whisper', 'ctranslate2', 'funasr', 'whisperx',
             'transformers', 'numpy', 'soundfile', 'scikit-learn', 'rapidfuzz', 'psutil', 'huggingface-hub'):
    try:
        packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        packages[name] = None
result = {'packages': packages, 'ffmpeg': shutil.which('ffmpeg'),
          'gpu': subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,memory.total,memory.used', '--format=csv,noheader'], text=True),
          'python': os.sys.executable}
print(json.dumps(result, indent=2), flush=True)
destination = Path(os.environ['REMIND_GPU_OUTPUT'])
(destination / 'inventory.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
