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
