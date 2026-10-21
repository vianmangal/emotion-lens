"""Explicit, checksum-verified model setup. Never invoked by API startup."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stgcn', action='store_true', help='Also download the optional MMAction2 checkpoint')
    args = parser.parse_args()
    directory = ROOT / 'data/models'
    directory.mkdir(parents=True, exist_ok=True)
    for item in json.loads((ROOT / 'scripts/model_artifacts.json').read_text()):
        if item['name'].endswith('.pth') and not args.stgcn:
            continue
        target = directory / item['name']
        if not target.exists():
            temporary = target.with_suffix('.download')
            try:
                with urllib.request.urlopen(item['url'], timeout=60) as response, temporary.open('wb') as output:
                    size = 0
                    while block := response.read(1024 * 1024):
                        size += len(block)
                        if size > item['bytes']:
                            raise ValueError('Unexpected artifact size')
                        output.write(block)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != item['sha256']:
                    raise ValueError('Downloaded artifact checksum mismatch')
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'Existing artifact checksum mismatch: {target.name}; no file overwritten')
        prefix = 'SAFETY_POSE' if item['name'].endswith('.task') else 'SAFETY_STGCN'
        print(f'{prefix}_PATH={target}')
        print(f'{prefix}_SHA256={item["sha256"]}')


if __name__ == '__main__':
    main()
