import numpy as np

# COCO 17 ordering from MediaPipe 33 landmarks, normalized image coordinates.
COCO_FROM_MP = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]


class Tracker:
    """Conservative session-local centroid assignment; ambiguous matches reset history."""
    def __init__(self):
        self.previous = {}
        self.next_id = 1

    def reset(self):
        self.previous.clear()

    def update(self, poses):
        remaining = set(self.previous)
        tracks, discontinuity = [], False
        for points in poses:
            center = np.mean(points[[5, 6, 11, 12], :2], axis=0)
            matches = sorted((float(np.linalg.norm(center - self.previous[k])), k) for k in remaining)
            ambiguous = len(matches) > 1 and matches[1][0] - matches[0][0] < .06
            if matches and matches[0][0] < .25 and not ambiguous:
                track_id = matches[0][1]
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
        self.previous = {x['id']: np.mean(x['points'][[5, 6, 11, 12], :2], axis=0) for x in tracks}
        return sorted(tracks, key=lambda x: x['id']), discontinuity
