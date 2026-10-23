import subprocess
import sys
from pathlib import Path


def test_validation_does_not_present_cached_project_as_new_inference(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'existing.txt').write_text('保留')
    script = Path(__file__).parents[1] / 'scripts' / 'validate_models.py'
    result = subprocess.run([sys.executable, str(script), '--mode', 'local', '--video', str(tmp_path / 'missing.mp4'), '--project', str(project)], capture_output=True, text=True)
    assert result.returncode == 2 and '需要空目录' in result.stderr
    assert (project / 'existing.txt').read_text() == '保留'
