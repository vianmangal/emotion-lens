from io import BytesIO

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 16_777_216
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_image_bytes(image_bytes: bytes) -> None:
    """Check the actual image format and header dimensions before decoding pixels."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format not in SUPPORTED_IMAGE_FORMATS:
                raise ValueError("Supported formats: JPG, PNG, and WebP.")

            width, height = image.size
            if (
                width <= 0
                or height <= 0
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ValueError("Image dimensions must be at most 4096 × 4096 pixels.")

            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Unable to decode image. Use a valid JPG, PNG, or WebP file.") from exc
