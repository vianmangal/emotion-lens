"""Clip-level development checks on public interactions. Never accesses a camera or calls."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate import pipeline_identity
from scripts.replay import Detector, model_settings, replay
from backend.safety.detector import verify_artifact
from backend.safety.video_model import StrikeHead

SOURCES = {
    'ut-interaction': 'https://cvrc.ece.utexas.edu/SDHA2010/Human_Interaction.html',
    'limu': 'https://limu.ait.kyushu-u.ac.jp/~resource/dataset/en/interaction_dataset.html',
}
UT_CLASSES = {0: 'handshake', 1: 'hug', 2: 'kick', 3: 'point', 4: 'punch', 5: 'push'}
SCOPE = ('Public-video development check, not held-out webcam qualification. Counts are clips with '
         'at least one alert, not individual-strike recall. A clip may contain multiple actions. '
         'Short clips include cold-start warm-up. Mirrored copies are correlated augmentations '
         'and are reported separately. No video, poses or phone actions are exported.')


@dataclass(frozen=True)
class Clip:
    path: Path
    dataset: str
    category: str
    actor_side: str = 'unspecified'


def discover(directory, selected='both'):
    clips = []
    if selected in ('ut-interaction', 'both'):
        for path in sorted((directory / 'ut-interaction').rglob('*.avi')):
            match = re.fullmatch(r'\d+_(\d+)_(\d)\.avi', path.name)
            if not match or int(match[2]) not in UT_CLASSES:
                raise ValueError(f'Unknown UT-Interaction label: {path.name}')
            clips.append(Clip(path, 'ut-interaction', UT_CLASSES[int(match[2])]))
    if selected in ('limu', 'both'):
        for path in sorted((directory / 'limu').glob('*.avi')):
            match = re.fullmatch(r'(punch|handclap|handshake)_(\d+)\.avi', path.name)
            if not match or not 1 <= int(match[2]) <= 10:
                raise ValueError(f'Unknown LIMU label: {path.name}')
            clips.append(Clip(path, 'limu', match[1], 'left' if int(match[2]) <= 5 else 'right'))
    if not clips:
        raise ValueError('No public clips found; download the documented source datasets first')
    digests = [hashlib.sha256(clip.path.read_bytes()).hexdigest() for clip in clips]
    if len(digests) != len(set(digests)):
        raise ValueError('Duplicate source video content would inflate the check')
    return clips


class CameraProtocol:
    """Same bounded resize (replay), JPEG quality and sample cadence as live."""
    def __init__(self, detector, mirrored=False):
        self.detector, self.mirrored = detector, mirrored
        self.config, self.temporal = detector.config, detector.temporal

    def reset(self):
        self.detector.reset()
        self.people = Counter()
        self.reasons = Counter()
        self.max_score = 0.

    def process(self, t, frame):
        if self.mirrored:
            frame = cv2.flip(frame, 1)
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            raise ValueError('Cannot simulate camera JPEG input')
        decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        evidence, tracks = self.detector.process(t, decoded)
        self.people[len(tracks)] += 1
        self.reasons.update(evidence.reasons)
        self.max_score = max(self.max_score, evidence.score)
        return evidence, tracks


def summarize(rows):
    groups = defaultdict(lambda: defaultdict(lambda: {'clips': 0, 'alerted': 0, 'coverage_sum': 0.}))
    for row in rows:
        key = f"{row['dataset']}/{'mirrored' if row['mirrored'] else 'original'}"
        category = groups[key][row['category']]
        category['clips'] += 1
        category['alerted'] += bool(row['events'])
        category['coverage_sum'] += row['coverage']
    return {key: {category: {'clips': value['clips'], 'alerted': value['alerted'],
                             'mean_tracking_coverage': value['coverage_sum'] / value['clips']}
                  for category, value in values.items()} for key, values in groups.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT / 'data/public-evaluation')
    parser.add_argument('--dataset', choices=['ut-interaction', 'limu', 'both'], default='both')
    parser.add_argument('--model', choices=['baseline', 'stgcn', 'visual'], default='visual')
    parser.add_argument('--orientation', choices=['original', 'mirrored', 'both'], default='both')
    parser.add_argument('--fold-heads', type=Path, help='Grouped validation manifest produced by train_visual_strike.py')
    parser.add_argument('--clip', action='append', help='Check only these source filenames (repeatable)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists; choose a new report filename')
    clips = discover(args.root, args.dataset)
    if args.clip:
        clips = [clip for clip in clips if clip.path.name in args.clip]
        if {clip.path.name for clip in clips} != set(args.clip):
            raise SystemExit('A requested clip was not found')
    folds = json.loads(args.fold_heads.read_text()) if args.fold_heads else None
    if folds and args.model != 'visual':
        raise SystemExit('Fold heads apply only to the visual model')
    config = model_settings(args.model)
    config.SAFETY_EVENT_COOLDOWN_SECONDS = 0  # Exactly the simplified live-only policy.
    config.SAFETY_VISUAL_SYNCHRONOUS = args.model == 'visual'
    identity = pipeline_identity(config)
    detector = Detector(config)
    if not detector.ready:
        raise SystemExit(detector.reason)
    rows = []
    orientations = [False, True] if args.orientation == 'both' else [args.orientation == 'mirrored']
    try:
        for clip in clips:
            effective_head = config.SAFETY_VISUAL_HEAD_SHA256 if args.model == 'visual' else None
            held_out_group = None
            if folds:
                stem = clip.path.stem.split('_')
                held_out_group = f'limu/{stem[-1]}' if clip.dataset == 'limu' else f'ut/{stem[1]}'
                entry = folds['heads'][folds['groups'][held_out_group]]
                path = args.fold_heads.parent / entry['path']
                verify_artifact(path, entry['sha256'])
                metadata = json.loads(path.read_text())
                if held_out_group in metadata['training_groups'] or held_out_group not in metadata['held_out_groups']:
                    raise ValueError('Source group was not excluded from this head’s training')
                detector.temporal.head = StrikeHead(path)
                effective_head = entry['sha256']
            for mirrored in orientations:
                protocol = CameraProtocol(detector, mirrored)
                result = replay(clip.path, protocol)
                row = {'path': str(clip.path.relative_to(args.root)), 'dataset': clip.dataset,
                       'category': clip.category, 'original_actor_side': clip.actor_side,
                       'mirrored': mirrored, 'sha256': hashlib.sha256(clip.path.read_bytes()).hexdigest(),
                       'effective_head_sha256': effective_head, 'excluded_training_group': held_out_group,
                       **result, 'people_histogram': dict(protocol.people),
                       'abstention_reasons': dict(protocol.reasons), 'max_score': protocol.max_score}
                rows.append(row)
                print(json.dumps({'clip': row['path'], 'mirrored': mirrored,
                                  'alerts': len(row['events']), 'coverage': row['coverage']}), flush=True)
    finally:
        detector.close()
    if folds:
        identity['visual_head_sha256'] = 'per-clip excluded-group head; see effective_head_sha256'
    report = {'scope': SCOPE, 'qualified': False, 'automatic_calls': False,
              'grouped_validation': bool(folds),
              'fold_manifest_sha256': hashlib.sha256(args.fold_heads.read_bytes()).hexdigest() if folds else None,
              'model': detector.temporal.version, 'identity': identity,
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'jpeg_quality': 75, 'analyzed_fps': 10, 'source_urls': SOURCES,
              'summary': summarize(rows), 'clips': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
