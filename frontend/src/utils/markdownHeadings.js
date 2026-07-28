function headingSlug(text) {
  const slug = String(text || '')
    .replace(/[`*_]/g, '')
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, '-')
    .replace(/^-|-$/g, '');
  return slug || 'section';
}

/** Return stable, non-empty and document-unique identifiers in source order. */
export function markdownHeadingIds(headings) {
  const counts = new Map();
  return headings.map((heading) => {
    const base = headingSlug(heading);
    const occurrence = (counts.get(base) || 0) + 1;
    counts.set(base, occurrence);
    return occurrence === 1 ? base : `${base}-${occurrence}`;
  });
}

export function markdownHeadingModel(source) {
  const titles = [...String(source || '').matchAll(/^##\s+(.+)$/gm)]
    .map((match) => match[1]);
  const ids = markdownHeadingIds(titles);
  return titles.map((title, index) => ({
    title: title.replace(/[`*_]/g, ''),
    id: ids[index],
  }));
}
