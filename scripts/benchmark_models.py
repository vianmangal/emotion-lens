"""Feasibility smoke tests on generated data. This does NOT measure real-world accuracy."""
import json
import platform
from pathlib import Path
import resource
import sys
import time
import importlib.metadata as metadata
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from replay import model_settings
from backend.safety.detector import Detector
from backend.safety.temporal_model import TrajectoryBaseline, STGCNTemporal


def skeleton_history(motion):
    points=np.zeros((17,3),np.float32);points[:,2]=.99
    points[:,:2]=np.array([[.3,.15],[.29,.14],[.31,.14],[.27,.15],[.33,.15],[.25,.3],[.35,.3],[.23,.4],[.37,.4],[.22,.5],[.38,.5],[.27,.55],[.33,.55],[.27,.7],[.33,.7],[.27,.85],[.33,.85]])
    result=[]
    for i in range(34):
        a=points.copy();b=points.copy();b[:,0]+=.35
        if motion == 'directed_arm' and i >= 29:
            a[10,0]=.38 + (i-29)*.05; a[10,1]=.5-(i-29)*.025
        elif motion == 'wave':
            a[10,:2]=[.4 + .04*np.sin(i/2), .15]
        tracks=[{'id':1,'points':a},{'id':2,'points':b}]
        if motion == 'lone_person': tracks=tracks[:1]
        result.append((i/10,tracks))
    return result


def benchmark(classifier, history):
    timings=[]
    for _ in range(15):
        start=time.perf_counter();result=classifier.classify(history,(480,640,3));timings.append((time.perf_counter()-start)*1000)
    return {'ready':result.ready,'score':result.score,'directed':result.directed,'reasons':list(result.reasons),
            'median_ms':float(np.median(timings[3:])), 'p95_ms':float(np.percentile(timings[3:],95))}


def main():
    cfg=model_settings('baseline'); detector=Detector(cfg)
    if not detector.ready: raise SystemExit(detector.reason)
    timings=[]
    for i in range(60):
        start=time.perf_counter();e,_=detector.process(i/10,np.zeros((480,640,3),np.uint8));timings.append((time.perf_counter()-start)*1000)
    detector.close()
    temporal=STGCNTemporal(cfg.SAFETY_STGCN_CONFIG,cfg.SAFETY_STGCN_PATH)
    results={motion:{'baseline':benchmark(TrajectoryBaseline(),skeleton_history(motion)), 'stgcn':benchmark(temporal,skeleton_history(motion))} for motion in ['stationary','directed_arm','wave','lone_person']}
    packages=['mediapipe','numpy','opencv-contrib-python','torch','torchvision','mmengine','mmcv-lite','fastapi','SQLAlchemy','aiosqlite']
    report={'data':'Generated blank frames and synthetic skeletons ONLY; no people or accuracy evaluation',
            'python':sys.version.split()[0],'platform':platform.platform(),'packages':{p:metadata.version(p) for p in packages},
            'pose_blank_frame_median_ms':float(np.median(timings[10:])), 'pose_blank_frame_p95_ms':float(np.percentile(timings[10:],95)),
            'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'synthetic_temporal_comparison':results,'qualified':False}
    target=ROOT/'docs/SAFETY_BENCHMARK.json';target.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__ == '__main__':main()
