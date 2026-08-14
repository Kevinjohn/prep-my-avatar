// The one place that knows how a dataset image is addressed. Seventeen surfaces
// built this URL by hand, which meant seventeen chances to forget the encoding on
// a filename with a space or a '#' in it.
//
// `nonce` busts the browser cache after an edit that rewrites the file in place
// (crop, watermark clean) and so keeps the same filename; surfaces that only ever
// show images they did not just edit pass none, and get a cacheable URL.
//
// Takes an image row or a bare filename, because callers hold both, and returns
// null when there is no filename — a row can exist before its file does (a
// generation still running), and callers already render a placeholder for that.
export function datasetImageUrl(datasetId, imageOrFilename, nonce = 0) {
  const filename = typeof imageOrFilename === 'string' ? imageOrFilename : imageOrFilename?.filename;
  if (!filename) return null;
  return `/api/dataset/${datasetId}/img/${encodeURIComponent(filename)}${nonce ? `?v=${nonce}` : ''}`;
}
