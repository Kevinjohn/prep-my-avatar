export const CROP_MIN_SIDE = 32;

export function clampCropBox(box, width, height) {
  const w = Math.min(Math.max(box.w, CROP_MIN_SIDE), width);
  const h = Math.min(Math.max(box.h, CROP_MIN_SIDE), height);
  return {
    x: Math.min(Math.max(box.x, 0), width - w),
    y: Math.min(Math.max(box.y, 0), height - h),
    w,
    h,
  };
}

export function clampRatioCropBox(box, ratio, width, height) {
  const maxWidth = Math.min(width, height * ratio);
  const requiredWidth = Math.max(CROP_MIN_SIDE, CROP_MIN_SIDE * ratio);
  // If the source itself is too small to satisfy the minimum on both axes,
  // preserve the ratio and use the largest box that fits.
  const minWidth = Math.min(requiredWidth, maxWidth);
  const w = Math.min(Math.max(box.w, minWidth), maxWidth);
  const h = w / ratio;
  return {
    x: Math.min(Math.max(box.x, 0), width - w),
    y: Math.min(Math.max(box.y, 0), height - h),
    w,
    h,
  };
}
