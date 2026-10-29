"""Explicit, checksum-verified model setup. Never invoked by API startup."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stgcn', action='store_true', help='Also download the optional MMAction2 checkpoint')
    parser.add_argument('--visual', action='store_true', help='Set up the learned video strike model')
    args = parser.parse_args()
    directory = ROOT / 'data/models'
    directory.mkdir(parents=True, exist_ok=True)
    for item in json.loads((ROOT / 'scripts/model_artifacts.json').read_text()):
        kind = item['kind']
        if kind == 'stgcn' and not args.stgcn:
            continue
        if kind == 'visual' and not args.visual:
            continue
        target = directory / item['name']
        if not target.exists():
            temporary = target.with_suffix('.download')
            try:
                if item.get('local_path'):
                    shutil.copyfile(ROOT / item['local_path'], temporary)
                else:
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
        prefix = ('SAFETY_POSE' if kind == 'pose' else 'SAFETY_STGCN' if kind == 'stgcn' else
                  'SAFETY_PERSON' if item['name'].endswith('.tflite') else
                  'SAFETY_VISUAL_HEAD' if item['name'].endswith('.json') else 'SAFETY_VISUAL_WEIGHTS')
        print(f'{prefix}_PATH={target}')
        print(f'{prefix}_SHA256={item["sha256"]}')


if __name__ == '__main__':
    main()
