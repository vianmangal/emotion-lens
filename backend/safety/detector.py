from collections import deque
import hashlib
from pathlib import Path
import numpy as np
import cv2
from backend.safety.tracking import Tracker, COCO_FROM_MP
from backend.safety.temporal_model import TrajectoryBaseline, STGCNTemporal
from backend.safety.event_policy import Evidence
from backend.safety.video_model import VideoAction, S3DEncoder, StrikeHead, PERSON_SCORE_THRESHOLD


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
        self.body = None
        self.temporal = TrajectoryBaseline()
        self.tracker = Tracker()
        self.history = deque(maxlen=120)
        self.reason = 'Pose weights not configured; camera preview and dry-run tests remain available'
        self.ready = False
        try:
            import mediapipe as mp
            self.mp = mp
            if config.SAFETY_TEMPORAL_MODEL == 'visual':
                verify_artifact(config.SAFETY_PERSON_PATH, config.SAFETY_PERSON_SHA256)
                self.body = mp.tasks.vision.ObjectDetector.create_from_options(mp.tasks.vision.ObjectDetectorOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=config.SAFETY_PERSON_PATH),
                    running_mode=mp.tasks.vision.RunningMode.IMAGE, max_results=4,
                    score_threshold=PERSON_SCORE_THRESHOLD, category_allowlist=['person']))
                verify_artifact(config.SAFETY_VISUAL_WEIGHTS_PATH, config.SAFETY_VISUAL_WEIGHTS_SHA256)
                verify_artifact(config.SAFETY_VISUAL_HEAD_PATH, config.SAFETY_VISUAL_HEAD_SHA256)
                head = StrikeHead(config.SAFETY_VISUAL_HEAD_PATH)
                self.temporal = VideoAction(S3DEncoder(config.SAFETY_VISUAL_WEIGHTS_PATH,
                                                      optimize_cpu=config.SAFETY_VISUAL_OPTIMIZE_CPU), head,
                                            synchronous=config.SAFETY_VISUAL_SYNCHRONOUS)
                self.temporal.version = (f'learned-video-s3d-strike-v2-{config.SAFETY_VISUAL_HEAD_SHA256[:8]}-'
                                         f'{config.SAFETY_PERSON_SHA256[:8]} (experimental)')
            else:
                verify_artifact(config.SAFETY_POSE_PATH, config.SAFETY_POSE_SHA256)
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
            if self.body:
                self.body.close()
                self.body = None

    def reset(self):
        self.history.clear()
        self.tracker.reset()
        if isinstance(self.temporal, VideoAction):
            self.temporal.reset()

    def close(self):
        if isinstance(self.temporal, VideoAction):
            self.temporal.close()
        if self.pose:
            self.pose.close()
            self.pose = None
        if getattr(self, 'body', None):
            self.body.close()
            self.body = None

    def process(self, t, frame):
        if not self.ready:
            return Evidence(False, reasons=(self.reason,)), []
        if getattr(self, 'body', None):
            h, w = frame.shape[:2]
            detections = self.body.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                                                       data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
            boxes, scores = [], []
            for detection in detections.detections:
                category = next((c for c in detection.categories if c.category_name == 'person' and c.score >= PERSON_SCORE_THRESHOLD), None)
                if category is None:
                    continue
                b = detection.bounding_box
                box = np.clip([b.origin_x / w, b.origin_y / h,
                               (b.origin_x + b.width) / w, (b.origin_y + b.height) / h], 0, 1).tolist()
                # Tiny distant/background proposals cannot establish one of the
                # two demo participants. Keep all qualifying foreground boxes;
                # a third person makes action inference abstain.
                if box[2] > box[0] and box[3] > box[1] and (box[2] - box[0]) * (box[3] - box[1]) >= .01:
                    boxes.append(box)
                    scores.append(category.score)
            # Box observations are real person detections. No artificial joint
            # confidence or inferred skeleton is exposed to the live overlay.
            tracks, _ = self.tracker.update([np.zeros((17, 3), np.float32) for _ in boxes], boxes, scores)
            overlays = [{'id': p['id'], 'box': p['box'], 'points': [], 'person_score': p['person_score']} for p in tracks]
            return self.temporal.process_frame(t, frame, tracks), overlays
        result = self.pose.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        poses = [np.array([[lm.x, lm.y, min(lm.visibility, lm.presence)] for lm in person], dtype=np.float32)[COCO_FROM_MP] for person in result.pose_landmarks]
        for points in poses:
            outside = np.any((points[:, :2] < 0) | (points[:, :2] > 1), axis=1)
            points[outside, 2] = 0  # Inferred off-screen limbs cannot satisfy visibility.
        tracks, _ = self.tracker.update(poses)
        overlays = [{'id': p['id'], 'box': p['box'], 'points': p['points'].tolist()} for p in tracks]
        if isinstance(self.temporal, VideoAction):
            return self.temporal.process_frame(t, frame, tracks), overlays
        # Each classifier checks a participant's own contiguous observations.
        # New/missing/occluded tracks must not erase another visible pair's
        # history; new identities cannot reuse the old person's observations.
        if self.history and (t - self.history[-1][0] > 1 or t <= self.history[-1][0]):
            self.history.clear()
        self.history.append((t, tracks))
        while self.history and t - self.history[0][0] > self.temporal.window_seconds:
            self.history.popleft()
        evidence = self.temporal.classify(list(self.history), frame.shape)
        return evidence, overlays
