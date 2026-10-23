from contextlib import contextmanager
from pathlib import Path
from PySide6.QtCore import QLockFile


@contextmanager
def project_guard(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(folder / '.dramascript.lock'))
    lock.setStaleLockTime(0)  # Long video jobs must not expire while their process is alive.
    if not lock.tryLock(0):
        raise RuntimeError('项目已被其他任务占用或目录不可写，请检查后重试。')
    try:
        yield
    finally:
        lock.unlock()
