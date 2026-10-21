from pathlib import Path
import threading


from backend.config import settings

_model = None
_lock = threading.Lock()
_labels = ["angry", "fear", "happy", "neutral", "sad"]


def load_model_once():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                if not settings.MODEL_PATH or not Path(settings.MODEL_PATH).is_file():
                    raise RuntimeError('Expression model unavailable. Configure local MODEL_PATH.')
                try:
                    from tensorflow.keras.models import load_model
                    _model = load_model(settings.MODEL_PATH)
                except Exception as exc:
                    raise RuntimeError('Expression model unavailable. Check weights and optional TensorFlow installation.') from exc
    return _model


def get_model():
    if _model is None:
        return load_model_once()
    return _model


def get_labels():
    return list(_labels)


def get_model_version() -> str:
    return Path(settings.MODEL_PATH).name


def model_loaded() -> bool:
    return _model is not None
