"""Timed local transport/memory check using generated images, never a real camera.

Runs an isolated SQLite app on an ephemeral loopback port. This is an engineering
soak, not an action-accuracy evaluation. No call credentials or provider requests.
"""
import argparse
import asyncio
import base64
from collections import deque
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import cv2
import httpx
import numpy as np
import uvicorn
import websockets
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.replay import model_settings
from backend.main import create_app
from scripts.evaluate import pipeline_identity, video_checksum


def resident_bytes():
    return int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(os.getpid())], text=True).strip()) * 1024


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


async def run(args):
    report = {'state': 'starting', 'pid': os.getpid(), 'source': 'generated static noise JPEG; no camera or people',
              'scope': 'real localhost WebSocket, image decode, pose model, policy, optional clip ring and SQLite runtime; no human action accuracy',
              'model': args.model, 'requested_seconds': args.seconds, 'calls_enabled': False,
              'detector_qualified': False,
              'frames': 0, 'rss_samples': []}
    write_report(args.output, report)
    with tempfile.TemporaryDirectory(prefix='emotion-lens-soak-') as directory:
        config = model_settings(args.model).model_copy(update={
            'DATA_DIR': Path(directory), 'DATABASE_URL': f'sqlite+aiosqlite:///{directory}/soak.db',
            'ELEVENLABS_API_KEY': SecretStr(''), 'ELEVENLABS_AGENT_ID': '', 'ELEVENLABS_AGENT_PHONE_NUMBER_ID': '',
            'SAFETY_ALERT_TO_NUMBER': SecretStr(''),
            'CORS_ALLOW_ORIGINS': ['http://127.0.0.1:5173'], 'ALLOWED_HOSTS': ['127.0.0.1'],
            'SAFETY_SESSION_TTL_SECONDS': 3600})
        app = create_app(config)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen(32)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                 access_log=False, log_level='warning', ws_max_size=1048576, ws_max_queue=1))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            while not server.started:
                if serving.done(): await serving
                await asyncio.sleep(.05)
            rt = app.state.safety
            if not rt.detector.ready: raise RuntimeError(rt.detector.reason)
            report['model_version'] = rt.detector.temporal.version
            report['model_identity'] = pipeline_identity(config)
            report['runtime_sources'] = {name: video_checksum(ROOT / name) for name in [
                'backend/config.py', 'backend/database.py', 'backend/main.py', 'backend/routers/safety.py', 'backend/safety/schemas.py', 'scripts/soak_test.py',
                'backend/safety/sessions.py', 'backend/safety/frame_buffer.py',
                'backend/safety/recording.py', 'backend/safety/retention.py',
                'backend/safety/actions/dispatcher.py']}
            report['threshold_version'] = rt.status()['threshold_version']
            image = np.random.default_rng(0).integers(0, 256, (480, 640, 3), dtype=np.uint8)
            jpeg = base64.b64encode(cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])[1]).decode()
            assert len(jpeg) < 699052
            ages = deque(maxlen=2000)
            max_frames = max_bytes = 0
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}') as client:
                token = (await client.get('/safety/bootstrap', headers={'X-EmotionLens-Client': 'local-ui'})).json()['capability']
                client.headers['X-Safety-Capability'] = token
                response = await client.post('/safety/sessions', json={'source': 'replay'})
                response.raise_for_status(); session = response.json()
                headers = {'X-Session-Capability': session['capability']}
                async with websockets.connect(f'ws://127.0.0.1:{port}/safety/sessions/{session["id"]}/stream', origin='http://127.0.0.1:5173') as ws:
                    await ws.send(json.dumps({'capability': session['capability']})); await ws.recv()
                    response = await client.post(f'/safety/sessions/{session["id"]}/arm', headers=headers,
                                                 json={'phone_mode': 'off', 'clips': True, 'client_now_ms': time.monotonic() * 1000})
                    response.raise_for_status()
                    started = time.monotonic(); next_sample = started
                    report['state'] = 'running'
                    while time.monotonic() - started < args.seconds:
                        tick = time.monotonic()
                        await ws.send(json.dumps({'v': 1, 'session_id': session['id'], 'frame_id': report['frames'],
                                                  'captured_ms': tick * 1000, 'jpeg': jpeg}))
                        while True:
                            result = json.loads(await asyncio.wait_for(ws.recv(), 5))
                            if result.get('type') != 'heartbeat': break
                        if result['state'] in ('disarmed', 'unavailable'):
                            raise RuntimeError(f'Monitoring stopped: {result.get("reason")}')
                        report['frames'] += 1
                        ages.append(result['frame_age_ms'])
                        frames = rt.session.buffer.frames
                        count = len(frames); size = sum(len(raw) for _, raw in frames)
                        max_frames = max(max_frames, count); max_bytes = max(max_bytes, size)
                        if count > 60 or size > 12 * 1024 * 1024 or len(rt.detector.history) > 120:
                            raise AssertionError('Runtime buffer exceeded its configured bound')
                        elapsed = time.monotonic() - started
                        if not report['rss_samples'] or elapsed - report['rss_samples'][-1]['elapsed_seconds'] >= 30:
                            disk_bytes = sum(p.stat().st_size for p in Path(directory).rglob('*') if p.is_file())
                            report['rss_samples'].append({'elapsed_seconds': round(elapsed, 3), 'rss_bytes': resident_bytes(),
                                                          'disk_bytes': disk_bytes})
                            report.update(elapsed_seconds=round(elapsed, 3), max_clip_frames=max_frames, max_clip_bytes=max_bytes)
                            write_report(args.output, report)
                            print(f'soak {elapsed:.0f}s: {report["frames"]} frames, {size / 1048576:.1f} MiB ring', flush=True)
                        next_sample = max(next_sample + .1, time.monotonic())
                        await asyncio.sleep(max(0, next_sample - time.monotonic()))
                    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
                    report['rss_samples'].append({'elapsed_seconds': report['elapsed_seconds'], 'rss_bytes': resident_bytes(),
                        'disk_bytes': sum(p.stat().st_size for p in Path(directory).rglob('*') if p.is_file())})
                    await client.post(f'/safety/sessions/{session["id"]}/disarm', headers=headers)
                await client.delete(f'/safety/sessions/{session["id"]}', headers=headers)
            rss = report['rss_samples']
            warm_peak = max(s['rss_bytes'] for s in rss if s['elapsed_seconds'] <= 120)
            later_peak = max(s['rss_bytes'] for s in rss)
            growth = max(0, later_peak - warm_peak)
            max_disk = max(s['disk_bytes'] for s in rss)
            disk_limit = rt.store.quota + 64 * 1024 * 1024
            report.update(state='completed', passed=growth <= 64 * 1024 * 1024 and max_disk <= disk_limit,
                          actual_fps=report['frames'] / report['elapsed_seconds'], max_clip_frames=max_frames,
                          max_clip_bytes=max_bytes, rss_growth_after_warmup_bytes=growth,
                          max_disk_bytes=max_disk, disk_limit_bytes=disk_limit,
                          memory_growth_limit_bytes=64 * 1024 * 1024,
                          frame_age_p95_ms=float(np.percentile(ages, 95)),
                          timing_sample_scope='last 2000 frame results; RSS sampled every 30 seconds')
        except BaseException as exc:
            report.update(state='failed', passed=False, error_category=type(exc).__name__, error=str(exc))
            raise
        finally:
            server.should_exit = True
            await serving
            listener.close()
            write_report(args.output, report)
    if not report['passed']: raise RuntimeError('Memory/disk use exceeded the engineering soak limit')
    print(json.dumps({k: v for k, v in report.items() if k != 'rss_samples'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=1800)
    parser.add_argument('--model', choices=['baseline', 'stgcn'], default='baseline')
    parser.add_argument('--output', type=Path, default=ROOT/'data/soak.json')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 1800: parser.error('seconds must be between 1 and 1800')
    asyncio.run(run(args))
