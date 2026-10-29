"""Run the single-camera demo behind its authenticated HTTPS reverse proxy."""
import argparse
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.main import create_app
from scripts.replay import model_settings
import uvicorn


def hosted_settings(config=None):
    config = config if config is not None else model_settings('visual').model_copy(
        update={'SAFETY_VISUAL_OPTIMIZE_CPU': True})
    origins = config.CORS_ALLOW_ORIGINS
    if not origins or any(urlparse(origin).scheme != 'https' or not urlparse(origin).hostname
                          or urlparse(origin).hostname not in config.ALLOWED_HOSTS for origin in origins):
        raise ValueError('Hosted mode requires explicit HTTPS origins and matching allowed hosts')
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    uvicorn.run(create_app(hosted_settings()), host='127.0.0.1', port=8000,
                workers=1, ws_max_size=1024 * 1024, ws_max_queue=1,
                proxy_headers=True, forwarded_allow_ips='127.0.0.1')
