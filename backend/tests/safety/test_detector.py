import numpy as np
from backend.safety.tracking import Tracker
from backend.safety.temporal_model import TrajectoryBaseline
from backend.safety.detector import verify_artifact
from backend.safety.event_policy import EventPolicy
import pytest


def history(directed=False, people=2, visible=True):
    result=[]
    for i in range(20):
        points=np.zeros((17,3),np.float32);points[:,2]=.99
        points[:,0]=.3;points[:,1]=.4
        points[5,:2]=[.25,.3];points[6,:2]=[.35,.3]
        points[9,:2]=[.22,.5];points[10,:2]=[.38,.5]
        if directed and i>=14:points[10,:2]=[.38+(i-14)*.05,.5-(i-14)*.025]
        other=points.copy();other[:,0]+=.35
        if not visible:points[10,2]=.1
        tracks=[{'id':1,'points':points},{'id':2,'points':other}][:people]
        result.append((i/10,tracks))
    return result


def test_real_trajectory_baseline_and_visibility_abstention():
    baseline=TrajectoryBaseline()
    positive=baseline.classify(history(True),(480,640,3))
    assert positive.directed and positive.score >= .75
    assert not baseline.classify(history(),(480,640,3)).directed
    assert not baseline.classify(history(True,1),(480,640,3)).ready
    assert not baseline.classify(history(True,visible=False),(480,640,3)).directed
    assert not baseline.classify(history()[:3],(480,640,3)).ready


def test_tracker_identity_loss_and_checksum_fail_closed(tmp_path):
    tracker=Tracker()
    points=history()[-1][1][0]['points']
    first,changed=tracker.update([points]);assert changed
    second,changed=tracker.update([points]);assert not changed and first[0]['id']==second[0]['id']
    tracker.update([])
    third,changed=tracker.update([points]);assert changed and third[0]['id']!=first[0]['id']
    artifact=tmp_path/'model';artifact.write_bytes(b'wrong')
    with pytest.raises(ValueError):verify_artifact(str(artifact),'0'*64)


def test_seated_upper_body_does_not_require_visible_hips():
    sequence = history(True)
    for _, tracks in sequence:
        for track in tracks:
            track['points'][[11, 12], 2] = 0
            track['points'][[11, 12], :2] = [3., -2.]
    evidence = TrajectoryBaseline().classify(sequence, (480, 640, 3))
    assert evidence.ready and evidence.directed and evidence.track_ids == (1, 2)
    # Removing the hip requirement must not waive observed arm landmarks.
    sequence[-2][1][0]['points'][10, 2] = .1
    assert not TrajectoryBaseline().classify(sequence, (480, 640, 3)).directed


def test_hidden_hip_estimates_cannot_move_track_identity():
    tracker = Tracker()
    points = history()[-1][1][0]['points'].copy()
    points[[11, 12], 2] = 0
    first, _ = tracker.update([points])
    points[[11, 12], :2] = [8., -8.]
    second, changed = tracker.update([points])
    assert not changed and second[0]['id'] == first[0]['id']


@pytest.mark.parametrize('top,accepted', [(49, True), (50, True), (51, False), (53, False), (54, False)])
def test_ntu60_upstream_class_indices_keep_punch_and_exclude_push(top, accepted):
    from types import SimpleNamespace
    from backend.safety.temporal_model import STGCNTemporal
    class Score:
        def detach(self): return self
        def cpu(self): return self
        def numpy(self):
            result = np.zeros(60); result[top] = .9
            return result
    temporal = STGCNTemporal.__new__(STGCNTemporal)
    temporal.model = object()
    temporal.infer = lambda *_: SimpleNamespace(pred_score=Score())
    sequence = history(True)
    # Stable initial observation followed by the actual directed-arm trajectory.
    window = [(i/10, sequence[max(0, i-14)][1]) for i in range(34)]
    evidence = temporal.classify(window, (480, 640, 3))
    assert evidence.directed
    assert (evidence.score == .9) is accepted


def test_inferred_wrist_after_occlusion_cannot_form_a_strike():
    sequence = history(True)
    # The earlier wrist observation is unreliable, although the current arm is visible.
    sequence[-2][1][0]['points'][10, 2] = .1
    evidence = TrajectoryBaseline().classify(sequence, (480, 640, 3))
    assert not evidence.directed


