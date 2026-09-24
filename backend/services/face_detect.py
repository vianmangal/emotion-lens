import os

import cv2
import numpy as np

_cascade = None


def _get_cascade() -> cv2.CascadeClassifier:
    global _cascade
    if _cascade is None:
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            raise FileNotFoundError(f"Failed to load Haar cascade at: {cascade_path}")
        _cascade = cascade
    return _cascade


def detect_largest_face(
    gray: np.ndarray,
    scale_factor: float = 1.1,
    min_neighbors: int = 5,
    min_size: int = 48,
) -> tuple[np.ndarray | None, tuple[int, int, int, int] | None, int]:
    cascade = _get_cascade()
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=(min_size, min_size),
    )
    if len(faces) == 0:
        return None, None, 0

    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    face = gray[y : y + h, x : x + w]
    return face, (int(x), int(y), int(w), int(h)), len(faces)
