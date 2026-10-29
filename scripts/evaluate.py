"""Event evaluation on local videos. No provider calls and no automatic qualification."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.replay import Detector, model_settings, replay
from backend.safety.event_policy import threshold_version


def match_events(predictions, truth, tolerance=4):
    """Match chronological predictions to the oldest eligible unused label.

    The fixed forward windows make this a maximum-cardinality chronological
    matching. Nearest-label greedy matching can steal a later event's only match.
    """
    labels = sorted(truth)
    next_label = 0
    true_positives = false_positives = 0
    delays = []
    for predicted in sorted(predictions):
        while next_label < len(labels) and labels[next_label] < predicted - tolerance:
            next_label += 1
        if next_label < len(labels) and labels[next_label] <= predicted:
            true_positives += 1
            delays.append(predicted - labels[next_label])
            next_label += 1
        else:
            false_positives += 1
    return true_positives, false_positives, len(labels) - true_positives, delays


def video_checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(payload, directory):
    rows = payload.get('clips')
    if not isinstance(rows, list) or not rows:
        raise ValueError('No clips supplied; accuracy cannot be evaluated')
    groups, videos = {}, {}
    required = ('path', 'source', 'license', 'participants', 'session', 'angle', 'lighting', 'category', 'split', 'onsets')
    for row in rows:
        if not isinstance(row, dict) or any(field not in row for field in required):
            raise ValueError('Every clip needs path, source/license, participant/session grouping, scene metadata, split and onsets')
        for field in ('path', 'source', 'license', 'session', 'angle', 'lighting', 'category'):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f'Invalid clip {field}')
        if row['split'] not in ('development', 'held_out'):
            raise ValueError('Invalid evaluation split')
        if not isinstance(row['participants'], list) or any(not isinstance(p, str) or not p.strip() for p in row['participants']):
            raise ValueError('Participants must be a list of nonempty pseudonyms')
        onsets = row['onsets']
        if not isinstance(onsets, list) or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in onsets):
            raise ValueError('Onsets must be finite nonnegative seconds')
        if len(set(onsets)) != len(onsets):
            raise ValueError('Duplicate event labels would inflate evaluation counts')
        if not isinstance(row.get('continuous', False), bool):
            raise ValueError('continuous must be a boolean')
        for group in [f'participant:{p}' for p in row['participants']] + [f'session:{row["session"]}']:
            if group in groups and groups[group] != row['split']:
                raise ValueError(f'Participant/session leakage across splits: {group}')
            groups[group] = row['split']
        path = (directory / row['path']).resolve()
        digest = video_checksum(path)
        if digest in videos:
            raise ValueError(f'Duplicate video content: {row["path"]} and {videos[digest]}')
        videos[digest] = row['path']
    return rows


def pipeline_identity(config):
    paths = ['backend/safety/detector.py', 'backend/safety/tracking.py', 'backend/safety/temporal_model.py',
             'backend/safety/event_policy.py', 'backend/safety/video_model.py', 'scripts/stgcn_config.py', 'scripts/replay.py', 'scripts/evaluate.py']
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode())
        digest.update((ROOT / path).read_bytes())
    return {'pipeline_sha256': digest.hexdigest(), 'pose_sha256': config.SAFETY_POSE_SHA256 if config.SAFETY_TEMPORAL_MODEL != 'visual' else None,
            'person_detector_sha256': config.SAFETY_PERSON_SHA256 if config.SAFETY_TEMPORAL_MODEL == 'visual' else None,
            'temporal_sha256': config.SAFETY_STGCN_SHA256 if config.SAFETY_TEMPORAL_MODEL == 'stgcn' else None,
            'visual_weights_sha256': config.SAFETY_VISUAL_WEIGHTS_SHA256 if config.SAFETY_TEMPORAL_MODEL == 'visual' else None,
            'visual_head_sha256': config.SAFETY_VISUAL_HEAD_SHA256 if config.SAFETY_TEMPORAL_MODEL == 'visual' else None,
            'threshold_version': threshold_version(config.event_policy_options())}


def verify_frozen_development(current, development):
    if development.get('split') != 'development':
        raise ValueError('Frozen reference must be a development report')
    for key in ('model', 'identity'):
        if current[key] != development.get(key):
            raise ValueError(f'Held-out run differs from frozen development {key}; do not retune against held-out data')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--model', choices=['baseline', 'stgcn', 'visual'], default='baseline')
    parser.add_argument('--split', choices=['development', 'held_out'], default='held_out')
    parser.add_argument('--development-report', type=Path, help='Required frozen reference for held-out evaluation')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = validate_manifest(json.loads(args.manifest.read_text()), args.manifest.parent)
        selected = [row for row in rows if row['split'] == args.split]
        if not selected:
            raise ValueError('No clips in the selected split')
        config = model_settings(args.model)
        identity = pipeline_identity(config)
        if args.split == 'held_out':
            if not args.development_report:
                raise ValueError('Held-out evaluation requires --development-report to freeze model, preprocessing and thresholds')
            verify_frozen_development({'model': args.model, 'identity': identity}, json.loads(args.development_report.read_text()))
        detector = Detector(config)
        if not detector.ready:
            raise ValueError(detector.reason)
        results, delays = [], []
        tp = fp = fn = 0
        continuous_seconds = continuous_alerts = 0
        categories = {}
        try:
            for row in selected:
                result = replay((args.manifest.parent / row['path']).resolve(), detector)
                if any(t >= result['duration_seconds'] for t in row['onsets']):
                    raise ValueError(f'Event onset outside clip duration: {row["path"]}')
                a, b, c, d = match_events([event['onset'] for event in result['events']], row['onsets'])
                tp += a; fp += b; fn += c; delays.extend(d)
                if not row['onsets'] and row.get('continuous', False):
                    continuous_seconds += result['duration_seconds']; continuous_alerts += b
                categories[row['category']] = categories.get(row['category'], 0) + 1
                results.append({'path': row['path'], **result, 'tp': a, 'fp': b, 'fn': c})
        finally:
            detector.close()
        summary = {'qualified': False, 'qualification_note': 'Manual coverage/licensing/accuracy review required; this report never unlocks calls.',
                   'split': args.split, 'model': args.model, 'identity': identity, 'event_policy': config.event_policy_options(),
                   'tp': tp, 'fp': fp, 'fn': fn, 'precision': tp / (tp + fp) if tp + fp else None,
                   'recall': tp / (tp + fn) if tp + fn else None,
                   'false_alerts_per_hour': continuous_alerts / (continuous_seconds / 3600) if continuous_seconds else None,
                   'continuous_benign_seconds': continuous_seconds, 'positive_labeled_events': sum(len(row['onsets']) for row in selected),
                   'benign_clips': sum(not row['onsets'] for row in selected), 'categories': categories,
                   'participant_count': len({p for row in selected for p in row['participants']}),
                   'onset_delay_median_seconds': float(np.median(delays)) if delays else None,
                   'onset_delay_p95_seconds': float(np.percentile(delays, 95)) if delays else None, 'clips': results}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
        print(json.dumps({key: value for key, value in summary.items() if key != 'clips'}, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