def test_occlusion_invalidates_only_the_affected_participant_window():
    from collections import deque
    from types import SimpleNamespace
    from backend.safety.detector import Detector
    from backend.safety.tracking import COCO_FROM_MP
    detector = Detector.__new__(Detector)
    detector.ready = True
    detector.history = deque(maxlen=120)
    detector.tracker = Tracker()
    detector.temporal = TrajectoryBaseline()
    detector.mp = SimpleNamespace(Image=lambda **kwargs: object(), ImageFormat=SimpleNamespace(SRGB='rgb'))
    points = history()[-1][1]
    poses = []
    for track in points:
        landmarks = [SimpleNamespace(x=.3, y=.4, visibility=.99, presence=.99) for _ in range(33)]
        for coco, mp in enumerate(COCO_FROM_MP):
            landmarks[mp].x, landmarks[mp].y = track['points'][coco, :2]
        # A seated webcam user can have fully observed arms but off-screen hips.
        for index in (23, 24):
            landmarks[index].y = 1.5
            landmarks[index].visibility = .1
        poses.append(landmarks)
    detector.pose = SimpleNamespace(detect=lambda _: SimpleNamespace(pose_landmarks=poses))
    frame = np.zeros((48,64,3), np.uint8)
    for i in range(10): detector.process(i/10, frame)
    assert len(detector.history) >= 8
    poses[0][15].visibility = .1
    evidence, _ = detector.process(1., frame)
    assert evidence.ready and not evidence.directed and detector.history
    # Losing a shoulder invalidates both interactions with that participant,
    # while retaining observations for any other visible pair.
    poses[0][11].visibility = .1
    evidence, _ = detector.process(1.1, frame)
    assert not evidence.ready and detector.history
    poses[0][15].visibility = .99
    poses[0][11].visibility = .99
    evidence, _ = detector.process(1.2, frame)
    assert not evidence.ready and len(detector.history) > 1
    detector.process(1.3, frame)
    evidence, _ = detector.process(1.4, frame)
    assert evidence.ready and not evidence.directed


def test_returning_pose_cannot_steal_a_closer_persons_identity():
    from backend.safety.tracking import tracking_center
    p = history()[-1][1][0]['points'].copy()
    p[:, 0] += .25  # Shoulder center .55.
    tracker = Tracker()
    original, _ = tracker.update([p])
    returning = p.copy(); returning[:, 0] -= .249
    same_person = p.copy(); same_person[:, 0] += .002
    tracks, changed = tracker.update([returning, same_person])
    assert changed  # A genuinely new track still has a new identity.
    retained = next(track for track in tracks if track['id'] == original[0]['id'])
    assert np.allclose(tracking_center(retained['points']), tracking_center(same_person))


def test_global_tracking_is_independent_of_pose_order_and_rejects_real_ambiguity():
    from backend.safety.tracking import tracking_center
    a = history()[-1][1][0]['points'].copy()
    b = a.copy(); b[:, 0] += .25
    tracker = Tracker()
    first, _ = tracker.update([a, b])
    second, changed = tracker.update([b, a])
    assert not changed
    assert all(np.allclose(tracking_center(x['points']), tracking_center(y['points']))
               for x, y in zip(first, second))
    midpoint = (a + b) / 2
    third, changed = tracker.update([midpoint.copy(), midpoint.copy()])
    assert changed and not {track['id'] for track in first} & {track['id'] for track in third}


def test_person_box_tracking_uses_observed_box_anchors_without_fake_landmarks():
    tracker = Tracker()
    points = [np.zeros((17, 3), np.float32) for _ in range(2)]
    boxes = [[.1, .1, .4, .9], [.6, .1, .9, .9]]
    first, _ = tracker.update(points, boxes, [.9, .8])
    second, changed = tracker.update(points, list(reversed(boxes)), [.8, .9])
    assert not changed
    assert [track['box'] for track in second] == boxes
    assert [track['id'] for track in first] == [track['id'] for track in second]
    assert all(track['body_observed'] and not track['points'].any() for track in second)


def test_temporal_model_and_trajectory_gate_use_same_pair_with_bystanders():
    from types import SimpleNamespace
    from backend.safety.temporal_model import STGCNTemporal
    sequence = history(True)
    window = []
    stationary_target = sequence[0][1][1]['points']
    for i in range(34):
        actors = sequence[max(0, i-14)][1]
        quiet_left = stationary_target.copy(); quiet_left[:, 0] -= .55
        quiet_right = stationary_target.copy(); quiet_right[:, 0] += .25
        tracks = [{'id': 1, 'points': quiet_left}, {'id': 2, 'points': quiet_right},
                  {'id': 3, 'points': actors[0]['points']}, {'id': 4, 'points': stationary_target}]
        window.append((i/10, tracks))
    class Score:
        def detach(self): return self
        def cpu(self): return self
        def numpy(self):
            values = np.zeros(60); values[49] = .9
            return values
    def infer(_, data):
        # Track 3 is the source; track 4 is the target. Track 1 must not be sent
        # to STGCN simply because it was observed before the interacting pair.
        assert np.isclose(data['keypoint'][0, -1, 5, 0], .25 * 640)
        assert np.isclose(data['keypoint'][1, -1, 5, 0], .6 * 640)
        return SimpleNamespace(pred_score=Score())
    temporal = STGCNTemporal.__new__(STGCNTemporal)
    temporal.model = object(); temporal.infer = infer
    evidence = temporal.classify(window, (480,640,3))
    assert evidence.directed and evidence.track_ids == (3,4) and evidence.score == .9


def test_small_head_proposal_is_not_counted_as_another_person():
    from backend.safety.detector import unique_person_boxes
    left=[.02,.35,.31,1.]
    head=[.02,.25,.16,.55]
    right=[.5,.2,.95,1.]
    boxes,scores=unique_person_boxes([head,left,right],[.22,.5,.7])
    assert boxes==[right,left] and scores==[.7,.5]


def test_distinct_people_and_similar_sized_overlapping_boxes_are_kept():
    from backend.safety.detector import unique_person_boxes
    boxes=[[.02,.2,.31,1.],[.2,.2,.49,1.],[.6,.2,.95,1.]]
    result,_=unique_person_boxes(boxes,[.8,.8,.8])
    assert len(result)==3
