/**
 * useLoraTestStudio — data hook of the « Studio de test de LoRA ».
 *
 * Polls /api/dataset/<id>/lora-test/status (3 s while cells are pending, same
 * rhythm as the dataset fan-out) and exposes the mutations: launch run, rate
 * a cell 👍/👎, cancel the run, persist the best settings.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useToast } from '../components/common/Toast';
import { getJson, safeDeleteJson, safePostJson as postJson } from '../api/fetchClient';

export function useLoraTestStudio(datasetId, family = null) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState(null);
  const [runHistory, setRunHistory] = useState([]);
  const [historyCursor, setHistoryCursor] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const historyCursorRef = useRef(null);
  const historyLoadingRef = useRef(false);
  const requestRef = useRef(0);
  const selectedRunRef = useRef(null);

  const refresh = useCallback(async () => {
    if (!datasetId) return false;
    const request = ++requestRef.current;
    try {
      // `family` scope la pipeline (ZIT/SDXL/Krea) ; absent → défaut résolu côté serveur.
      const params = new URLSearchParams();
      if (family) params.set('family', family);
      if (selectedRunRef.current) params.set('run_id', selectedRunRef.current);
      const qs = params.size ? `?${params}` : '';
      const next = await getJson(`/api/dataset/${datasetId}/lora-test/status${qs}`);
      if (request === requestRef.current) {
        selectedRunRef.current = next.selected_run_id || null;
        setData(next); setError(null);
      }
      return true;
    } catch (cause) {
      if (request === requestRef.current) setError(cause?.message || 'Could not load Studio status');
      return false;
    }
  }, [datasetId, family]);

  const loadRunHistory = useCallback(async ({ append = false } = {}) => {
    if (!datasetId || historyLoadingRef.current) return false;
    const cursor = append ? historyCursorRef.current : null;
    if (append && !cursor) return false;
    historyLoadingRef.current = true;
    setHistoryLoading(true);
    try {
      const params = new URLSearchParams({ limit: '20' });
      if (family) params.set('family', family);
      if (cursor) params.set('cursor', String(cursor));
      const payload = await getJson(`/api/dataset/${datasetId}/lora-test/runs?${params}`);
      setRunHistory((previous) => append
        ? [...previous, ...(payload.runs || [])]
        : (payload.runs || []));
      historyCursorRef.current = payload.next_cursor ?? null;
      setHistoryCursor(historyCursorRef.current);
      return true;
    } catch (cause) {
      setError(cause?.message || 'Could not load Studio run history');
      return false;
    } finally {
      historyLoadingRef.current = false;
      setHistoryLoading(false);
    }
  }, [datasetId, family]);

  const selectRun = useCallback(async (runId) => {
    selectedRunRef.current = runId || null;
    return refresh();
  }, [refresh]);

  // Vide la grille DÈS que le dataset change : sinon on continue d'afficher les
  // cellules du LoRA précédent tant que le refetch n'a pas répondu (et si le
  // fetch échoue, ça reste bloqué sur l'autre LoRA — ex. eva6938 dans le studio
  // d'un autre dataset).
  useEffect(() => {
    requestRef.current += 1;
    selectedRunRef.current = null;
    setData(null);
    setError(null);
    setRunHistory([]);
    historyCursorRef.current = null;
    setHistoryCursor(null);
  }, [datasetId, family]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { loadRunHistory(); }, [loadRunHistory]); // explicit, bounded history request

  // Retry the first fetch and serialize subsequent polling requests.
  useEffect(() => {
    if (!datasetId || (data && !data.pending)) return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      await refresh();
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [datasetId, data, refresh]);

  const launch = useCallback(async (checkpoints, strengths, seed, prompt, zModels, aspects, cfgs, stepsList, steps2List, count = 1, genSettings = {}) => {
    setLaunching(true);
    try {
      // `genSettings` = réglages GLOBAUX snake_case remontés par StudioGenerationSettings
      // (resolution_tier, negative, sampler, scheduler, weight_dtype, rebalance(+_strength),
      // enhancer(+_strength), detail_amount, permanent_loras) — déjà gatés PAR FAMILLE côté
      // serveur ; les champs vides sont absents (le backend garde alors ses défauts).
      const d = await postJson(`/api/dataset/${datasetId}/lora-test/run`,
        { checkpoints, strengths, seed, prompt, z_models: zModels, aspects, cfgs, steps: stepsList, steps2: steps2List, count, family, ...genSettings });
      if (d.ok) {
        selectedRunRef.current = d.run_id || null;
        toast.success(`${d.created} generation(s) queued (seed ${d.seed}${d.count > 1 ? ` ×${d.count}` : ''})`);
      }
      else toast.error(d.error || 'Unexpected error');
      await refresh();
      await loadRunHistory();
      return d;
    } finally {
      setLaunching(false);
    }
  }, [datasetId, refresh, loadRunHistory, toast, family]);

  const rate = useCallback(async (imageId, rating) => {
    const d = await postJson(`/api/dataset/lora-test/image/${imageId}/rate`, { rating });
    if (!d.ok) {
      toast.error(d.error || 'Unexpected error');
      return false;
    }
    await refresh();
    return true;
  }, [refresh, toast]);

  // Scoring facial objectif (« best epoch » auto) : InsightFace CPU côté serveur,
  // puis refresh → le payload porte face_ranking + face_score par cellule.
  const [scoring, setScoring] = useState(false);
  const scoreFaces = useCallback(async () => {
    setScoring(true);
    try {
      const d = await postJson(`/api/dataset/${datasetId}/lora-test/score-faces`,
        family ? { family } : {});
      // Un scorer cassé disait « done — 0/14 » en VERT (user-reported) : le
      // backend remonte maintenant scoring_error {kind, detail} — dire POURQUOI.
      if (!d.ok) toast.error(d.error || 'Scoring failed');
      else if (d.scoring_error) {
        const { kind, detail } = d.scoring_error;
        toast.error(kind === 'unavailable'
          ? 'Face scoring is not installed — run the Quality tools step in Setup.'
          : kind === 'ref_unusable'
            ? `The reference photo is not usable for scoring: ${detail}`
            : `Face scoring failed: ${detail}`);
      } else if (!d.total) {
        toast.info('Nothing to score yet — run a test with several checkpoints (same seed) first.');
      } else {
        toast.success(`Face scoring done — ${d.scored}/${d.total} cell(s) scored`);
      }
      await refresh();
      return d;
    } finally {
      setScoring(false);
    }
  }, [datasetId, family, refresh, toast]);

  const cancel = useCallback(async () => {
    const d = await postJson(`/api/dataset/${datasetId}/lora-test/cancel`);
    if (d.ok) toast.success(`${d.cancelled} generation(s) stopped — resumable`);
    else toast.error(d.error || 'Unexpected error');
    await refresh();
  }, [datasetId, refresh, toast]);

  const resume = useCallback(async () => {
    if (!family) {
      const d = { ok: false, error: 'Choose a model family before resuming.' };
      toast.error(d.error);
      return d;
    }
    const d = await postJson(`/api/dataset/${datasetId}/lora-test/resume`, { family });
    if (d.ok) toast.success(`${d.resumed} cell(s) restarted with their settings`);
    else toast.error(d.error || 'Unexpected error');
    await refresh();
    return d;
  }, [datasetId, family, refresh, toast]);

  // Persiste la config gagnante COMPLÈTE (pas juste checkpoint+strength) : on
  // passe la cellule entière pour garder modèle/cfg/steps/format.
  const setBest = useCallback(async (cell) => {
    const d = await postJson(`/api/dataset/${datasetId}/lora-test/best`, {
      generation_config: Object.fromEntries([
        'checkpoint', 'strength', 'aspect', 'z_model', 'cfg', 'steps', 'steps2',
        'extra_loras', 'krea_rebalance', 'negative', 'sampler', 'scheduler',
        'weight_dtype', 'enhancer_strength', 'detail_amount', 'resolution_tier',
        'init_image', 'denoise',
      ].map((key) => [key, cell[key] ?? null])),
    });
    if (d.ok) toast.success('★ Best setting saved');
    else toast.error(d.error || 'Unexpected error');
    await refresh();
    return d;
  }, [datasetId, refresh, toast]);

  // Supprime le réglage mémorisé (DELETE — pas géré par postJson). `fam` cible une
  // famille précise (les autres gardent leur best) ; absent → famille courante du hook.
  const clearBest = useCallback(async (fam) => {
    const f = fam || family;
    const qs = f ? `?family=${encodeURIComponent(f)}` : '';
    const d = await safeDeleteJson(`/api/dataset/${datasetId}/lora-test/best${qs}`);
    if (d.ok) toast.success('Saved setting removed'); else toast.error(d.error || 'Error');
    await refresh();
    return d;
  }, [datasetId, refresh, toast, family]);

  // Supprime un prompt récent + ses cellules/images de test — sur TOUS les
  // datasets du user (la liste des prompts récents est désormais GLOBALE).
  const deletePrompt = useCallback(async (prompt) => {
    const d = await postJson('/api/studio/recent-prompts/delete', { prompt });
    if (d.ok) toast.success(`Prompt deleted (${d.deleted} image(s))`); else toast.error(d.error || 'Error');
    await refresh();
    return d;
  }, [refresh, toast]);

  return {
    data, error, refresh, launch, rate, cancel, resume, setBest, clearBest,
    deletePrompt, launching, scoreFaces, scoring, runHistory, historyCursor,
    historyLoading, loadRunHistory, selectRun,
  };
}
