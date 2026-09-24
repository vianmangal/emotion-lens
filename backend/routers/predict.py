from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.db_models import Prediction
from backend.schemas.prediction import PredictionResponse
from backend.services.image_validation import MAX_IMAGE_BYTES, validate_image_bytes
from backend.services.inference import run_inference

router = APIRouter(prefix="/predict", tags=["predict"])


@router.post("", response_model=PredictionResponse)
async def predict_emotion(
    image: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
):
    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty image payload.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image must be 5 MiB or smaller.")

    try:
        validate_image_bytes(image_bytes)
        result = run_inference(image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    record = Prediction(
        image_filename=image.filename or "upload.jpg",
        emotion=result["emotion"],
        confidence=result["confidence"],
        all_scores=result["all_scores"],
    )
    session.add(record)
    await session.commit()

    return result
