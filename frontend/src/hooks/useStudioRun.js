/**
 * useStudioRun — data hook of the autonomous multi-LoRA test Studio.
 *
 * Pilots ONE run identified by `runId`. Polls
 * GET /api/studio/run/<runId>/status (3 s while cells are pending — same rhythm
 * as useLoraTestStudio) and exposes the mutations: rate a cell 👍/👎, cancel the
 * run, resume it. When `runId` is null → no poll (blank studio waiting for a run).
 *
 * Contract of the status payload (delivered by the backend):
 *   { run_id, loras:[{dataset_id, lora_label, dataset_name}],
 *     cells:[{id, dataset_id, checkpoint, label, strength, aspect, filename,
 *             rating, seed, run_seed, status, prompt, z_model, cfg, steps}],
 *     lora_ranking:[{dataset_id, lora_label, dataset_name, likes, dislikes,
 *                    voted, net, wilson}],
 *     pending, resumable, gpu_busy }
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useToast } from '../components/common/Toast';
import { getJson, safePostJson as postJson } from '../api/fetchClient';

export function useStudioRun(runId, { pollMs = 3000 } = {}) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!runId) return false;
    const request = ++requestRef.current;
    try {
      const next = await getJson(`/api/studio/run/${runId}/status`);
      if (request === requestRef.current) {
        setData(next);
        setError(null);
      }
      return true;
    } catch (cause) {
      if (request === requestRef.current) setError(cause?.message || 'Could not load this run');
      return false;
    }
  }, [runId]);

  // Vide la grille DÈS que le run change : sinon on garde les cellules du run
  // précédent tant que le refetch n'a pas répondu (et si le fetch échoue ça reste
  // bloqué sur l'ancien run). null = pas de run sélectionné → studio vierge.
  useEffect(() => {
    requestRef.current += 1;
    setData(null);
    setError(null);
  }, [runId]);

  useEffect(() => { refresh(); }, [refresh]);

  // Self-scheduling poll: retries a failed first request and never overlaps.
  useEffect(() => {
    if (!runId || (data && !data.pending)) return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      await refresh();
      if (!cancelled) timer = setTimeout(poll, pollMs);
    };
    timer = setTimeout(poll, pollMs);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [runId, data, refresh, pollMs]);

  // Vote sur une image de test — réutilise la route existante lora-test/rate.
  const rate = useCallback(async (imageId, rating) => {
    const d = await postJson(`/api/dataset/lora-test/image/${imageId}/rate`, { rating });
    if (!d.ok) {
      toast.error(d.error);
      return false;
    }
    await refresh();
    return true;
  }, [refresh, toast]);

  const cancel = useCallback(async () => {
    if (!runId) return undefined;
    const d = await postJson(`/api/studio/run/${runId}/cancel`);
    if (d.ok) toast.success(`${d.cancelled} generation(s) stopped — resumable`);
    else toast.error(d.error);
    await refresh();
    return d;
  }, [runId, refresh, toast]);

  const resume = useCallback(async () => {
    if (!runId) return undefined;
    const d = await postJson(`/api/studio/run/${runId}/resume`);
    if (d.ok) toast.success(`${d.resumed} cell(s) restarted with their settings`);
    else toast.error(d.error);
    await refresh();
    return d;
  }, [runId, refresh, toast]);

  return { data, error, refresh, rate, cancel, resume };
}
