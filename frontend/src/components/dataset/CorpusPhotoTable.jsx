import { technicalAnalysisState } from '../../utils/technicalAnalysis.js';
import { datasetImageUrl } from './datasetImageUrl';

const TRAINING_STATUS = {
  keep: {
    label: 'Accepted',
    className: 'text-emerald-200',
    dotClassName: 'bg-emerald-400',
  },
  reject: {
    label: 'Rejected',
    className: 'text-rose-200',
    dotClassName: 'bg-rose-400',
  },
  pending: {
    label: 'Needs decision',
    className: 'text-amber-200',
    dotClassName: 'bg-amber-400',
  },
};

const QUALITY_TONE = {
  green: ['text-emerald-200', 'bg-emerald-400'],
  amber: ['text-amber-200', 'bg-amber-400'],
  red: ['text-rose-200', 'bg-rose-400'],
};

function StatusText({ children, className = 'text-content-muted', dotClassName = 'bg-content-subtle' }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-[0.625rem] font-semibold ${className}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dotClassName}`} />
      {children}
    </span>
  );
}

function generationDecision(image, selectedIds) {
  if (image.anchor_decision === 'pinned') return ['Always use', 'text-emerald-200'];
  if (image.anchor_decision === 'excluded') return ['Never send', 'text-rose-200'];
  if (selectedIds.has(image.id)) return ['Selected', 'text-indigo-200'];
  return ['Automatic', 'text-content-muted'];
}

export default function CorpusPhotoTable({
  datasetId,
  images,
  selectedId,
  selectedIds,
  duplicateRoots,
  anchorsVisible,
  onSelect,
}) {
  return (
    <table aria-label="Photos for review"
      className="block w-full min-w-0 text-left sm:table sm:table-fixed sm:border-separate sm:border-spacing-0">
        <colgroup className="hidden sm:table-column-group">
          <col className={anchorsVisible ? 'w-[38%]' : 'w-[46%]'} />
          <col className="w-[17%]" />
          <col className="w-[14%]" />
          <col className={anchorsVisible ? 'w-[17%]' : 'w-[23%]'} />
          {anchorsVisible && <col className="w-[14%]" />}
        </colgroup>
        <thead className="hidden bg-surface-overlay sm:sticky sm:top-0 sm:z-10 sm:table-header-group">
          <tr>
            <th scope="col" className="border-b border-border px-2 py-2 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Photo</th>
            <th scope="col" className="border-b border-border px-2 py-2 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Training</th>
            <th scope="col" className="border-b border-border px-2 py-2 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Framing</th>
            <th scope="col" className="border-b border-border px-2 py-2 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Technical quality</th>
            {anchorsVisible && (
              <th scope="col" className="border-b border-border px-2 py-2 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Generation use</th>
            )}
          </tr>
        </thead>
        <tbody className="block sm:table-row-group">
          {images.map((image) => {
            const active = selectedId === image.id;
            const name = image.source_name || `Imported image ${image.id}`;
            const training = TRAINING_STATUS[image.status] || TRAINING_STATUS.pending;
            const quality = image.training_usefulness || 'unknown';
            const [qualityTone, qualityDot] = QUALITY_TONE[quality] || [];
            const analysis = technicalAnalysisState(image.analysis);
            const duplicate = image.duplicate_of_id || duplicateRoots.has(image.id);
            const [generationLabel, generationTone] = generationDecision(image, selectedIds);
            return (
              <tr key={image.id} aria-selected={active}
                className={`grid grid-cols-3 border-b border-border sm:table-row sm:border-b-0 ${active
                  ? 'bg-indigo-500/10' : 'hover:bg-surface-raised'}`}>
                <td className="col-span-3 p-2 align-middle sm:table-cell sm:border-b sm:border-border">
                  <button type="button" onClick={() => onSelect(image.id)} aria-pressed={active}
                    aria-label={`Select ${name} for review`}
                    className="flex w-full min-w-0 items-center gap-2 rounded-md text-left">
                    <span className={`flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded-sm border sm:w-32 xl:h-32 xl:w-36 ${active
                      ? 'border-indigo-300 ring-2 ring-indigo-400/40'
                      : 'border-transparent'}`}>
                      <img loading="lazy" decoding="async" alt="" src={datasetImageUrl(datasetId, image)}
                        className="h-full w-full object-contain" />
                    </span>
                    <span className="min-w-0">
                      <span className="block max-w-24 truncate text-xs font-semibold text-content" title={name}>{name}</span>
                      {duplicate && <span className="mt-1 block text-[0.625rem] font-semibold text-amber-200">≈ Near-duplicate</span>}
                    </span>
                  </button>
                </td>
                <td className="px-2 py-2 align-middle sm:table-cell sm:border-b sm:border-border sm:py-3">
                  <span className="mb-1 block text-[0.5rem] font-semibold uppercase tracking-wide text-content-subtle sm:hidden">Training</span>
                  <StatusText className={training.className} dotClassName={training.dotClassName}>{training.label}</StatusText>
                </td>
                <td className="px-2 py-2 align-middle text-xs text-content sm:table-cell sm:border-b sm:border-border sm:py-3">
                  <span className="mb-1 block text-[0.5rem] font-semibold uppercase tracking-wide text-content-subtle sm:hidden">Framing</span>
                  {image.framing || 'Not set'}
                </td>
                <td className="px-2 py-2 align-middle sm:table-cell sm:border-b sm:border-border sm:py-3">
                  <span className="mb-1 block text-[0.5rem] font-semibold uppercase tracking-wide text-content-subtle sm:hidden">Quality</span>
                  <StatusText className={qualityTone} dotClassName={qualityDot}>{quality}</StatusText>
                  {analysis.key !== 'current' && (
                    <span className="mt-1 block text-[0.5625rem] text-content-subtle">{analysis.label} analysis</span>
                  )}
                </td>
                {anchorsVisible && (
                  <td className={`px-2 py-2 align-middle text-xs font-medium sm:table-cell sm:border-b sm:border-border sm:py-3 ${generationTone}`}>
                    <span className="mb-1 block text-[0.5rem] font-semibold uppercase tracking-wide text-content-subtle sm:hidden">Generation</span>
                    {generationLabel}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
    </table>
  );
}
