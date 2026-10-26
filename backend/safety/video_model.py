"""Bounded, local RGB action inference. No camera access, disk recording or calls."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import time

import cv2
import numpy as np

from backend.safety.event_policy import Evidence

PERSON_SCORE_THRESHOLD = .2


class StrikeHead:
    """Numeric MLP artifact; no pickle or executable model configuration."""

    def __init__(self, path):
        with open(path) as source:
            artifact = json.load(source)
        if artifact.get('version') != 1 or artifact.get('kind') != 'mlp':
            raise ValueError('Unsupported visual strike head')
        self.mean = np.asarray(artifact['mean'], np.float32)
        self.scale = np.asarray(artifact['scale'], np.float32)
        params = artifact['parameters']
        self.w1 = np.asarray(params['0.weight'], np.float32)
        self.b1 = np.asarray(params['0.bias'], np.float32)
        self.w2 = np.asarray(params['2.weight'], np.float32)
        self.b2 = np.asarray(params['2.bias'], np.float32)
        shapes = [(self.mean, (1024,)), (self.scale, (1024,)),
                  (self.w1, (32, 1024)), (self.b1, (32,)),
                  (self.w2, (1, 32)), (self.b2, (1,))]
        if any(value.shape != shape or not np.isfinite(value).all() for value, shape in shapes):
            raise ValueError('Invalid visual head dimensions or values')
        if np.any(self.scale <= 0):
            raise ValueError('Invalid visual head normalization')

    def predict(self, feature):
        feature = np.asarray(feature, np.float32)
        if feature.shape != (1024,) or not np.isfinite(feature).all():
            raise ValueError('Invalid visual feature')
        hidden = np.maximum(self.w1 @ ((feature - self.mean) / self.scale) + self.b1, 0)
        logit = float((self.w2 @ hidden + self.b2)[0])
        return float(1 / (1 + np.exp(-np.clip(logit, -30, 30))))


class S3DEncoder:
    def __init__(self, weights):
        # Optional runtime only. Model files must already exist and be verified
        # by Detector; startup never downloads a model or imports expression AI.
        import torch
        from torchvision.models.video import s3d, S3D_Weights
        torch.set_num_threads(4)
        self.torch = torch
        self.model = s3d(weights=None).eval()
        self.model.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True))
        self.transform = S3D_Weights.KINETICS400_V1.transforms()

    def __call__(self, frames):
        video = self.torch.from_numpy(frames).permute(0, 3, 1, 2)
        batch = self.transform(video).unsqueeze(0)
        with self.torch.inference_mode():
            encoded = self.model.avgpool(self.model.features(batch)).mean(dim=(2, 3, 4))
        return encoded[0].numpy()


class VideoAction:
    """One RGB window and one inference job; stale/session-old scores abstain."""
    version = 'learned-video-s3d-strike-v1 (experimental)'
    window_seconds = 3.3
    interval_seconds = .5
    max_score_age_seconds = 1.

    def __init__(self, encoder, head, synchronous=False):
        self.encoder, self.head = encoder, head
        self.synchronous = synchronous  # Offline replay only; includes measured inference delay.
        self.executor = None if synchronous else ThreadPoolExecutor(max_workers=1, thread_name_prefix='local-video-action')
        self.future = None
        self.generation = 0
        self.frames = deque(maxlen=48)
        self.reset()

    def reset(self):
        self.generation += 1
        self.frames.clear()
        self.prediction = None
        self.pending = None
        self.next_run = -1.
        self.failure = False
        if self.future is not None:
            self.future.cancel()

    def close(self):
        self.reset()
        if self.executor:
            self.executor.shutdown(wait=True, cancel_futures=True)

    def _predict(self, frames, generation, captured):
        start = time.perf_counter()
        score = self.head.predict(self.encoder(frames))
        if not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid visual action score')
        elapsed = time.perf_counter() - start
        return generation, captured, score, elapsed

    @staticmethod
    def two_bodies(tracks):
        return len(tracks) == 2 and all(
            (p.get('body_observed') is True and p.get('person_score', 0) >= PERSON_SCORE_THRESHOLD) or
            np.min(p['points'][[5, 6], 2]) >= .55 for p in tracks)

    def process_frame(self, t, frame, tracks):
        if self.frames and (t <= self.frames[-1][0] or t - self.frames[-1][0] > 1):
            self.reset()
        current_valid = self.two_bodies(tracks)
        rgb = cv2.cvtColor(cv2.resize(frame, (256, 256)), cv2.COLOR_BGR2RGB)
        self.frames.append((t, rgb, current_valid))
        while self.frames and t - self.frames[0][0] > self.window_seconds:
            self.frames.popleft()

        try:
            if self.future is not None and self.future.done():
                if not self.future.cancelled():
                    self.pending = self.future.result()
                self.future = None
            if self.pending:
                generation, captured, score, elapsed = self.pending
                # Replay computes synchronously, then waits on source time for
                # the actual measured inference cost before publishing a score.
                if not self.synchronous or t >= captured + elapsed:
                    if generation == self.generation:
                        self.prediction = (captured, score)
                    self.pending = None
        except Exception:
            self.failure = True
            self.prediction = None
            self.future = None
            self.pending = None

        samples = list(self.frames)
        ready_window = (len(samples) >= 24 and t - samples[0][0] >= 3.0 and
                        sum(sample[2] for sample in samples) / len(samples) >= .8 and
                        all(b[0] - a[0] <= .5 for a, b in zip(samples, samples[1:])))
        if not self.failure and current_valid and ready_window and t >= self.next_run and self.future is None and self.pending is None:
            times = np.array([sample[0] for sample in samples])
            indices = [int(np.argmin(np.abs(times - wanted))) for wanted in np.linspace(t - 3.1, t, 32)]
            batch = np.stack([samples[index][1] for index in indices])
            self.next_run = t + self.interval_seconds
            if self.synchronous:
                try:
                    self.pending = self._predict(batch, self.generation, t)
                except Exception:
                    self.failure = True
            else:
                self.future = self.executor.submit(self._predict, batch, self.generation, t)

        people = len(tracks)
        if self.failure:
            return Evidence(False, people=people, reasons=('Action model unavailable; stop and restart detection',))
        if not current_valid:
            reason = ('Keep exactly two people in the frame' if people != 2 else 'Keep both people’s shoulders in frame')
            return Evidence(False, people=people, reasons=(reason,))
        if not ready_window:
            return Evidence(False, people=people, reasons=('Building a clear two-person action window…',))
        if self.prediction is None or not 0 <= t - self.prediction[0] <= self.max_score_age_seconds:
            return Evidence(False, people=people, reasons=('Waiting for fresh action analysis…',))
        score = self.prediction[1]
        return Evidence(True, score, score >= .75, people,
                        ('Experimental visual action score; possible striking motion',),
                        tuple(p['id'] for p in tracks) if score >= .75 else ())
