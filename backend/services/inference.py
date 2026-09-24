import cv2
import numpy as np

from backend.models import cnn_model
from backend.services.face_detect import detect_largest_face


def preprocess_image_bytes(image_bytes: bytes):
    image_array = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unable to decode image.")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    face, face_box, face_count = detect_largest_face(gray)
    if face is None:
        raise ValueError("No face found. Try a clearer, front-facing photo.")

    resized = cv2.resize(face, (48, 48))
    normalized = resized.astype("float32") / 255.0
    input_tensor = normalized.reshape(1, 48, 48, 1)
    x, y, width, height = face_box
    return input_tensor, {
        "face_box": {"x": x, "y": y, "width": width, "height": height},
        "face_count": face_count,
        "image_width": int(gray.shape[1]),
        "image_height": int(gray.shape[0]),
    }


def run_inference(image_bytes: bytes):
    input_tensor, face_details = preprocess_image_bytes(image_bytes)
    model = cnn_model.get_model()
    probabilities = model.predict(input_tensor, verbose=0)[0]

    labels = cnn_model.get_labels()
    scores = {label: float(probabilities[idx]) for idx, label in enumerate(labels)}
    pred_idx = int(np.argmax(probabilities))

    return {
        "emotion": labels[pred_idx],
        "confidence": float(probabilities[pred_idx]),
        "all_scores": scores,
        "face_detected": True,
        **face_details,
        "model_version": cnn_model.get_model_version(),
    }
