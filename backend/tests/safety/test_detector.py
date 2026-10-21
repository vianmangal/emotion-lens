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
    assert not baseline.classify(history(True,visible=False),(480,640,3)).ready
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
    sequence[-4][1][0]['points'][10, 2] = .1
    evidence = TrajectoryBaseline().classify(sequence, (480, 640, 3))
    assert not evidence.ready and 'occluded' in evidence.reasons[0]


def test_pose_occlusion_clears_window_before_visibility_recovers():
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
        poses.append(landmarks)
    detector.pose = SimpleNamespace(detect=lambda _: SimpleNamespace(pose_landmarks=poses))
    frame = np.zeros((48,64,3), np.uint8)
    for i in range(10): detector.process(i/10, frame)
    assert len(detector.history) >= 8
    poses[0][15].visibility = .1
    evidence, _ = detector.process(1., frame)
    assert not evidence.ready and not detector.history
    poses[0][15].visibility = .99
    evidence, _ = detector.process(1.1, frame)
    assert not evidence.ready and len(detector.history) == 1


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
