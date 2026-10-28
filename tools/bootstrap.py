"""Fetch frozen upstream source without touching any existing user checkout."""
import json
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]
for name, item in json.loads((root / 'upstream.lock.json').read_text()).items():
    dest = root / '.cache/upstream' / name
    if not dest.exists():
        subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout', item['url'], str(dest)], check=True)
    revision = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != item['commit']:
        dirty = subprocess.check_output(['git', '-C', str(dest), 'status', '--porcelain'], text=True)
        if dirty:
            raise SystemExit(f'Refusing to overwrite changes in {dest}')
        subprocess.run(['git', '-C', str(dest), 'fetch', 'origin', item['commit']], check=True)
        subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', item['commit']], check=True)
    print(f'{name}: {item["commit"]}')
