// react-frontend/src/components/dataset/studio/ResultsArea.jsx
/**
 * Zone « 📊 Résultats » du Studio de test LoRA. Possède l'état d'affichage
 * (repli `showResults`) et le run sélectionné (`selRun`), recalcule tout le
 * regroupement par run / config / variante à partir de `d.cells` et `d.scores`
 * (extraction behavior-preserving depuis l'ancien LoraTestStudio.jsx), puis rend
 * le sélecteur de run + une grille par variante (format × cfg × steps).
 */
import { useMemo, useState } from 'react';
import { fmt } from '../../../utils/studioFormat';
import RunSelector from './RunSelector';
import ResultsGrid from './ResultsGrid';
import { groupStudioRuns } from '../../../utils/studioState';

export default function ResultsArea({ datasetId, d, studio, vote, onOpen }) {
  // Repli des grilles de résultats (pour ne pas encombrer la page).
  const [showResults, setShowResults] = useState(true);
  // Run sélectionné (null = run le plus récent par défaut).
  // The hot status payload contains exactly one run. Older runs are selected
  // through the bounded, paginated history endpoint instead of being shipped
  // and regrouped on every poll.
  const runs = useMemo(() => groupStudioRuns(d?.cells), [d]);
  const activeRunKey = d?.selected_run_id || runs[0]?.key || null;
  const displayedCells = useMemo(() => {
    const r = runs.find((x) => x.key === activeRunKey);
    return r ? r.cells : [];
  }, [runs, activeRunKey]);

  // Dernière cellule par config dans le run affiché.
  // Clé d'une cellule = checkpoint|strength|format|cfg|steps|steps2 (steps2 = pass 2
  // SDXL ; vide pour Z-Image → clé inchangée).
  const ckey = (c) => `${c.checkpoint}|${c.strength}|${c.z_model || ''}|${c.aspect || ''}|${c.cfg ?? ''}|${c.steps ?? ''}|${c.steps2 ?? ''}`;
  // Batch : TOUTES les cellules par config (les N seeds), triées par seed → bande.
  const cellList = useMemo(() => {
    const m = new Map();
    for (const c of displayedCells) {
      const k = ckey(c);
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(c);
    }
    for (const arr of m.values()) arr.sort((a, b) => (a.seed || 0) - (b.seed || 0));
    return m;
  }, [displayedCells]);

  // Score cross-runs PAR CONFIG (modèle + cfg + steps inclus) — aligné backend.
  const scoreMap = useMemo(() => {
    const m = new Map();
    for (const s of d?.scores || []) {
      m.set(`${s.checkpoint}|${s.strength}|${s.aspect || ''}|${s.z_model || ''}|${s.cfg ?? ''}|${s.steps ?? ''}|${s.steps2 ?? ''}`, s);
    }
    return m;
  }, [d]);

  // Variantes présentes dans le run affiché (format × cfg × steps) → une grille par variante.
  const variantsInData = useMemo(() => {
    const m = new Map();
    for (const c of displayedCells) {
      const k = `${c.z_model || ''}|${c.aspect || ''}|${c.cfg ?? ''}|${c.steps ?? ''}|${c.steps2 ?? ''}`;
      if (!m.has(k)) m.set(k, { key: k, zModel: c.z_model || '', zModelLabel: c.z_model_label || '',
                                aspect: c.aspect || '', cfg: c.cfg, steps: c.steps, steps2: c.steps2 });
    }
    return [...m.values()].sort((a, b) =>
      (a.zModelLabel || '').localeCompare(b.zModelLabel || '')
      || a.aspect.localeCompare(b.aspect) || ((a.cfg ?? 0) - (b.cfg ?? 0))
      || ((a.steps ?? 0) - (b.steps ?? 0)) || ((a.steps2 ?? 0) - (b.steps2 ?? 0)));
  }, [displayedCells]);

  const gridRows = useMemo(() => {
    const seen = new Map();
    for (const c of displayedCells) if (!seen.has(c.checkpoint)) seen.set(c.checkpoint, c.label);
    return [...seen.entries()].map(([filename, label]) => ({ filename, label }))
      .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
  }, [displayedCells]);

  const gridCols = useMemo(() => {
    const set = new Set(displayedCells.map((c) => c.strength));
    return [...set].sort((a, b) => a - b);
  }, [displayedCells]);  // dépend des cellules affichées (pas de d) — sinon colonnes figées au changement de run

  // --- Mode vote rapide : enchaîne les images non votées (swipe / 👍 / 👎) ----
  const unvoted = displayedCells.filter((c) => c.status === 'done' && c.filename && !c.rating);
  // 2e passe : revoter UNIQUEMENT les 👍 pour resserrer (un 👎 les bascule rouge,
  // un 👍 les reconfirme, passer les laisse vertes).
  const greens = displayedCells.filter((c) => c.status === 'done' && c.filename && c.rating === 1);

  if (gridRows.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      <RunSelector
        runs={studio.runHistory?.length ? studio.runHistory.map((run) => ({
          ...run, key: run.run_id, likes: run.likes || 0, dislikes: run.dislikes || 0,
        })) : runs}
        activeRunKey={activeRunKey}
        onSelect={studio.selectRun}
        unvotedCount={unvoted.length}
        onStartVote={() => vote.startVoting(unvoted)}
        greenCount={greens.length}
        onStartReVote={() => vote.startVoting(greens, '♻️ Reconfirm the 👍')}
        displayedCount={displayedCells.length}
        showResults={showResults}
        onToggleResults={() => setShowResults((v) => !v)}
        hasMore={!!studio.historyCursor}
        loadingMore={studio.historyLoading}
        onLoadMore={() => studio.loadRunHistory({ append: true })}
      />
      {showResults && (
        <ResultsGrid
          gridRows={gridRows}
          gridCols={gridCols}
          variantsInData={variantsInData}
          cellList={cellList}
          scoreMap={scoreMap}
          best={d.best_cell}
          datasetId={datasetId}
          onRate={studio.rate}
          onOpen={onOpen}
          fmt={fmt}
        />
      )}
    </div>
  );
}
