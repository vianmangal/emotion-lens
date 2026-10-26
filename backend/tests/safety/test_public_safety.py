from types import SimpleNamespace

import numpy as np
import pytest

from backend.safety.event_policy import Evidence
from scripts.check_public_safety import CameraProtocol, discover, summarize


def test_public_labels_keep_punch_push_and_actor_side_distinct(tmp_path):
    ut = tmp_path / 'ut-interaction'; ut.mkdir()
    limu = tmp_path / 'limu'; limu.mkdir()
    for name, data in [('0_1_4.avi', b'punch'), ('5_1_5.avi', b'push')]:
        (ut / name).write_bytes(data)
    for name in ['punch_1.avi', 'punch_6.avi']:
        (limu / name).write_bytes(name.encode())
    clips = discover(tmp_path)
    assert {c.path.name: c.category for c in clips}['0_1_4.avi'] == 'punch'
    assert {c.path.name: c.category for c in clips}['5_1_5.avi'] == 'push'
    assert {c.path.name: c.actor_side for c in clips}['punch_1.avi'] == 'left'
    assert {c.path.name: c.actor_side for c in clips}['punch_6.avi'] == 'right'
    (limu / 'punch_6.avi').write_bytes(b'punch')
    with pytest.raises(ValueError, match='Duplicate'):
        discover(tmp_path)


def test_camera_protocol_mirrors_actual_pixels_before_jpeg_encoding():
    received = []
    detector = SimpleNamespace(config=None, temporal=None, reset=lambda: None,
                               process=lambda t, frame: (received.append(frame) or Evidence(True), []))
    frame = np.zeros((48, 64, 3), np.uint8)
    frame[:, :32] = 220
    protocol = CameraProtocol(detector, mirrored=True); protocol.reset()
    protocol.process(1., frame)
    assert received[0][:, :20].mean() < 10
    assert received[0][:, -20:].mean() > 210


def test_public_summary_never_pools_mirrored_copies_as_independent_clips():
    common = {'dataset': 'limu', 'category': 'punch', 'coverage': .5}
    result = summarize([{**common, 'mirrored': False, 'events': [1]},
                        {**common, 'mirrored': True, 'events': []}])
    assert result['limu/original']['punch']['alerted'] == 1
    assert result['limu/mirrored']['punch']['alerted'] == 0
    assert result['limu/original']['punch']['clips'] == 1
