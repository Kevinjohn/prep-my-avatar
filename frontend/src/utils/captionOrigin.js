export const CAPTION_ORIGINS = [
  {
    key: 'asserted',
    chip: 'You',
    short: 'You wrote this',
    title: 'You wrote or corrected this caption. An ordinary Re-caption run keeps it.',
  },
  {
    key: 'joycaption',
    chip: 'JoyCaption',
    short: 'Written by JoyCaption',
    title: 'Written by JoyCaption, running locally through the configured ai-toolkit folder.',
  },
  {
    key: 'ollama',
    chip: 'Local vision',
    short: 'Written by the local vision model',
    title: 'Written by the configured local vision model.',
  },
  {
    key: 'openai', chip: 'OpenAI', short: 'Written by OpenAI',
    title: 'Written by the configured OpenAI API model.',
  },
  {
    key: 'gemini', chip: 'Gemini', short: 'Written by Google Gemini',
    title: 'Written by the configured Google Gemini API model.',
  },
  {
    key: 'chatgpt', chip: 'ChatGPT', short: 'Written by ChatGPT',
    title: 'Written through the connected ChatGPT subscription.',
  },
];

export const CAPTION_ORIGIN_UNRECORDED = {
  key: '',
  chip: 'Author not recorded',
  short: 'Author not recorded',
  title: 'This caption predates recorded authorship. It may be human or model text; the app does not guess.',
  known: false,
};

export function captionOriginInfo(origin) {
  const key = typeof origin === 'string' ? origin.trim().toLowerCase() : '';
  if (!key) return CAPTION_ORIGIN_UNRECORDED;
  const known = CAPTION_ORIGINS.find((entry) => entry.key === key);
  if (known) return { ...known, known: true };
  return {
    key,
    chip: key,
    short: `Written by ${key}`,
    title: `Written by ${key}, an origin this version of the app does not know. It is shown rather than hidden.`,
    known: true,
  };
}

export function captionIsAsserted(origin) {
  return captionOriginInfo(origin).key === 'asserted';
}

export function captionOriginTooltipLine(caption, origin) {
  if (!String(caption || '').trim()) return '';
  return captionOriginInfo(origin).short;
}

export function captionAttributionState(savedCaption, origin, draft = savedCaption) {
  const saved = String(savedCaption || '');
  const current = String(draft || '');
  if (current !== saved) {
    return {
      kind: 'draft',
      key: 'unsaved',
      chip: 'Unsaved edit',
      short: 'Unsaved edit',
      title: 'Save this edit to record it as your caption.',
      known: true,
    };
  }
  if (!saved.trim()) return null;
  return { kind: 'saved', ...captionOriginInfo(origin) };
}

export function captionRewriteCounts(images) {
  const counts = {
    blank: 0,
    machine: 0,
    asserted: 0,
    unrecorded: 0,
    unknown: 0,
  };
  for (const image of Array.isArray(images) ? images : []) {
    if (image?.status !== 'keep') continue;
    if (!String(image.caption || '').trim()) {
      counts.blank += 1;
      continue;
    }
    const origin = captionOriginInfo(image.caption_origin);
    if (origin.key === 'asserted') counts.asserted += 1;
    else if (['joycaption', 'ollama', 'openai', 'gemini', 'chatgpt'].includes(origin.key)) counts.machine += 1;
    else if (!origin.key) counts.unrecorded += 1;
    else counts.unknown += 1;
  }
  const rewrite = counts.blank + counts.machine + counts.unrecorded + counts.unknown;
  return {
    ...counts,
    rewrite,
    spared: counts.asserted,
    rewriteWithAsserted: rewrite + counts.asserted,
  };
}
