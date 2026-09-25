from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener(thumbnails=False)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 16_777_216
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}
SUPPORTED_FORMATS_MESSAGE = "Supported formats: JPG, PNG, WebP, and HEIC."
DECODE_ERROR_MESSAGE = "Unable to decode image. Use a valid JPG, PNG, WebP, or HEIC file."


def _check_dimensions(width: int, height: int) -> None:
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise ValueError("Image dimensions must be at most 4096 × 4096 pixels.")


def validate_image_bytes(image_bytes: bytes) -> bytes:
    """Validate file contents and return bytes OpenCV can decode for inference."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format not in SUPPORTED_IMAGE_FORMATS:
                raise ValueError(SUPPORTED_FORMATS_MESSAGE)
            _check_dimensions(*image.size)
            image.verify()

        with Image.open(BytesIO(image_bytes)) as image:
            if image.format == "HEIF":
                output = BytesIO()
                image.convert("RGB").save(output, format="PNG")
                return output.getvalue()
        return image_bytes
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(DECODE_ERROR_MESSAGE) from exc
