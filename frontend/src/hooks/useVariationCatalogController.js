import { useEffect, useMemo, useRef, useState } from 'react'
import { useToast } from '../components/common/Toast'
import { useConfirmDialog, usePromptDialog } from '../components/common/ConfirmDialog'
import { useCapabilities } from '../context/CapabilitiesContext'
import { apiFetch } from '../api/fetchClient'
import { initialVariationSelection } from '../components/dataset/variationRecommendations'
import { useVariationEngines } from './useVariationEngines'
import { useShotPersistence } from './useShotPersistence'
import {
  applyRemoteIdentityCanary, buildVariationLaunch, partitionExistingShots,
} from '../components/dataset/variationLaunch'
import { applyShotPreset, deleteShotPreset, renameShotPreset, saveShotPreset } from '../utils/shotPresets'
import { toggleInSet } from '../utils/selection'
import { usePersistedPreference } from './usePersistedPreference'

const parseBoolean = (value) => value === '1'
const serializeBoolean = (value) => value ? '1' : '0'

/** Owns catalog loading, shot selection, presets, engine state, and launch policy. */
export function useVariationCatalogController({ onGenerate, bodyFidelity, recommendedIds,
  images, variationLabelCounts, anchorPlan }) {
  const toast = useToast();
  const confirm = useConfirmDialog();
  const promptDialog = usePromptDialog();
  const { caps } = useCapabilities();
  const generationRates = caps.generation_pricing?.per_image || {};
  const nanoBananaRate = Number(generationRates.nanobanana) || 0;
  const chatGptApiRate = Number(generationRates.chatgpt_api) || 0;
  const pricingAsOf = caps.generation_pricing?.as_of;
  const [catalog, setCatalog] = useState([]);
  const appliedRecommendationKey = useRef('');
  const [nsfwCatalog, setNsfwCatalog] = useState([]);
  const [presets, setPresets] = useState({});
  const [catalogLoadError, setCatalogLoadError] = useState(false);
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [selected, setSelected] = useState(new Set());
  const [multiplier, setMultiplier] = useState(1);
  const [klein, setKlein] = useState(null);
  // 🔞 NSFW mode — local Klein ONLY (the backend refuses NSFW on API engines).
  // Unlocks the uncensored body catalog + a free-prompt custom variation.
  const { value: nsfwMode, setValue: setNsfwMode } = usePersistedPreference(
    'datasetNsfwMode', false, { parse: parseBoolean, serialize: serializeBoolean },
  );
  const [customPrompt, setCustomPrompt] = useState('');
  const [customFraming, setCustomFraming] = useState('body');
  // User-authored shot cards ("Add" under the free prompt): they live in their
  // own Custom group after BACK, are selectable like catalog cards and are the
  // only DELETABLE ones (catalog cards stay fixed). Persisted across sessions.
  const {
    customShots, customPresets, storageWarning,
    commitCustomShots, commitCustomPresets,
  } = useShotPersistence(toast);

  const addCustomShot = () => {
    const p = customPrompt.trim();
    if (!p) return;
    const hot = nsfwMode && isKlein;
    const shot = { id: `custom_${Date.now()}`, label: `${hot ? '🔞' : '✨'} ${p.slice(0, 40)}`,
                   prompt: p, framing: customFraming, nsfw: hot };
    commitCustomShots([...customShots, shot]);
    setSelected((s) => new Set(s).add(shot.id));   // freshly added = selected
    setCustomPrompt('');
  };

  const removeCustomShot = (id) => {
    commitCustomShots(customShots.filter((c) => c.id !== id));
    setSelected((s) => { const n = new Set(s); n.delete(id); return n; });
  };
  // Identity LoRA strength (F1): higher = closer to the reference face,
  // lower = more variety in the generated variations.
  // dx8152 consistency LoRA: anchors STRUCTURE, its guide recommends ~0.5 and
  // warns 0.8-1.0 can stop edits from applying (0.9 made variations near-copies).
  const [loraStrength, setLoraStrength] = useState(0.5);
  const {
    generator, setGenerator, settingsError, remoteAllowed,
    isNB, isGPT, isKlein, nbAvailable, gptAvailable, klAvailable,
    nbProviderReady, gptProviderReady, nanoBananaProviderLabel,
    approveRemoteGeneration, currentAvailable, gptViaSub, gptPlanLabel, kleinHint,
  } = useVariationEngines(caps);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/api/dataset/variations')
      .then((d) => {
        if (cancelled) return;
        setCatalog(d.catalog || []);
        setNsfwCatalog(d.nsfw_catalog || []);
        setPresets(d.presets || {});
        setCatalogLoadError(false);
        // Body-fidelity datasets start on the body-emphasis preset (figure-visible
        // outfits); everyone else keeps the balanced default.
        setSelected(new Set(initialVariationSelection(
          d.presets, bodyFidelity, recommendedIds,
        )));
      })
      .catch(() => {
        // Loud failure (M6): an empty catalog otherwise looks like a UI bug.
        if (!cancelled) {
          setCatalogLoadError(true);
          toast.error('Could not load the variation catalog');
        }
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast, catalogAttempt]);

  // An import-first dataset gets a deliberately small first selection: the
  // backend coverage plan's empty combinations. This is a one-time default,
  // not a lock — the user can still choose a preset or toggle any shot.
  useEffect(() => {
    if (!Array.isArray(recommendedIds) || !catalog.length) return;
    const ids = recommendedIds.filter((id) => catalog.some((entry) => entry.id === id));
    const key = JSON.stringify(ids);
    if (appliedRecommendationKey.current === key) return;
    setSelected(new Set(ids));
    appliedRecommendationKey.current = key;
  }, [catalog, recommendedIds]);

  const byFraming = useMemo(() => {
    const g = { face: [], bust: [], body: [], back: [] };
    catalog.forEach((e) => g[e.framing]?.push(e));
    return g;
  }, [catalog]);

  // Switching to an API engine drops any selected NSFW shots (Klein-only) —
  // catalog nsfw_ entries AND 🔞 custom cards alike.
  useEffect(() => {
    if (isKlein) return;
    const hotCustom = new Set(customShots.filter((c) => c.nsfw).map((c) => c.id));
    setSelected((s) => {
      const n = new Set([...s].filter((id) => !id.startsWith('nsfw_') && !hotCustom.has(id)));
      return n.size === s.size ? s : n;
    });
  }, [isKlein, customShots]);

  // "Already in the dataset" per variation label: live images (kept, pending or
  // still generating — not failed/rejected) → the green ✓×N state on the cards.
  const doneByLabel = useMemo(() => {
    const m = new Map(Object.entries(variationLabelCounts));
    for (const img of images) {
      if (!img.variation_label || img.status === 'failed' || img.status === 'reject') continue;
      if (!Object.prototype.hasOwnProperty.call(variationLabelCounts, img.variation_label)) {
        m.set(img.variation_label, (m.get(img.variation_label) || 0) + 1);
      }
    }
    return m;
  }, [images, variationLabelCounts]);
  const identityVerified = isKlein || images.some((image) => (
    image.source === 'generated'
      && image.status === 'keep'
      && image.generation_engine === generator
  ));

  // Framing mix of each preset — feeds the mini composition bar on its card.
  const presetStats = useMemo(() => {
    const framingById = new Map(catalog.map((e) => [e.id, e.framing]));
    const stats = {};
    Object.entries(presets).forEach(([key, ids]) => {
      const counts = { face: 0, bust: 0, body: 0, back: 0 };
      (ids || []).forEach((id) => { const fr = framingById.get(id); if (fr) counts[fr] += 1; });
      stats[key] = { counts, total: (ids || []).length };
    });
    return stats;
  }, [catalog, presets]);

  // Which preset (if any) matches the current selection exactly → highlighted card.
  const activePreset = useMemo(() => {
    const entry = Object.entries(presets).find(([, ids]) =>
      ids && ids.length === selected.size && ids.every((id) => selected.has(id)));
    return entry ? entry[0] : null;
  }, [presets, selected]);

  const activeCustomPreset = useMemo(() => customPresets.find((preset) =>
    preset.selectedIds.length === selected.size
      && preset.selectedIds.every((id) => selected.has(id)))?.id || null,
  [customPresets, selected]);

  const customPresetStats = useMemo(() => {
    const framingById = new Map([
      ...catalog, ...nsfwCatalog, ...customShots,
      ...customPresets.flatMap((preset) => preset.customShots || []),
    ].map((shot) => [shot.id, shot.framing]));
    return Object.fromEntries(customPresets.map((preset) => {
      const counts = { face: 0, bust: 0, body: 0, back: 0 };
      preset.selectedIds.forEach((id) => { const fr = framingById.get(id); if (fr) counts[fr] += 1; });
      return [preset.id, { counts, total: preset.selectedIds.length }];
    }));
  }, [catalog, nsfwCatalog, customShots, customPresets]);

  const toggle = (id) => setSelected((current) => toggleInSet(current, id));

  // Never wipe the current selection when the preset is unavailable (M6).
  // Toggle: re-clicking the ACTIVE preset (exact selection match) clears the
  // whole selection instead of re-applying it.
  const applyPreset = (key) => {
    const ids = presets[key];
    if (!ids?.length) return;
    setSelected(activePreset === key ? new Set() : new Set(ids));
  };

  const saveCurrentPreset = async () => {
    const name = await promptDialog({
      title: 'Save shot preset',
      inputLabel: 'Preset name',
      confirmLabel: 'Save preset',
    });
    if (name == null) return;
    try {
      const next = saveShotPreset(customPresets, name, selected, customShots);
      commitCustomPresets(next, `Preset saved: ${next.at(-1).name}`);
    } catch (error) { toast.error(error.message || 'Could not save preset'); }
  };

  const applyCustomPreset = (preset) => {
    if (activeCustomPreset === preset.id) {
      setSelected(new Set());
      return;
    }
    const availableIds = new Set([...catalog, ...nsfwCatalog].map((shot) => shot.id));
    const restored = applyShotPreset(preset, customShots, availableIds);
    if (restored.customShots.length !== customShots.length) commitCustomShots(restored.customShots);
    setSelected(new Set(restored.selectedIds));
    if (restored.droppedIds.length) {
      toast.error(`${restored.droppedIds.length} saved shot${restored.droppedIds.length === 1 ? '' : 's'} no longer exist and were removed from this selection.`);
    }
  };

  const renameCustomPreset = async (preset) => {
    const name = await promptDialog({
      title: 'Rename shot preset',
      inputLabel: 'Preset name',
      defaultValue: preset.name,
      confirmLabel: 'Rename preset',
    });
    if (name == null) return;
    try { commitCustomPresets(renameShotPreset(customPresets, preset.id, name)); }
    catch (error) { toast.error(error.message || 'Could not rename preset'); }
  };

  const removeCustomPreset = async (preset) => {
    if (!(await confirm({
      title: `Delete preset “${preset.name}”?`,
      message: 'The saved shot selection will be removed. Generated images are unaffected.',
      confirmLabel: 'Delete preset',
      tone: 'danger',
    }))) return;
    commitCustomPresets(deleteShotPreset(customPresets, preset.id));
  };

  const go = async () => {
    const variations = buildVariationLaunch({
      catalog, nsfwCatalog, customShots, selected, nsfwMode, isKlein,
    });
    if (!variations.length) return;
    // Guard-rail: the selection survives a previous Generate, so a re-click would
    // re-generate (and re-bill) shots that already exist. Ask — OK = duplicates
    // on purpose, Cancel = only the newly added shots.
    const { existing: dupes, fresh } = partitionExistingShots(variations, doneByLabel);
    let toGen = variations;
    if (dupes.length === variations.length) {
      if (!(await confirm({
        title: 'Generate duplicate shots?',
        message: `All ${dupes.length} selected shots already exist in the dataset. Generate every selected shot again anyway?`,
        confirmLabel: 'Generate duplicates',
        tone: 'warning',
      }))) return;
    } else if (dupes.length > 0) {
      if (!(await confirm({
        title: 'Include existing shots?',
        message: `${dupes.length} of ${variations.length} selected shots already exist. Generate all shots, including duplicates, or only the ${fresh.length} new shots?`,
        confirmLabel: 'Generate all',
        cancelLabel: 'Only new shots',
        tone: 'warning',
      }))) {
        toGen = fresh;
      }
    }
    if (!toGen.length) return;
    const launch = applyRemoteIdentityCanary({
      variations: toGen, multiplier, images, engine: generator, isKlein,
    });
    if (!isKlein) {
      const requestCount = launch.variations.length * launch.multiplier;
      const destination = isNB ? nanoBananaProviderLabel : 'OpenAI';
      const providerName = isNB
        ? `Nano Banana Pro via ${nanoBananaProviderLabel}`
        : `ChatGPT ${gptPlanLabel}`;
      const referenceCount = Math.min(Number(anchorPlan?.selected_total) || 0, 5);
      const rate = isNB ? nanoBananaRate : gptViaSub ? 0 : chatGptApiRate;
      const costLine = rate > 0
        ? ` Estimated provider cost: about $${(requestCount * rate).toFixed(2)}.`
        : ' This uses your connected ChatGPT plan quota.';
      const permissionLine = remoteAllowed
        ? '' : ' Accepting also enables third-party image generation in Settings.';
      if (!(await confirm({
        title: launch.canary
          ? `Verify identity with ${providerName}?`
          : `Generate ${requestCount} shot${requestCount === 1 ? '' : 's'} with ${providerName}?`,
        message: `${launch.canary && launch.requestedTotal > 1
          ? `You selected ${launch.requestedTotal} outputs, but batch generation stays locked until you approve one likeness. `
          : ''}This sends ${referenceCount} selected reference image${referenceCount === 1 ? '' : 's'} and ${requestCount} prompt${requestCount === 1 ? '' : 's'} to ${destination}.${costLine}${permissionLine}${launch.canary
          ? ' Review the result in Curation: keep it to unlock batches, or reject it and adjust the provider or references.'
          : ''}`,
        confirmLabel: launch.canary
          ? 'Generate 1 identity canary'
          : `Allow this ${requestCount}-shot batch`,
        tone: 'warning',
      }))) return;
      try {
        await approveRemoteGeneration();
      } catch (error) {
        toast.error(error.message || 'Could not enable third-party image generation');
        return;
      }
    }
    onGenerate(launch.variations, launch.multiplier, klein, loraStrength, generator);
  };

  return {
    nanoBananaRate, chatGptApiRate, pricingAsOf, nsfwCatalog,
    catalogLoadError, setCatalogAttempt, selected, setSelected, multiplier,
    setMultiplier, setKlein, nsfwMode, setNsfwMode, customPrompt,
    setCustomPrompt, customFraming, setCustomFraming, customShots, customPresets,
    storageWarning, addCustomShot, removeCustomShot, loraStrength, setLoraStrength,
    setGenerator, settingsError, remoteAllowed, isNB, isGPT, isKlein,
    nbAvailable, gptAvailable, klAvailable, nbProviderReady, gptProviderReady,
    nanoBananaProviderLabel, approveRemoteGeneration, currentAvailable, gptViaSub, gptPlanLabel,
    kleinHint, identityVerified, byFraming, doneByLabel, presetStats, activePreset, activeCustomPreset,
    customPresetStats, toggle, applyPreset, saveCurrentPreset, applyCustomPreset,
    renameCustomPreset, removeCustomPreset, go,
  }
}
