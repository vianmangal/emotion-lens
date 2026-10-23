"""Generated pose-sequence regressions, not measurements of camera accuracy."""
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from backend.safety.detector import Detector
from backend.safety.event_policy import EventPolicy
from backend.safety.temporal_model import TrajectoryBaseline
from backend.safety.tracking import COCO_FROM_MP, Tracker


def points():
    p = np.zeros((17, 3), np.float32)
    p[:, 2] = .95
    p[:, :2] = [.3, .4]
    p[0, :2] = [.3, .18]
    p[5, :2], p[6, :2] = [.25, .3], [.35, .3]
    p[7, :2], p[8, :2] = [.22, .4], [.4, .4]
    p[9, :2], p[10, :2] = [.22, .5], [.38, .44]
    p[11, :2], p[12, :2] = [.27, .7], [.33, .7]
    return p


def sequence(kind='strike', hidden_unused=False):
    result = []
    for i in range(45):
        p = points()
        q = points(); q[:, 0] += .35
        # A 200 ms outward movement followed immediately by retraction. A
        # current-vs-350-ms-old comparison loses the event before the policy
        # has accumulated its 300 ms candidate confirmation.
        outward = {10: [.49, .38], 11: [.60, .31]}
        if kind in ('strike', 'hidden_strike') and i in outward:
            p[10, :2] = outward[i]
        if kind == 'wave' and i in (10, 11):
            p[10, :2] = [.38, .44 - (i - 9) * .12]
        if kind == 'away' and i in (10, 11):
            p[10, :2] = [.38 - (i - 9) * .11, .44]
        if kind == 'body_translation':
            p[:, 0] += min(max(i - 9, 0), 3) * .07
        if kind == 'one_frame_glitch' and i == 10:
            p[10, :2] = [.60, .31]
        if kind == 'hidden_strike' and 9 <= i <= 12:
            p[10, 2] = .05
        if kind == 'reappearance_jump':
            if 9 <= i <= 11:
                p[10, 2] = .05
            if 9 <= i <= 15:
                p[10, :2] = [.60, .31]
        if hidden_unused:
            p[9, 2] = .05
            q[[9, 10], 2] = .05
        result.append((i / 10, [p, q]))
    return result


def detector_for(poses):
    detector = Detector.__new__(Detector)
    detector.ready = True
    detector.history = deque(maxlen=120)
    detector.tracker = Tracker()
    detector.temporal = TrajectoryBaseline()
    detector.mp = SimpleNamespace(Image=lambda **kwargs: object(), ImageFormat=SimpleNamespace(SRGB='rgb'))
    detector.pose = SimpleNamespace(detect=lambda _: SimpleNamespace(pose_landmarks=poses))
    return detector


def run(kind, hidden_unused=False):
    poses = []
    detector = detector_for(poses)
    policy = EventPolicy(cooldown=0); policy.arm()
    events, ends, scores = [], [], []
    frame = np.zeros((480, 640, 3), np.uint8)
    for t, actors in sequence(kind, hidden_unused):
        poses.clear()
        for p in actors:
            landmarks = [SimpleNamespace(x=.3, y=.4, visibility=.95, presence=.95) for _ in range(33)]
            for ci, mi in enumerate(COCO_FROM_MP):
                landmarks[mi] = SimpleNamespace(x=float(p[ci, 0]), y=float(p[ci, 1]),
                                                visibility=float(p[ci, 2]), presence=float(p[ci, 2]))
            poses.append(landmarks)
        evidence, tracks = detector.process(t, frame)
        created, ended = policy.step(t, evidence)
        if created:
            events.append(t)
            assert evidence.track_ids == (tracks[0]['id'], tracks[1]['id'])
        if ended:
            ends.append(t)
        scores.append(evidence.score)
    return events, ends, scores


@pytest.mark.parametrize('hidden_unused', [False, True])
def test_brief_strike_reaches_policy_even_after_hand_retracts(hidden_unused):
    events, ends, scores = run('strike', hidden_unused)
    assert len(events) == 1 and 1.2 <= events[0] <= 1.5
    assert len(ends) == 1 and ends[0] < 4.4
    assert scores[-1] == 0  # The completed motion does not latch forever.


@pytest.mark.parametrize('kind', ['still', 'wave', 'away', 'body_translation', 'hidden_strike', 'reappearance_jump', 'one_frame_glitch'])
def test_non_strikes_and_unobserved_jumps_do_not_open_an_alert(kind):
    events, _, _ = run(kind)
    assert events == []
