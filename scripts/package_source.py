"""Create a small source delivery, excluding environments and model/media caches."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / 'dist' / 'DramaScript-0.2.0-source.zip'
output.parent.mkdir(exist_ok=True)
paths = [root / name for name in ('README.md', 'pyproject.toml', '.gitignore')]
for folder in ('src', 'scripts', 'tests', 'docs', '.github'):
    paths.extend(p for p in (root / folder).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'
                 and not any(part.endswith('.egg-info') for part in p.parts))
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(paths):
        archive.write(path, Path('DramaScript') / path.relative_to(root))
print(output)
