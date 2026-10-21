"""Interchangeable temporal classifiers. No expression model is imported here."""
import numpy as np
from backend.safety.event_policy import Evidence

# The upstream text file uses one-based line numbers: A50/A51 -> indices 49/50.
STRIKING_CLASSES = {49: 'punching/slapping other person', 50: 'kicking other person'}


class TrajectoryBaseline:
    version = 'directed-wrist-trajectory-v1 (experimental)'
    window_seconds = 1.2

    def classify(self, history, shape):
        if len(history) < 8 or history[-1][0] - history[0][0] < .7:
            return Evidence(False, reasons=('Inadequate temporal history',))
        current = history[-1][1]
        if len(current) < 2:
            return Evidence(False, people=len(current), reasons=('Two visible participants required',))
        if any(p['points'][[5, 6, 7, 8, 9, 10, 11, 12], 2].min() < .55 for _, tracks in history for p in tracks):
            return Evidence(False, people=len(current), reasons=('Temporal window contains occluded limbs',))
        # Inspect a short trailing trajectory, after a longer stable observation window.
        old = min(history, key=lambda h: abs(h[0] - (history[-1][0] - .35)))
        dt = history[-1][0] - old[0]
        if dt < .15:
            return Evidence(False, reasons=('Insufficient motion sampling',))
        score = 0.
        pair = ()
        for source in current:
            previous = next((p for p in old[1] if p['id'] == source['id']), None)
            if previous is None:
                return Evidence(False, reasons=('Track identity changed',))
            p, prev = source['points'], previous['points']
            for target in current:
                if target['id'] == source['id']:
                    continue
                q = target['points']
                if min(p[[5, 6, 7, 8, 9, 10], 2].min(), q[[5, 6, 11, 12], 2].min()) < .55:
                    return Evidence(False, people=len(current), reasons=('Relevant limbs occluded',))
                center = np.mean(q[[5, 6, 11, 12], :2], axis=0)
                scale = max(float(np.linalg.norm(p[5, :2] - p[6, :2])), .06)
                for wrist, elbow, shoulder in [(9, 7, 5), (10, 8, 6)]:
                    v = (p[wrist, :2] - p[shoulder, :2]) - (prev[wrist, :2] - prev[shoulder, :2])
                    toward = center - prev[wrist, :2]
                    alignment = float(np.dot(v, toward) / max(np.linalg.norm(v) * np.linalg.norm(toward), 1e-6))
                    speed = float(np.linalg.norm(v)) / (scale * dt)
                    extension = float(np.linalg.norm(p[wrist, :2] - p[shoulder, :2])) / scale
                    proximity = float(np.linalg.norm(p[wrist, :2] - center)) / scale
                    if alignment > .8 and speed > 2 and extension > .9 and proximity < 2.5:
                        candidate_score = min(.99, .75 + (speed - 2) * .05)
                        if candidate_score > score:
                            score, pair = candidate_score, (source['id'], target['id'])
        return Evidence(True, score, score >= .75, len(current), ('Experimental trajectory baseline; review footage',), pair)


class STGCNTemporal:
    """Official MMAction2 COCO-17 NTU60 pipeline. Optional isolated model environment."""
    version = 'mmaction2-stgcn-ntu60-coco17-experimental-v3'
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
