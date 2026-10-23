"""Interchangeable temporal classifiers. No expression model is imported here."""
import numpy as np
from backend.safety.event_policy import Evidence

# The upstream text file uses one-based line numbers: A50/A51 -> indices 49/50.
STRIKING_CLASSES = {49: 'punching/slapping other person', 50: 'kicking other person'}


class TrajectoryBaseline:
    version = 'directed-wrist-trajectory-v3-arm-windows (experimental)'
    window_seconds = 1.2
    motion_memory_seconds = .45

    @staticmethod
    def observed(history, track_id, joints):
        """Contiguous visible suffix; a missing joint resets only this arm."""
        samples = []
        for t, tracks in reversed(history):
            track = next((p for p in tracks if p['id'] == track_id), None)
            if track is None or np.any(track['points'][joints, 2] < .55):
                break
            samples.append((t, track['points']))
        return list(reversed(samples))

    def classify(self, history, shape):
        if len(history) < 8 or history[-1][0] - history[0][0] < .7:
            return Evidence(False, reasons=('Inadequate temporal history',))
        current = history[-1][1]
        if len(current) < 2:
            return Evidence(False, people=len(current), reasons=('Two visible participants required',))
        now = history[-1][0]
        # Each arm has its own visibility window. A target's hidden wrist must
        # not erase an observed strike from the other person's visible arm.
        score = 0.
        pair = ()
        observable = False
        pixels = np.array([shape[1], shape[0]], dtype=np.float32)
        for source in current:
            for target in current:
                if target['id'] == source['id']:
                    continue
                for wrist, elbow, shoulder in [(9, 7, 5), (10, 8, 6)]:
                    arm = self.observed(history, source['id'], [5, 6, elbow, wrist])
                    body = self.observed(history, target['id'], [5, 6])
                    if not arm or not body:
                        continue
                    since = max(arm[0][0], body[0][0])
                    arm = [sample for sample in arm if sample[0] >= since]
                    body = [sample for sample in body if sample[0] >= since]
                    # Require half a second of observed landmarks after this
                    # arm recovers; an inferred wrist jump cannot be a strike.
                    if len(arm) < 5 or now - since < .5 - 1e-6:
                        continue
                    observable = True
                    # Three fresh observations are needed for a trajectory.
                    # Never bridge an occluded moving arm or infer its motion.
                    for start in range(len(arm) - 2):
                        if now - arm[start][0] > .9:
                            continue
                        t0, prev = arm[start]
                        for end in range(start + 2, len(arm)):
                            te, p = arm[end]
                            dt = te - t0
                            if dt < .15 or dt > .45 or now - te > self.motion_memory_seconds:
                                continue
                            q = body[end][1]
                            center = np.mean(q[[5, 6], :2], axis=0) * pixels
                            scale = max(float(np.linalg.norm((p[5, :2] - p[6, :2]) * pixels)), .06 * shape[1])
                            # Remove source body translation; walking toward a
                            # stationary hand is not an arm strike.
                            v = ((p[wrist, :2] - p[shoulder, :2]) -
                                 (prev[wrist, :2] - prev[shoulder, :2])) * pixels
                            toward = center - prev[wrist, :2] * pixels
                            alignment = float(np.dot(v, toward) / max(np.linalg.norm(v) * np.linalg.norm(toward), 1e-6))
                            speed = float(np.linalg.norm(v)) / (scale * dt)
                            extension = float(np.linalg.norm((p[wrist, :2] - p[shoulder, :2]) * pixels)) / scale
                            proximity = float(np.linalg.norm(p[wrist, :2] * pixels - center)) / scale
                            approach = (float(np.linalg.norm(toward)) -
                                        float(np.linalg.norm(p[wrist, :2] * pixels - center))) / scale
                            if alignment > .8 and speed > 2 and extension > .9 and proximity < 2.5 and approach > .25:
                                # Retaining a recent trajectory must not turn a
                                # single bad landmark into a sustained alert.
                                # Require progress in two separately observed
                                # intervals, not two still frames plus a jump.
                                direction = toward / max(np.linalg.norm(toward), 1e-6)
                                progress = 0
                                for k in range(start + 1, end + 1):
                                    before, after = arm[k - 1][1], arm[k][1]
                                    step = ((after[wrist, :2] - after[shoulder, :2]) -
                                            (before[wrist, :2] - before[shoulder, :2])) * pixels
                                    progress += int(float(np.dot(step, direction)) / scale > .06)
                                if progress < 2:
                                    continue
                                candidate_score = min(.99, .75 + (speed - 2) * .05)
                                if candidate_score > score:
                                    score, pair = candidate_score, (source['id'], target['id'])
        reason = ('Experimental trajectory baseline; review footage' if observable else
                  'Keep one moving arm fully visible, including elbow and wrist, and both people’s shoulders in frame')
        return Evidence(observable, score, score >= .75, len(current), (reason,), pair)


class STGCNTemporal:
    """Official MMAction2 COCO-17 NTU60 pipeline. Optional isolated model environment."""
    version = 'mmaction2-stgcn-ntu60-coco17-experimental-v5-arm-windows'
    window_seconds = 3.3

    def __init__(self, config, checkpoint):
        from mmaction.apis import init_recognizer, inference_recognizer
        self.model = init_recognizer(config, checkpoint, device='cpu')
        self.infer = inference_recognizer

    def classify(self, history, shape):
        if len(history) < 24 or history[-1][0] - history[0][0] < 3:
            return Evidence(False, reasons=('STGCN requires 3 seconds of stable poses',))
        candidate = TrajectoryBaseline().classify(history, shape)
        # Temporal classification and the directed-motion gate must describe the
        # same pair, even when bystanders have older/lower track IDs.
        ids = list(candidate.track_ids) if candidate.directed else [t['id'] for t in history[-1][1]][:2]
        if len(ids) < 2:
            return Evidence(False, people=len(ids), reasons=('Two visible participants required',))
        h, w = shape[:2]
        points = np.zeros((2, len(history), 17, 2), dtype=np.float32)
        scores = np.zeros((2, len(history), 17), dtype=np.float32)
        for ti, (_, tracks) in enumerate(history):
            for pi, track_id in enumerate(ids):
                track = next((p for p in tracks if p['id'] == track_id), None)
                if track is None or track['points'][[5, 6, 7, 8, 9, 10], 2].min() < .55:
                    return Evidence(False, people=2, reasons=('Unstable or occluded tracks',))
                points[pi, ti] = track['points'][:, :2] * [w, h]
                scores[pi, ti] = track['points'][:, 2]
        result = self.infer(self.model, {'keypoint': points, 'keypoint_score': scores, 'total_frames': len(history), 'img_shape': (h, w), 'original_shape': (h, w), 'start_index': 0, 'label': -1, 'modality': 'Pose'})
        values = result.pred_score.detach().cpu().numpy()
        top = int(values.argmax())
        # Also require a directed trajectory; class rank alone cannot trigger an event.
        directed = candidate.directed
        label = STRIKING_CLASSES.get(top, 'unsupported action')
        return Evidence(True, float(values[top]) if top in STRIKING_CLASSES else 0., directed, 2,
                        (f'NTU60 class index {top} ({label}); experimental model score',), tuple(ids) if directed else ())
