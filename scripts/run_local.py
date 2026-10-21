"""Run one loopback-only backend with explicitly downloaded local models."""
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay import model_settings
from backend.main import create_app
import uvicorn

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['baseline','stgcn'], default='baseline')
    args=parser.parse_args()
    uvicorn.run(create_app(model_settings(args.model)), host='127.0.0.1', port=8000, ws_max_size=1024*1024, ws_max_queue=1, workers=1)
