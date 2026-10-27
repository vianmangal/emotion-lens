from concurrent.futures import Future
import json
import threading

import numpy as np
import pytest

from backend.safety.video_model import StrikeHead, VideoAction


def bodies(n=2):
    result = []
    for i in range(n):
        p = np.zeros((17, 3), np.float32)
        p[:, 2] = .99
        result.append({'id': i + 1, 'points': p})
    return result


class ConstantHead:
    def predict(self, feature):
        return float(feature[0])


def fake_model(score=.9, synchronous=True):
    return VideoAction(lambda frames: np.array([score]), ConstantHead(), synchronous=synchronous)


def feed(model, count=45, tracks=None, start=0):
    tracks = bodies() if tracks is None else tracks
    evidence = []
    for i in range(start, start + count):
        evidence.append(model.process_frame(i / 10, np.zeros((48, 64, 3), np.uint8), tracks))
    return evidence


def test_visual_warmup_observed_bodies_and_no_infinite_latch():
    model = fake_model()
    try:
        evidence = feed(model)
        assert not any(e.ready for e in evidence[:30])
        assert evidence[-1].directed and evidence[-1].track_ids == (1, 2)
        # A lone person cannot carry an earlier two-person strike score.
        assert not feed(model, 1, bodies(1), start=45)[0].ready
        # A timestamp gap clears the RGB window and old inference.
        after_gap = model.process_frame(8., np.zeros((48, 64, 3), np.uint8), bodies())
        assert not after_gap.ready and len(model.frames) == 1
    finally:
        model.close()


def test_fresh_negative_video_is_clear_and_buffers_are_bounded():
    model = fake_model(.1)
    try:
        evidence = feed(model, 120)
        assert evidence[-1].ready and not evidence[-1].directed
        assert len(model.frames) <= 34
        assert sum(frame.nbytes for _, frame, _ in model.frames) <= 34 * 256 * 256 * 3
    finally:
        model.close()


@pytest.mark.parametrize('fps', [10, 20, 30])
def test_faster_tracking_preserves_the_trained_action_window(fps):
    model = fake_model()
    try:
        frame = np.zeros((48, 64, 3), np.uint8)
        for i in range(6 * fps):
            result = model.process_frame(i / fps, frame, bodies())
        assert result.ready and result.directed
        assert 30 <= len(model.frames) <= 34
        assert model.frames[-1][0] - model.frames[0][0] >= 3
        # The neural input rate stays 10 FPS even with 30 FPS box tracking.
        assert all(b[0] - a[0] >= .09 for a, b in zip(model.frames, list(model.frames)[1:]))
    finally:
        model.close()


@pytest.mark.parametrize('count', [0, 1, 3])
def test_visual_score_requires_exactly_two_people(count):
    model = fake_model()
    try:
        assert not any(e.ready for e in feed(model, tracks=bodies(count)))
    finally:
        model.close()


def test_hidden_shoulders_do_not_make_a_visual_trial_ready():
    model = fake_model()
    tracks = bodies(); tracks[1]['points'][5, 2] = .1
    try:
        assert not any(e.ready for e in feed(model, tracks=tracks))
    finally:
        model.close()


def test_observed_person_boxes_do_not_depend_on_inferred_arm_joints():
    model = fake_model()
    tracks = bodies()
    for track in tracks:
        track['points'][:, 2] = 0
        track.update(body_observed=True, person_score=.8)
    try:
        result = feed(model, tracks=tracks)[-1]
        assert result.ready and result.directed
        tracks[1]['person_score'] = .1
        assert not feed(model, 1, tracks, start=45)[0].ready
    finally:
        model.close()


def test_reset_discards_a_running_old_session_prediction():
    entered, release = threading.Event(), threading.Event()
    def encoder(frames):
        entered.set()
        assert release.wait(5)
        return np.array([.99])
    model = VideoAction(encoder, ConstantHead())
    try:
        feed(model, 33)
        assert entered.wait(2)
        old_job = model.future
        model.reset()
        release.set()
        old_job.result(timeout=2)
        evidence = feed(model, 1, start=40)[0]
        assert not evidence.ready and model.prediction is None
    finally:
        release.set()
        model.close()


def test_background_inference_does_not_block_frame_processing_or_queue_jobs():
    model = fake_model(synchronous=False)
    # An unfinished job represents a slow neural network. Fresh frames continue
    # without blocking, and no second job or unbounded work queue is created.
    running = Future()
    model.future = running
    try:
        evidence = feed(model, 90)
        assert model.future is running and not any(e.directed for e in evidence)
        assert len(model.frames) <= 34
        model.prediction = (0., .99, 0.)
        assert not feed(model, 1, start=90)[0].directed
    finally:
        running.cancel()
        model.close()


def test_encoder_failure_abstains():
    model = fake_model()
    model.encoder = lambda frames: (_ for _ in ()).throw(RuntimeError('unavailable'))
    try:
        result = feed(model)[-1]
        assert not result.ready and 'unavailable' in result.reasons[0]
    finally:
        model.close()


def test_slow_bounded_video_results_can_open_and_clear_an_episode():
    from backend.safety.event_policy import EventPolicy
    model = fake_model()
    model._predict = lambda frames, generation, captured: (generation, captured, .99 if captured < 6 else .1, .8)
    policy = EventPolicy(cooldown=0)
    policy.arm()
    opened = closed = 0
    try:
        for i in range(150):
            t = i / 10
            evidence = model.process_frame(t, np.zeros((48, 64, 3), np.uint8), bodies())
            created, ended = policy.step(t, evidence)
            opened += created
            closed += ended
        assert opened == 1 and closed == 1
        assert policy.state == 'monitoring'
    finally:
        model.close()


@pytest.mark.parametrize('prediction,ready', [
    ((3.5, .99, 4.3), True),  # Recent source and newly completed result.
    ((1., .99, 5.), False),  # A newly published result cannot revive old video.
    ((5., .99, 1.), False),  # Recent source cannot revive a frozen publisher.
])
def test_video_result_requires_both_source_and_publication_freshness(prediction, ready):
    model = fake_model()
    try:
        feed(model, 50)
        model.prediction, model.pending, model.next_run = prediction, None, float('inf')
        result = model.process_frame(5., np.zeros((48, 64, 3), np.uint8), bodies())
        assert result.ready is ready
    finally:
        model.close()


def test_numeric_head_matches_explicit_two_layer_network_and_rejects_corruption(tmp_path):
    head = {'version': 1, 'kind': 'mlp', 'mean': [0.] * 1024, 'scale': [1.] * 1024,
            'parameters': {'0.weight': np.zeros((32, 1024)).tolist(), '0.bias': [0.] * 32,
                           '2.weight': [[1.] * 32], '2.bias': [0.]}}
    head['parameters']['0.weight'][0][0] = 1
    path = tmp_path / 'head.json'; path.write_text(json.dumps(head))
    feature = np.zeros(1024, np.float32); feature[0] = 2
    assert StrikeHead(path).predict(feature) == pytest.approx(1 / (1 + np.exp(-2)))
    head['scale'][0] = 0; path.write_text(json.dumps(head))
    with pytest.raises(ValueError, match='normalization'):
        StrikeHead(path)
