export function watermarkScanNotice(result) {
  if (!Number(result?.checked)) {
    return {
      severity: 'warning',
      message: 'No photos were checked for watermarks. Local vision returned no usable results, so this is not a clean scan. In Setup, verify the loaded model supports images, then retry.',
    }
  }
  return {
    severity: 'success',
    message: `${result.detected || 0} watermark(s) found · ${result.none || 0} clean (of ${result.checked})`,
  }
}
