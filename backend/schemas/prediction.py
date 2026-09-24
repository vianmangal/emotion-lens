from typing import Dict

from pydantic import BaseModel


class PredictionResponse(BaseModel):
    emotion: str
    confidence: float
    all_scores: Dict[str, float]
    face_detected: bool
    face_box: Dict[str, int]
    face_count: int
    image_width: int
    image_height: int
    model_version: str
