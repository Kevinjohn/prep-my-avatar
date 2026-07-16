export function isCleanAdmissionCandidate(image, identityFloor = 0.50, duplicateRoots = new Set()) {
  return image?.status === 'pending'
    && image.training_usefulness === 'green'
    && image.analysis?.face?.quality === 'green'
    && image.face_state === 'scorable'
    && image.face_score != null
    && image.face_score >= identityFloor
    && !['detected', 'failed'].includes(image.watermark_state)
    && !image.duplicate_of_id
    && !duplicateRoots.has(image.id);
}

export function needsQualityReview(image) {
  return image?.training_usefulness !== 'green'
    || image?.analysis?.face?.quality !== 'green'
    || image?.face_state !== 'scorable'
    || image?.face_score == null;
}
