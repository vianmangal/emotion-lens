from types import SimpleNamespace
import copy
import numpy as np
import pytest
from backend.config import Settings
from backend.safety.event_policy import Evidence, threshold_version
from scripts.evaluate import match_events, validate_manifest, verify_frozen_development, pipeline_identity
from scripts.replay import replay


def test_matching_does_not_steal_later_events_and_counts_duplicates():
    assert match_events([3, 6], [0, 3])[:3] == (2, 0, 0)
    assert match_events([3, 3.1, 6], [0, 3])[:3] == (2, 1, 0)
    assert match_events([-.1, 10], [0, 3])[:3] == (0, 2, 2)


def clip(path, split='development', participant='p1', session='s1'):
    return {'path': path, 'source': 'staged with consent', 'license': 'private evaluation',
            'participants': [participant], 'session': session, 'angle': 'front', 'lighting': 'day',
            'category': 'wave', 'split': split, 'onsets': []}


def test_manifest_rejects_group_leakage_renamed_duplicate_and_invalid_onsets(tmp_path):
    (tmp_path/'a.mp4').write_bytes(b'first')
    (tmp_path/'b.mp4').write_bytes(b'second')
    a, b = clip('a.mp4'), clip('b.mp4', 'held_out', 'p2', 's2')
    assert len(validate_manifest({'clips': [a, b]}, tmp_path)) == 2
    leaked = {**b, 'participants': ['p1']}
    with pytest.raises(ValueError, match='leakage'): validate_manifest({'clips': [a, leaked]}, tmp_path)
    (tmp_path/'b.mp4').write_bytes(b'first')
    with pytest.raises(ValueError, match='Duplicate video'): validate_manifest({'clips': [a, b]}, tmp_path)
    for onset in (-1, float('nan'), float('inf'), True):
        with pytest.raises(ValueError, match='Onsets'): validate_manifest({'clips': [{**a, 'onsets': [onset]}]}, tmp_path)


def test_held_out_policy_and_pipeline_must_match_frozen_development(config):
    current = {'model': 'baseline', 'identity': pipeline_identity(config)}
    development = {'split': 'development', **current}
    verify_frozen_development(current, development)
    changed = copy.deepcopy(current)
    config.SAFETY_EVENT_ENTRY_SCORE = .8
    changed['identity'] = pipeline_identity(config)
    with pytest.raises(ValueError, match='frozen development'): verify_frozen_development(changed, development)
    with pytest.raises(ValueError, match='development report'): verify_frozen_development(current, {**development, 'split': 'held_out'})


class FakeCapture:
    def __init__(self, timestamps, fps=25):
        self.timestamps, self.fps, self.index, self.closed = timestamps, fps, -1, False
    def isOpened(self): return True
    def get(self, prop):
        import cv2
        return self.fps if prop == cv2.CAP_PROP_FPS else self.timestamps[max(self.index, 0)] * 1000
    def read(self):
        self.index += 1
        return (True, np.zeros((48, 64, 3), np.uint8)) if self.index < len(self.timestamps) else (False, None)
    def release(self): self.closed = True


class FakeDetector:
    def __init__(self, config):
        self.config = config
        self.temporal = SimpleNamespace(version='test', window_seconds=1.2)
        self.timestamps = []
    def reset(self): self.timestamps.clear()
    def process(self, t, frame):
        self.timestamps.append(t)
        return Evidence(True, .9, True, 2), []


def test_replay_keeps_target_cadence_and_live_policy(monkeypatch, config):
    capture = FakeCapture([i/25 for i in range(100)])
    monkeypatch.setattr('scripts.replay.cv2.VideoCapture', lambda _: capture)
    detector = FakeDetector(config)
    default = replay('fixture.mp4', detector)
    assert default['analyzed_frames'] == 40
    assert capture.closed and default['timestamp_source'] == 'presentation_timestamps'
    assert len(default['events']) == 1
    # The exact same configured entry threshold must suppress live and replay evidence.
    config.SAFETY_EVENT_ENTRY_SCORE = .95
    capture = FakeCapture([i/25 for i in range(100)])
    result = replay('fixture.mp4', detector)
    assert result['events'] == []
    assert result['threshold_version'] != default['threshold_version']
    assert result['threshold_version'] == threshold_version(config.event_policy_options())


def test_replay_preserves_variable_timestamps_and_releases_on_failure(monkeypatch, config):
    capture = FakeCapture([0, .04, .12, .2, .6, 1.2], fps=25)
    monkeypatch.setattr('scripts.replay.cv2.VideoCapture', lambda _: capture)
    detector = FakeDetector(config)
    replay('fixture.mp4', detector)
    assert detector.timestamps == [0, .12, .2, .6, 1.2]
    assert capture.closed
    capture = FakeCapture([0, .2, .1], fps=25)
    with pytest.raises(ValueError, match='timestamps'): replay('fixture.mp4', detector)
    assert capture.closed


@pytest.mark.parametrize('values', [
    {'SAFETY_EVENT_ENTRY_SCORE': .3, 'SAFETY_EVENT_EXIT_SCORE': .4},
    {'SAFETY_EVENT_ENTRY_SCORE': float('nan')},
    {'SAFETY_EVENT_QUIET_SECONDS': 0},
])
def test_invalid_policy_settings_are_rejected(values):
    with pytest.raises(ValueError): Settings(_env_file=None, **values)
