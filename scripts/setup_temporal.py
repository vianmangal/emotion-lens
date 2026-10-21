"""Explicit optional STGCN environment setup; never run at application startup."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REVISION = '4d6c93474730cad2f25e51109adcf96824efc7a3'  # MMAction2 v1.2.0


def main():
    env = ROOT / '.venv-model'
    if not env.exists(): subprocess.run([sys.executable, '-m', 'venv', str(env)], check=True)
    python = env / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'backend/requirements-temporal.txt')], check=True)
    source = ROOT / 'data/vendor/mmaction2'
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--depth', '1', '--branch', 'v1.2.0', 'https://github.com/open-mmlab/mmaction2.git', str(source)], check=True)
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if head != REVISION or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise SystemExit('Existing MMAction2 checkout differs from the tested clean revision; no files reset')
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-deps', '-e', str(source)], check=True)
    subprocess.run([str(python), str(ROOT / 'scripts/download_models.py'), '--stgcn'], check=True)
    print(f'Run live: {python} scripts/run_local.py --model stgcn')


if __name__ == '__main__': main()
