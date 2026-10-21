"""Offline video replay through the live detector and policy. No call provider is imported."""
import argparse
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import Settings
from backend.safety.detector import Detector
from backend.safety.event_policy import EventPolicy


def model_settings(model):
    artifacts = json.loads((ROOT / 'scripts/model_artifacts.json').read_text())
    pose, stgcn = artifacts
    return Settings(SAFETY_POSE_PATH=str(ROOT / 'data/models' / pose['name']), SAFETY_POSE_SHA256=pose['sha256'],
                    SAFETY_TEMPORAL_MODEL=model, SAFETY_STGCN_PATH=str(ROOT / 'data/models' / stgcn['name']),
                    SAFETY_STGCN_SHA256=stgcn['sha256'], SAFETY_STGCN_CONFIG=str(ROOT / 'scripts/stgcn_config.py'))


def replay(path, detector, analyzed_fps=10):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or not np.isfinite(fps) or fps <= 0:
        raise ValueError(f'Cannot read video: {path}')
    detector.reset()
    policy = EventPolicy(); policy.arm()
    frame_id = 0; next_sample = 0.; available = 0; analyzed = 0; latencies = []; events = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = frame_id / fps; frame_id += 1
        if t + 1e-6 < next_sample:
            continue
        next_sample = t + 1 / analyzed_fps
        scale = min(640 / frame.shape[1], 480 / frame.shape[0], 1)
        frame = cv2.resize(frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale)))
        start = time.perf_counter()
        evidence, tracks = detector.process(t, frame)
        created, _ = policy.step(t, evidence)
        latencies.append((time.perf_counter() - start) * 1000)
        analyzed += 1; available += int(evidence.ready)
        if created:
            events.append({'onset': t, 'score': evidence.score, 'track_ids': [p['id'] for p in tracks]})
    cap.release()
    return {'source': 'replay', 'automatic_calls': False, 'model': detector.temporal.version,
            'events': events, 'duration_seconds': frame_id / fps, 'analyzed_frames': analyzed,
            'coverage': available / analyzed if analyzed else 0, 'processing_median_ms': float(np.median(latencies)) if latencies else None,
            'processing_p95_ms': float(np.percentile(latencies, 95)) if latencies else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--model', choices=['baseline','stgcn'], default='baseline')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    detector = Detector(model_settings(args.model))
    if not detector.ready:
        raise SystemExit(detector.reason)
    try:
        report = replay(args.video, detector)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
    finally:
        detector.close()


if __name__ == '__main__':
    main()
