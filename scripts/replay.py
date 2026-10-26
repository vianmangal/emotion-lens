"""Offline video replay through the live detector and policy. No call provider is imported."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import Settings
from backend.safety.detector import Detector
from backend.safety.event_policy import EventPolicy, threshold_version


def model_settings(model):
    artifacts = {item['name']: item for item in json.loads((ROOT / 'scripts/model_artifacts.json').read_text())}
    pose, stgcn = artifacts['pose_landmarker_lite.task'], artifacts['stgcn_ntu60.pth']
    visual, head = artifacts['s3d_kinetics400.pth'], artifacts['visual_head_v1.json']
    person = artifacts['efficientdet_lite2_int8.tflite']
    return Settings(SAFETY_POSE_PATH=str(ROOT / 'data/models' / pose['name']), SAFETY_POSE_SHA256=pose['sha256'],
                    SAFETY_TEMPORAL_MODEL=model, SAFETY_STGCN_PATH=str(ROOT / 'data/models' / stgcn['name']),
                    SAFETY_STGCN_SHA256=stgcn['sha256'], SAFETY_STGCN_CONFIG=str(ROOT / 'scripts/stgcn_config.py'),
                    SAFETY_VISUAL_WEIGHTS_PATH=str(ROOT / 'data/models' / visual['name']),
                    SAFETY_VISUAL_WEIGHTS_SHA256=visual['sha256'],
                    SAFETY_VISUAL_HEAD_PATH=str(ROOT / head['local_path']), SAFETY_VISUAL_HEAD_SHA256=head['sha256'],
                    SAFETY_PERSON_PATH=str(ROOT / 'data/models' / person['name']), SAFETY_PERSON_SHA256=person['sha256'])


def replay(path, detector, analyzed_fps=10):
    if not math.isfinite(analyzed_fps) or analyzed_fps <= 0:
        raise ValueError('Analysis FPS must be positive and finite')
    cap = cv2.VideoCapture(str(path))
    previous_sync = getattr(detector.temporal, 'synchronous', None)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not cap.isOpened() or not np.isfinite(fps) or fps <= 0:
            raise ValueError(f'Cannot read video: {path}')
        detector.reset()
        # Source time advances faster than wall time in replay. Visual inference
        # runs synchronously and publishes after its measured processing delay.
        if hasattr(detector.temporal, 'synchronous'):
            detector.temporal.synchronous = True
        options = detector.config.event_policy_options()
        policy = EventPolicy(**options); policy.arm()
        frame_id = 0; next_sample = 0.; available = 0; analyzed = 0
        last_t = -1.; fallbacks = 0; latencies = []; events = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if not math.isfinite(timestamp) or timestamp < 0 or timestamp <= last_t:
                timestamp = frame_id / fps
                fallbacks += 1
            if timestamp <= last_t:
                raise ValueError('Clip timestamps are inconsistent; replay cannot invent a reliable motion history')
            t = timestamp; last_t = t; frame_id += 1
            if t + 1e-6 < next_sample:
                continue
            next_sample = (math.floor(t * analyzed_fps + 1e-6) + 1) / analyzed_fps
            scale = min(640 / frame.shape[1], 480 / frame.shape[0], 1)
            frame = cv2.resize(frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale)))
            start = time.perf_counter()
            evidence, tracks = detector.process(t, frame)
            created, _ = policy.step(t, evidence)
            processing_ms = (time.perf_counter() - start) * 1000
            latencies.append(processing_ms)
            analyzed += 1; available += int(evidence.ready)
            if created:
                events.append({'onset': t, 'score': evidence.score, 'track_ids': [p['id'] for p in tracks],
                               'processing_ms': processing_ms})
        duration = max(frame_id / fps, last_t + 1 / fps) if frame_id else 0
        return {'source': 'replay', 'automatic_calls': False, 'model': detector.temporal.version,
                'event_policy': options, 'threshold_version': threshold_version(options),
                'timestamp_source': 'nominal_fps_fallback' if fallbacks else 'presentation_timestamps',
                'timestamp_fallback_frames': fallbacks, 'model_window_seconds': detector.temporal.window_seconds,
                'capture_transport_delay_ms': None,
                'events': events, 'duration_seconds': duration, 'analyzed_frames': analyzed,
                'coverage': available / analyzed if analyzed else 0,
                'processing_median_ms': float(np.median(latencies)) if latencies else None,
                'processing_p95_ms': float(np.percentile(latencies, 95)) if latencies else None}
    finally:
        cap.release()
        if previous_sync is not None:
            detector.temporal.synchronous = previous_sync


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--model', choices=['baseline','stgcn','visual'], default='baseline')
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
