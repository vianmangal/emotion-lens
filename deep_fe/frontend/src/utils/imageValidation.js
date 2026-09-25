export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_IMAGE_DIMENSION = 4096;

const SUPPORTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]);

export const isHeicFile = (file) =>
  ["image/heic", "image/heif"].includes(file.type) ||
  (!file.type && /\.(heic|heif)$/i.test(file.name));

export async function validateImageFile(file) {
  if (!SUPPORTED_TYPES.has(file.type) && !isHeicFile(file)) {
    throw new Error("Supported formats: JPG, PNG, WebP, and HEIC.");
  }
  if (!file.size) {
    throw new Error("The image file is empty.");
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new Error("Image must be 5 MiB or smaller.");
  }

  // Browser image decoders do not consistently support HEIC; the API validates
  // its contents and dimensions before converting it for inference.
  if (isHeicFile(file)) return;

  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("Unable to decode image. Use a valid JPG, PNG, WebP, or HEIC file.");
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
