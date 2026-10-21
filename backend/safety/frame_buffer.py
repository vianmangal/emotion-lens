from collections import deque
import base64
from io import BytesIO
import cv2
import numpy as np
from PIL import Image

MAX_MESSAGE = 1024 * 1024
MAX_JPEG = 512 * 1024


def decode_frame(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_JPEG:
            raise ValueError('Compressed frame exceeds 512 KiB')
        with Image.open(BytesIO(raw)) as header:
            if header.format != 'JPEG' or not (1 <= header.width <= 640 and 1 <= header.height <= 480):
                raise ValueError('Expected JPEG at most 640 × 480')
            header.verify()
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('Malformed JPEG')
        return raw, frame
    except Exception as exc:
        raise ValueError('Invalid frame: expected JPEG at most 640 × 480 and 512 KiB') from exc


class FrameBuffer:
    def __init__(self, seconds=5, capacity=60):
        self.frames = deque(maxlen=capacity)
        self.seconds = seconds

    def append(self, t, raw):
        self.frames.append((t, raw))
        while self.frames and (t - self.frames[0][0] > self.seconds or sum(len(raw) for _, raw in self.frames) > 12 * 1024 * 1024):
            self.frames.popleft()

    def clear(self):
        self.frames.clear()
