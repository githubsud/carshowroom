/**
 * Client-side photo compression before upload (SPEC §4.3, ASSUMPTION A-11):
 * WebP, longest edge 1600 px, about 80% quality. Phone photos of 4-8 MB
 * become a few hundred kB, which matters on mobile data at the lot.
 */
export const MAX_EDGE = 1600;
export const QUALITY = 0.8;

/** Scale (width, height) so the longest edge is at most maxEdge; never enlarge. */
export function fitWithin(width: number, height: number, maxEdge = MAX_EDGE): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= maxEdge) {
    return { width, height };
  }
  const scale = maxEdge / longest;
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

export async function compressImage(file: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const { width, height } = fitWithin(bitmap.width, bitmap.height);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) {
    bitmap.close();
    return file;
  }
  context.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  const webp = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', QUALITY));
  // Browsers without WebP encoding fall back to JPEG.
  if (webp && webp.type === 'image/webp') {
    return webp;
  }
  const jpeg = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', QUALITY));
  return jpeg ?? file;
}
