export function isCaptionSaveShortcut(event) {
  return event?.key === 'Enter' && Boolean(event.ctrlKey || event.metaKey);
}

export function captionCharacterLabel(caption) {
  const value = String(caption || '').normalize('NFC');
  // Intl.Segmenter counts user-perceived graphemes (flags, emoji ZWJ sequences,
  // and combining characters). Older runtimes fall back to Unicode code points.
  const count = typeof Intl?.Segmenter === 'function'
    ? [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(value)].length
    : Array.from(value).length;
  return `${count} character${count === 1 ? '' : 's'}`;
}
