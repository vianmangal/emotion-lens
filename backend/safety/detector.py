from collections import deque
import hashlib
from pathlib import Path
import numpy as np
import cv2
from backend.safety.tracking import Tracker, COCO_FROM_MP, UPPER_BODY
from backend.safety.temporal_model import TrajectoryBaseline, STGCNTemporal
from backend.safety.event_policy import Evidence


def verify_artifact(path, checksum):
    if not path or not Path(path).is_file() or len(checksum) != 64:
        raise ValueError('Missing model file or SHA256; run the explicit model setup script')
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != checksum.lower():
        raise ValueError('Model checksum mismatch')


class Detector:
    qualified = False  # Real-world qualification is unmet. No environment flag bypasses this gate.

    def __init__(self, config):
        self.config = config
        self.pose = None
        self.temporal = TrajectoryBaseline()
        self.tracker = Tracker()
        self.history = deque(maxlen=120)
        self.reason = 'Pose weights not configured; camera preview and dry-run tests remain available'
        self.ready = False
        try:
            verify_artifact(config.SAFETY_POSE_PATH, config.SAFETY_POSE_SHA256)
            import mediapipe as mp
            self.mp = mp
            self.pose = mp.tasks.vision.PoseLandmarker.create_from_options(mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=config.SAFETY_POSE_PATH),
                running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=4,
                min_pose_detection_confidence=.6, min_pose_presence_confidence=.6))
            if config.SAFETY_TEMPORAL_MODEL == 'stgcn':
                verify_artifact(config.SAFETY_STGCN_PATH, config.SAFETY_STGCN_SHA256)
                self.temporal = STGCNTemporal(config.SAFETY_STGCN_CONFIG, config.SAFETY_STGCN_PATH)
            elif config.SAFETY_TEMPORAL_MODEL != 'baseline':
                raise ValueError('Unsupported temporal model')
            self.ready = True
            self.reason = 'Experimental detector; automatic real calls unavailable pending evaluation'
        except Exception as exc:
            self.reason = f'Detector unavailable ({type(exc).__name__}); check local model setup'
            if self.pose:
                self.pose.close()
                self.pose = None

    def reset(self):
        self.history.clear()
        self.tracker.reset()

    def close(self):
        if self.pose:
            self.pose.close()
            self.pose = None

    def process(self, t, frame):
        if not self.ready:
            return Evidence(False, reasons=(self.reason,)), []
        result = self.pose.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        poses = [np.array([[lm.x, lm.y, min(lm.visibility, lm.presence)] for lm in person], dtype=np.float32)[COCO_FROM_MP] for person in result.pose_landmarks]
        for points in poses:
            outside = np.any((points[:, :2] < 0) | (points[:, :2] > 1), axis=1)
            points[outside, 2] = 0  # Inferred off-screen limbs cannot satisfy visibility.
        tracks, changed = self.tracker.update(poses)
        overlays = [{'id': p['id'], 'box': p['box'], 'points': p['points'].tolist()} for p in tracks]
        if any(p['points'][UPPER_BODY, 2].min() < .55 for p in tracks):
            self.history.clear()
            return Evidence(False, people=len(tracks), reasons=('Keep both shoulders, elbows and wrists visible; move farther from the camera',)), overlays
        if changed or (self.history and (t - self.history[-1][0] > 1 or t <= self.history[-1][0])):
            self.history.clear()
        self.history.append((t, tracks))
        while self.history and t - self.history[0][0] > self.temporal.window_seconds:
            self.history.popleft()
        evidence = self.temporal.classify(list(self.history), frame.shape)
        return evidence, overlays
