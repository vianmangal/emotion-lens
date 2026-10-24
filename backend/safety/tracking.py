from itertools import product
import numpy as np

# COCO 17 ordering from MediaPipe 33 landmarks, normalized image coordinates.
COCO_FROM_MP = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
UPPER_BODY = [5, 6, 7, 8, 9, 10]  # Shoulders, elbows and wrists; hips may be below the webcam.


def tracking_center(points):
    # Hidden hips are inferred and can jump outside the frame. They must not
    # move an otherwise stationary upper-body track or change its identity.
    shoulders = points[[5, 6]]
    visible = shoulders[:, 2] >= .55
    if visible.any():
        return np.mean(shoulders[visible, :2], axis=0)
    visible = points[:, 2] > .5
    return np.mean(points[visible, :2], axis=0) if visible.any() else np.mean(points[[5, 6], :2], axis=0)


class Tracker:
    """Global session-local assignment; ambiguous matches receive new identities."""
    def __init__(self):
        self.previous = {}
        self.next_id = 1

    def reset(self):
        self.previous.clear()

    def update(self, poses):
        centers = [tracking_center(points) for points in poses]
        ids = list(self.previous)
        # MediaPipe returns at most four poses, in no guaranteed order. Match
        # all observations together so a distant first pose cannot steal the
        # identity belonging to a later, much closer observation.
        distances = {(i, k): float(np.linalg.norm(center - self.previous[k]))
                     for i, center in enumerate(centers) for k in ids}
        choices = [[None] + [k for k in ids if distances[i, k] < .25]
                   for i in range(len(centers))]
        assignments = []
        for assignment in product(*choices):
            matched = [k for k in assignment if k is not None]
            if len(matched) != len(set(matched)):
                continue
            cost = sum(distances[i, k] for i, k in enumerate(assignment) if k is not None)
            assignments.append((len(matched), cost, assignment))
        assignments.sort(key=lambda item: (-item[0], item[1]))
        count, cost, best = assignments[0]
        alternatives = [a for n, c, a in assignments[1:] if n == count and c - cost < .06]
        remaining = set(ids)
        tracks, discontinuity = [], False
        for i, points in enumerate(poses):
            track_id = best[i]
            ambiguous = any(a[i] != track_id for a in alternatives)
            if track_id is not None and not ambiguous:
                remaining.remove(track_id)
            else:
                track_id = self.next_id
                self.next_id += 1
                discontinuity = True
            visible = points[:, 2] > .5
            coords = points[visible, :2]
            box = [*coords.min(axis=0).tolist(), *coords.max(axis=0).tolist()] if len(coords) else [0, 0, 0, 0]
            tracks.append({'id': track_id, 'points': points, 'box': box})
        discontinuity |= bool(remaining)
        self.previous = {x['id']: tracking_center(x['points']) for x in tracks}
        return sorted(tracks, key=lambda x: x['id']), discontinuity
