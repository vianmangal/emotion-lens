from pathlib import Path
import time
import uuid
import cv2
import numpy as np


class RecordingStore:
    def __init__(self, config):
        self.root = config.DATA_DIR.resolve()
        self.directory = self.root / 'clips'
        self.quota = config.SAFETY_CLIP_QUOTA_MB * 1024 * 1024
        self.available = False
        self.reason = 'Clip storage unavailable'
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.path('probe.webm')
            self.available = self._probe()
            self.reason = 'VP8/WebM, no audio; 24-hour default retention' if self.available else 'VP8 codec unavailable; recording disabled'
        except (OSError, ValueError):
            pass

    def path(self, name):
        if not name or Path(name).name != name or self.directory.is_symlink():
            raise ValueError('Invalid clip reference')
        path = self.directory / name
        if path.is_symlink() or path.resolve().parent != self.directory.resolve() or self.directory.resolve().parent != self.root:
            raise ValueError('Clip path escapes data directory')
        return path

    def usage(self):
        try:
            return sum(p.stat().st_size for p in self.directory.glob('*.webm') if not p.is_symlink())
        except OSError:
            return 0

    def _probe(self):
        name = f'probe-{uuid.uuid4()}.webm'
        path = self.path(name)
        try:
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'VP80'), 10, (64, 48))
            if not writer.isOpened():
                writer.release()
                return False
            for _ in range(3):
                writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
            writer.release()
            capture = cv2.VideoCapture(str(path))
            ok, _ = capture.read()
            capture.release()
            return ok
        finally:
            path.unlink(missing_ok=True)

    def encode(self, event_id, frames, partial=False):
        details = {'partial': partial, 'audio': False, 'fps': 10, 'source_frames': len(frames)}
        if not self.available or not frames:
            return None, 'unavailable', details
        frames = sorted(frames, key=lambda x: x[0])
        start, end = frames[0][0], frames[-1][0]
        details.update(duration_seconds=round(end - start, 3), max_source_gap_seconds=round(max((b[0] - a[0] for a, b in zip(frames, frames[1:])), default=0), 3))
        # Reserve a conservative raw-frame upper bound before admitting the write.
        reserve = min(int((end - start) * 10 + 1), 101) * 640 * 480 * 3
        if self.usage() + reserve > self.quota:
            return None, 'quota_exceeded', details
        name = f'{uuid.UUID(event_id)}.webm'
        path = self.path(name)
        writer = None
        try:
            first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
            h, w = first.shape[:2]
            # VP8 needs even dimensions.
            w, h = w - w % 2, h - h % 2
            if min(w, h) < 2:
                raise ValueError('Clip frames too small')
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'VP80'), 10, (w, h))
            if not writer.isOpened():
                raise OSError('Codec not available')
            index = 0
            for t in np.arange(start, min(end + .05, start + 10.1), .1):
                while index + 1 < len(frames) and frames[index + 1][0] <= t:
                    index += 1
                image = cv2.imdecode(np.frombuffer(frames[index][1], np.uint8), cv2.IMREAD_COLOR)
                writer.write(cv2.resize(image, (w, h)))
            writer.release()
            writer = None
            if not path.exists() or path.stat().st_size == 0 or self.usage() > self.quota:
                raise OSError('Clip write or quota failure')
            return name, 'partial' if partial else 'ready', details
        except (OSError, ValueError, cv2.error, AttributeError):
            if writer:
                writer.release()
            path.unlink(missing_ok=True)
            return None, 'write_failed', details

    def delete(self, name):
        if name:
            self.path(name).unlink(missing_ok=True)
