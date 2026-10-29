"""Extract frozen S3D features from the documented public research clips."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.safety.detector import verify_artifact
from backend.safety.video_model import S3DEncoder
from scripts.check_public_safety import discover, SOURCES
from scripts.replay import model_settings


def frames_at_ten_fps(path):
    capture = cv2.VideoCapture(str(path))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
            raise ValueError(f'Cannot decode {path}')
        frames = []
        index, next_t = 0, 0.
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            t = index / fps; index += 1
            if t + 1e-6 < next_t:
                continue
            next_t = (math.floor(t * 10 + 1e-6) + 1) / 10
            scale = min(640 / frame.shape[1], 480 / frame.shape[0], 1)
            frame = cv2.resize(frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale)))
            ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise ValueError('JPEG encoding failed')
            frame = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
            frames.append(cv2.cvtColor(cv2.resize(frame, (256, 256)), cv2.COLOR_BGR2RGB))
        if not frames:
            raise ValueError(f'Empty clip: {path}')
        return frames
    finally:
        capture.release()


def windows(frames):
    if len(frames) <= 32:
        yield [frames[0]] * (32 - len(frames)) + frames, 'action'
    else:
        starts = sorted(set([0, len(frames) - 32] + list(range(0, len(frames) - 31, 16))))
        for start in starts:
            yield frames[start:start + 32], f'window-{start}'
    # A stationary stance, even from a punching clip, is a negative example.
    yield [frames[0]] * 32, 'static'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT / 'data/public-evaluation')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists; choose a new feature filename')
    config = model_settings('visual')
    verify_artifact(config.SAFETY_VISUAL_WEIGHTS_PATH, config.SAFETY_VISUAL_WEIGHTS_SHA256)
    encoder = S3DEncoder(config.SAFETY_VISUAL_WEIGHTS_PATH)
    features, labels, groups, metadata = [], [], [], []
    clips = discover(args.root)
    for number, clip in enumerate(clips):
        frames = frames_at_ten_fps(clip.path)
        group = ('limu/' + clip.path.stem.rsplit('_', 1)[1] if clip.dataset == 'limu' else
                 'ut/' + clip.path.stem.split('_')[1])
        checksum = hashlib.sha256(clip.path.read_bytes()).hexdigest()
        for mirrored in (False, True):
            for sample, name in windows(frames):
                batch = np.stack(sample)
                if mirrored:
                    batch = batch[:, :, ::-1, :].copy()
                features.append(encoder(batch))
                labels.append(int(clip.category == 'punch' and name != 'static'))
                groups.append(group)
                metadata.append(json.dumps({'path': str(clip.path.relative_to(args.root)),
                                            'sha256': checksum, 'category': clip.category,
                                            'window': name, 'mirrored': mirrored}))
        print(f'{number + 1}/{len(clips)} {clip.path.name}', flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, x=np.stack(features), y=np.array(labels),
                        groups=np.array(groups), metadata=np.array(metadata))
    args.output.with_suffix('.json').write_text(json.dumps({
        'scope': 'Development features, weak clip-level labels and static negatives. MIL pools positive windows.',
        'weights_sha256': config.SAFETY_VISUAL_WEIGHTS_SHA256,
        'frames': 32, 'fps': 10, 'jpeg_quality': 75, 'sources': SOURCES,
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
