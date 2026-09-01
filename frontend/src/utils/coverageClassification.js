export function coverageClassificationNotice(classified) {
  if (!Number(classified)) {
    return {
      severity: 'warning',
      message: 'No photo details were added. Local vision is connected but returned no usable classifications. In Setup, make sure the loaded model supports images, then retry — or describe each photo manually here.',
    }
  }
  return {
    severity: 'success',
    message: `${classified} image(s) mapped for coverage`,
  }
}
