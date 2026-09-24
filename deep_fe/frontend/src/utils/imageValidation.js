export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_IMAGE_DIMENSION = 4096;

const SUPPORTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export async function validateImageFile(file) {
  if (!SUPPORTED_TYPES.has(file.type)) {
    throw new Error("Supported formats: JPG, PNG, and WebP.");
  }
  if (!file.size) {
    throw new Error("The image file is empty.");
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new Error("Image must be 5 MiB or smaller.");
  }

  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("Unable to decode image. Use a valid JPG, PNG, or WebP file.");
  }

  try {
    if (
      !bitmap.width ||
      !bitmap.height ||
      bitmap.width > MAX_IMAGE_DIMENSION ||
      bitmap.height > MAX_IMAGE_DIMENSION
    ) {
      throw new Error("Image dimensions must be at most 4096 × 4096 pixels.");
    }
  } finally {
    bitmap.close();
  }
}
