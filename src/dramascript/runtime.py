"""Resolve bundled media tools before consulting the system installation."""
from pathlib import Path
import shutil
import subprocess
import sys


def media_tool(name):
    if getattr(sys, 'frozen', False):
        bundled = Path(sys._MEIPASS) / 'media' / (name + ('.exe' if sys.platform == 'win32' else ''))
        if bundled.is_file():
            return str(bundled)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f'缺少视频组件 {name}，请重新安装完整软件包。')
    return found


def run_media(args, **kwargs):
    args = [media_tool(args[0]), *args[1:]]
    if sys.platform == 'win32':
        kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)


def check_media():
    for name in ('ffmpeg', 'ffprobe'):
        run_media([name, '-version'], capture_output=True, check=True, timeout=30)
