"""Run on the target OS; no cross-compilation or publication."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
# Chocolatey exposes shims; package the real executable rather than the shim.
media = []
for name in ('ffmpeg', 'ffprobe'):
    found = shutil.which(name)
    if sys.platform == 'win32' and found and 'chocolatey' in found.lower():
        candidates = list(Path(os.environ.get('ProgramData', r'C:\ProgramData')).glob(f'chocolatey/lib/ffmpeg*/tools/**/{name}.exe'))
        if not candidates:
            raise RuntimeError(f'Cannot locate real {name}.exe behind Chocolatey shim')
        found = str(candidates[0])
    if not found:
        raise RuntimeError(f'Install {name} on the build machine first')
    subprocess.run([found, '-version'], capture_output=True, check=True, timeout=30)
    media.extend(['--add-binary', f'{Path(found).resolve()}{os.pathsep}media'])
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
                '--name', 'DramaScript', '--paths', 'src',
                '--add-data', f'docs{os.pathsep}docs',
                '--exclude-module', 'torch', '--exclude-module', 'torchvision', '--exclude-module', 'transformers',
                '--collect-all', 'faster_whisper', '--collect-all', 'ctranslate2',
                *media, 'src/dramascript/launcher.py'], check=True)
executable = Path('dist/DramaScript.app/Contents/MacOS/DramaScript') if sys.platform == 'darwin' else Path('dist/DramaScript') / ('DramaScript.exe' if sys.platform == 'win32' else 'DramaScript')
smoke_env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
subprocess.run([str(executable.resolve()), '--smoke-test'], env=smoke_env, timeout=60, check=True)
# Verify the packaged media executables without relying on the builder's PATH.
subprocess.run([str(executable.resolve()), '--check-media'],
               env=dict(smoke_env, PATH=''), timeout=90, check=True)
if sys.platform == 'darwin':
    subprocess.run(['hdiutil', 'create', '-volname', 'DramaScript', '-srcfolder',
                    'dist/DramaScript.app', '-ov', '-format', 'UDZO', 'dist/DramaScript-macOS.dmg'], check=True)
else:
    shutil.make_archive(f'dist/DramaScript-{sys.platform}', 'zip', 'dist/DramaScript')
print('Build complete. FFmpeg/FFprobe are bundled and checked. This build is unsigned.')
