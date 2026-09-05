import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { getJson, safePostJson as postJson } from '../../api/fetchClient';
import { useCapabilities } from '../../context/CapabilitiesContext';
import {
  checkpointSelectionMatchesTraining,
  defaultCheckpointBase,
  loraFolderLabel,
  trainFamilyLabel,
} from '../../utils/checkpointBrowser';
import { useToast } from '../common/Toast';
import { useConfirmDialog, usePromptDialog } from '../common/ConfirmDialog';
import TrainingProgress from './TrainingProgress';
import ResumeTrainingDialog from './ResumeTrainingDialog';
import PreflightModal from './PreflightModal';
import CloudLaunchDialog from './CloudLaunchDialog';
import { baseName, DEFAULT_CUSTOM_FAMILIES, looksAbsolute } from './trainingPanelModel';
import { deriveCloudTrainingState } from './trainingCloudState';
import { OPT_FOR_FLAG } from './trainingLaunchPolicy';
import TrainingAdvancedOptions from './TrainingAdvancedOptions';
import TrainingCheckpointBrowserView from './TrainingCheckpointBrowserView';
import { useTrainingPresets } from './useTrainingPresets';
import { useCheckpointBrowser } from './useCheckpointBrowser';
import { useTrainingMonitoring } from '../../hooks/useTrainingMonitoring';
import { useTrainingLaunch } from '../../hooks/useTrainingLaunch';

// Familles qui exposent « Custom weights… » + celles honorant VAE/TE
// (miroir de CUSTOM_WEIGHTS_FAMILIES / VAE_TE_OVERRIDE_FAMILIES côté serveur ;
// base-info les renvoie, ces défauts ne servent qu'avant son chargement).
// Absolute path = the persisted custom-weights path (never a ComfyUI-relative
// base name): Windows drive (C:\), UNC (\\), or POSIX (/…).
/** Panneau d'entraînement LoRA : lance l'UI ai-toolkit (pause ComfyUI),
 * affiche l'état, liste les checkpoints et importe celui choisi.
 * Poll régulier : c'est ce poll qui fait avancer la file (fin du courant → suivant). */
export default function TrainingPanel({ ds, keptCount, kind, onCheckpointsChange,
                                        checkpointHost = null,
                                        navigationPanel = null,
                                        onNavigationStateChange,
                                        onPanelOpenChange }) {
  const concept = kind === 'concept' || kind === 'style';  // style: même chemin UI
  const { caps } = useCapabilities();
  const cloudConfigured = caps.cloud_configured ?? caps.cloud_training;
  const trainingVisible = caps.training_visible || cloudConfigured;
  const toast = useToast();
  const confirm = useConfirmDialog();
  const promptDialog = usePromptDialog();
  // Polls every 10s: advances the queue server-side + updates the UI. Skipped
  // entirely while training is hidden (ai-toolkit not configured) — no point
  // hitting endpoints the backend doesn't expose in that state.
  const { status, statusLoaded, cloudStatus, refreshStatus } = useTrainingMonitoring({
    trainingVisible, cloudTraining: caps.cloud_training, cloudConfigured,
    onNavigationStateChange,
  });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [checkpointsOpen, setCheckpointsOpen] = useState(false);
  // {registered, version, changed, diff} — provenance du dataset (registre).
  const [trainingFeedback, setTrainingFeedback] = useState(null);
  // {steps, kind, n_images, rationale} renvoyé par /train/checkpoints — le POURQUOI
  // du barème adaptatif, affiché avec le champ Steps (pédagogie, pas boîte noire).
  const [stepsInfo, setStepsInfo] = useState(null);
  const [enqErr, setEnqErr] = useState(null);
  // Base d'entraînement (officielle ou merge custom) + variante + conversion.
  const [baseInfo, setBaseInfo] = useState(null);
  const [baseInfoState, setBaseInfoState] = useState('loading');
  const [preflightSummary, setPreflightSummary] = useState(null);
  const [preflightState, setPreflightState] = useState('loading');
  const [base, setBase] = useState('');
  // « Custom weights… » (local-only) : quand actif, `base` porte un chemin ABSOLU
  // vers un .safetensors de la même architecture (krea/flux/flux2klein/sdxl).
  const [customBase, setCustomBase] = useState(false);
  // Overrides SDXL UNIQUEMENT : chemin VAE + chemin/te repo-id du text-encoder.
  const [vaePath, setVaePath] = useState('');
  const [tePath, setTePath] = useState('');
  const [variant, setVariant] = useState('turbo');
  // Type de LoRA : 'zimage' (défaut, encodeur Qwen3-4B) ou 'sdxl' (checkpoints ComfyUI).
  const [trainType, setTrainType] = useState('zimage');
  // Navigateur de résultats indépendant : changer la configuration du PROCHAIN
  // entraînement ne doit jamais faire disparaître les checkpoints que l'utilisateur
  // est en train de consulter dans la section dédiée.
  const checkpointSelectionDataset = useRef(null);
  const familyChangeRequest = useRef(0);
  // Réglages ai-toolkit avancés éditables (rank / resolution / save_every /
  // sample_every / sample_prompts), chargés depuis base-info ; persistés par POST
  // /train/settings via ds.setTrainSettings.
  const [adv, setAdv] = useState(null);
  // Textarea des prompts de preview : état local (édition libre), sauvé au blur —
  // resynchronisé sur la valeur stockée canonique chaque fois que `adv` arrive/change.
  const [samplePromptsText, setSamplePromptsText] = useState('');
  const checkpointBrowser = useCheckpointBrowser({ dataset: ds, baseInfo,
    visible: trainingVisible, toast, onCountChange: onCheckpointsChange });
  // Saves cloud synchronisés en local (y compris ceux d'un run EN COURS) —
  // liste séparée : le prompt Resume-or-Fresh ne raisonne que sur le local.
  // {run_dir_bytes, training_dataset_bytes, cloud_staging_bytes, deployed_bytes, total_bytes}
  const { trainType: checkpointTrainType, setTrainType: setCheckpointTrainType,
    base: checkpointBase, setBase: setCheckpointBase, checkpoints, imported,
    cloudCheckpoints: cloudCkpts, datasetState, diskUsage, loaded: ckLoaded,
    refresh: loadCheckpoints } = checkpointBrowser;

  useEffect(() => {
    if (navigationPanel === 'advanced') setAdvancedOpen(true);
  }, [navigationPanel]);

  const togglePanel = (panelId, current, setter) => (event) => {
    event.preventDefault();
    const next = !current;
    setter(next);
    onPanelOpenChange?.(panelId, next);
  };

  // Charge les bases + la base/variante du dataset au montage.
  useEffect(() => {
    if (!trainingVisible) return undefined;
    let alive = true;
    setBaseInfoState('loading');
    ds.trainBaseInfo?.().then((info) => {
      if (alive && info) {
        setBaseInfo(info); setBase(info.base || '');
        // A persisted ABSOLUTE base is the « Custom weights… » path → reopen that mode.
        setCustomBase(looksAbsolute(info.base || ''));
        setVaePath(info.vae_path || '');
        setTePath(info.te_path || '');
        // Défaut family-aware : Krea sans variante persistée → Raw (reco officielle
        // « train on Raw, validate on Turbo ») ; FLUX.2 Klein → 4B (voie locale) —
        // y compris quand la variante PERSISTÉE vient d'une autre famille (un
        // dataset ex-Krea porte 'base', qui n'est pas une taille Klein valide) ;
        // les autres familles → Turbo.
        const fam = info.train_type || 'zimage';
        const v = info.variant
          || (fam === 'krea' ? 'base' : fam === 'flux2klein' ? '4b' : 'turbo');
        setVariant(fam === 'flux2klein' && !['4b', '9b'].includes(v) ? '4b' : v);
        setTrainType(info.train_type || 'zimage');
        // Initialiser le navigateur une seule fois par dataset. Les refreshs de
        // base-info (conversion, réglages) ne doivent pas écraser son filtre.
        if (checkpointSelectionDataset.current !== ds.currentId) {
          checkpointSelectionDataset.current = ds.currentId;
          setCheckpointTrainType(fam);
          setCheckpointBase(info.base || '');
        }
        setAdv(info.train_settings || null);
        setBaseInfoState('ready');
      } else if (alive) {
        setBaseInfoState('error');
      }
    }).catch(() => { if (alive) setBaseInfoState('error'); });
    return () => { alive = false; };
  }, [ds.currentId, trainingVisible]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!trainingVisible || !ds.currentId || baseInfoState !== 'ready') return undefined;
    let alive = true;
    setPreflightState('loading');
    getJson(`/api/dataset/${ds.currentId}/train/preflight?train_type=${encodeURIComponent(trainType)}`)
      .then((data) => {
        if (!alive) return;
        setPreflightSummary(data);
        setPreflightState('ready');
      })
      .catch(() => { if (alive) setPreflightState('error'); });
    return () => { alive = false; };
  }, [trainingVisible, ds.currentId, trainType, keptCount, baseInfoState]);

  // Pendant une conversion, poll le statut toutes les 4 s. Dépend de la fonction
  // STABLE (useCallback sur currentId), pas de l'objet `ds` entier — sinon
  // l'interval était recréé à chaque render et le timer 4 s n'aboutissait jamais.
  const getBaseInfo = ds.trainBaseInfo;
  useEffect(() => {
    if (!trainingVisible || baseInfo?.convert?.status !== 'running') return undefined;
    const id = setInterval(async () => {
      const info = await getBaseInfo?.();
      if (info) setBaseInfo(info);
    }, 4000);
    return () => clearInterval(id);
  }, [baseInfo?.convert?.status, getBaseInfo, trainingVisible]);

  // Bases selon le type choisi (zimage : officiel + merges ; sdxl : checkpoints ComfyUI).
  const currentBases = baseInfo?.bases_by_type?.[trainType] || baseInfo?.bases || [];
  // base_dir non configuré → les listers renvoient [] : distinguer « aucun modèle de
  // cette famille » de « ComfyUI pas encore pointé » (le vrai motif sur un clone neuf).
  // Défaut true tant que baseInfo n'est pas chargé, pour ne pas flasher la CTA au montage.
  const comfyConfigured = baseInfo?.comfyui_configured !== false;
  const baseSelected = !!base;
  // « Custom weights… » (local-only) : familles qui l'exposent + celles honorant
  // VAE/TE (SDXL). base-info fait foi ; défauts avant chargement.
  const customFamilies = baseInfo?.custom_weights_families || DEFAULT_CUSTOM_FAMILIES;
  const customSupported = customFamilies.includes(trainType);
  const vaeTeFamilies = baseInfo?.vae_te_families || ['sdxl'];
  const vaeTeSupported = vaeTeFamilies.includes(trainType);
  // Mode custom actif mais chemin vide → rien à entraîner (bloque le bouton).
  const customWeightsEmpty = customBase && customSupported && !String(base).trim();
  // La conversion diffusers ne concerne QUE Z-Image (SDXL = single-file direct) ;
  // le mode « Custom weights… » (chemin absolu direct) ne convertit jamais.
  const needsConversion = trainType === 'zimage' && baseSelected && !customBase;
  const baseConverted = needsConversion && !!(baseInfo?.converted?.[base]);
  const convertRunning = needsConversion && baseInfo?.convert?.status === 'running' && baseInfo?.convert?.z_model === base;
  const convertError = (needsConversion && baseInfo?.convert?.status === 'error' && baseInfo?.convert?.z_model === base)
    ? baseInfo.convert.error : null;
  // Bloque l'entraînement si la base custom Z-Image n'est pas encore convertie,
  // ou si SDXL sans base choisie (SDXL exige un checkpoint).
  const baseBlocksTrain = needsConversion && !baseConverted;
  const sdxlNeedsBase = trainType === 'sdxl' && !base;
  // Changement de type : réinitialise la base (les listes diffèrent ; SDXL → 1ère base réelle)
  // et PERSISTE la famille (choisie à la création, modifiable ici) pour que le menu
  // regroupé se ré-trie et que le format de caption suive.
  const onTypeChange = async (t) => {
    const requestId = ++familyChangeRequest.current;
    setTrainType(t);
    setBaseInfoState('loading');
    setAdv(null);
    // Switching family leaves custom-weights mode (the path is arch-specific).
    setCustomBase(false);
    const list = baseInfo?.bases_by_type?.[t] || [];
    setBase(t === 'sdxl' ? (list[0]?.value || '') : '');
    // Krea → Raw par défaut (reco officielle « train on Raw, validate on Turbo »).
    setVariant(t === 'krea' ? 'base' : t === 'flux2klein' ? '4b' : 'turbo');
    // FLUX.2 Klein → 4B par défaut (voie locale 16-24 GB ; le 9B est la voie cloud).
    if (t !== 'sdxl') { setVaePath(''); setTePath(''); }
    try {
      const saved = await ds.setDatasetTrainType?.(t);
      if (requestId !== familyChangeRequest.current) return;
      if (!saved?.ok) throw new Error('family was not saved');
      const info = await ds.trainBaseInfo?.();
      if (requestId !== familyChangeRequest.current) return;
      if (!info || info.train_type !== t) throw new Error('family metadata did not refresh');
      setBaseInfo(info);
      setAdv(info.train_settings || null);
      setBaseInfoState('ready');
    } catch {
      setBaseInfoState('error');
      toast.error('The training family could not be loaded. Launch controls remain unavailable.');
    }
  };

  // Réglages avancés effectifs (client-side pour que le défaut family-aware du rank
  // suive un changement de type SANS re-fetch). `adv.rank` null = Auto.
  const advRankChoice = adv?.rank ?? 'auto';
  const advDefaultRank = (trainType === 'zimage' || trainType === 'flux' || trainType === 'flux2klein') ? 16 : 32;   // miroir de _DEFAULT_RANK
  const advEffRank = advRankChoice === 'auto' ? advDefaultRank : advRankChoice;
  // Expert levers (all default to current behaviour when absent):
  const advAlphaChoice = adv?.alpha_setting ?? 'auto';
  const advDefaultAlpha = trainType === 'sdxl' ? Math.max(1, Math.floor(advEffRank / 2)) : advEffRank;
  const advEffAlpha = advAlphaChoice !== 'auto' ? advAlphaChoice : advDefaultAlpha;
  const advAlphaChoices = adv?.alpha_choices ?? [1, 2, 4, 8, 16, 24, 32, 48, 64];
  const advDropout = adv?.dropout ?? 0;
  const advDropoutChoices = adv?.dropout_choices ?? [0.05, 0.1, 0.15, 0.2, 0.3];
  const advTimestep = adv?.timestep_type ?? 'auto';
  const advTimestepDefault = trainType === 'krea' ? 'linear' : trainType === 'flux2klein' ? 'weighted' : (trainType === 'zimage' || trainType === 'flux') ? 'sigmoid' : null;   // miroir de _DEFAULT_TIMESTEP
  const advTimestepSupported = trainType !== 'sdxl';
  const advTimestepChoices = adv?.timestep_type_choices ?? ['sigmoid', 'linear', 'weighted', 'shift'];
  const advOptimizer = adv?.optimizer ?? 'adamw8bit';
  const advOptimizerChoices = adv?.optimizer_choices ?? ['adamw8bit', 'adafactor', 'automagic', 'prodigy'];
  const advLrSched = adv?.lr_scheduler ?? 'constant';
  const advLrSchedChoices = adv?.lr_scheduler_choices ?? ['constant', 'linear', 'cosine', 'cosine_with_restarts', 'constant_with_warmup'];
  const advWarmup = adv?.warmup ?? 0;
  const advWarmupChoices = adv?.warmup_choices ?? [50, 100, 200, 500];
  const advGradAccum = adv?.grad_accum ?? 1;
  const advGradAccumChoices = adv?.grad_accum_choices ?? [1, 2, 4];
  // Recipe levers — network variant (LoKr) + EMA. LoKr is arch-generic in ai-toolkit,
  // so network_type_supported is always true today; the flag mirrors the timestep
  // pattern so a future family could be gated with one server-side flip.
  const advNetworkType = adv?.network_type ?? 'lora';
  const advNetworkChoices = adv?.network_type_choices ?? ['lora', 'lokr'];
  const advNetworkSupported = adv ? adv.network_type_supported !== false : true;
  const advEma = adv?.ema ?? 0;
  const advEmaChoices = adv?.ema_choices ?? [0.99, 0.999];
  const LR_SCHED_LABELS = { constant: 'Constant (default)', constant_with_warmup: 'Warmup → constant', linear: 'Linear decay', cosine: 'Cosine decay', cosine_with_restarts: 'Cosine + restarts' };
  const advRes = adv?.resolution ?? '768,1024';
  const advSave = adv?.save_every ?? 250;
  const advSampleEvery = adv?.sample_every ?? 250;
  const advSampleEveryChoices = adv?.sample_every_choices ?? [100, 250, 500, 1000];
  const advSampleDefault = adv?.sample_prompts_default ?? [];
  const advMaxPrompts = adv?.max_sample_prompts ?? 8;
  const saveAdv = async (patch) => {
    const eff = await ds.setTrainSettings?.(patch);
    if (eff) setAdv(eff);
  };
  // Seed / re-sync the preview-prompts textarea from the stored value whenever
  // base-info (re)loads. Save is on blur, so the user is never mid-typing here.
  useEffect(() => {
    setSamplePromptsText((adv?.sample_prompts ?? []).join('\n'));
  }, [adv?.sample_prompts]);
  const saveSamplePrompts = () => {
    const stored = (adv?.sample_prompts ?? []).join('\n');
    if (samplePromptsText === stored) return;      // no-op → skip the round-trip
    saveAdv({ sample_prompts: samplePromptsText }); // server splits on newlines + trims
  };

  // Normalizes like useDataset's own postJson: a non-2xx response (e.g. the
  // 409 {'error','hint'} the training routes return when ai-toolkit isn't
  // configured, or a 400 for a refused enqueue) must surface as `ok: false`
  // — previously this just returned the raw body, so callers checking
  // `d.ok === false` never saw the error (d.ok stayed undefined) and it was
  // silently dropped instead of reaching the confirm/toast below.
  const postTrain = (path, body) => postJson(path, body);
  // 409 {'error','hint'} (or any other refusal) → toast, hint appended when present.
  const toastTrainError = (d, fallback) => {
    const msg = (d && d.error) || fallback;
    toast.error(d && d.hint ? `${msg} — ${d.hint}` : msg);
  };
  // Presets de réglages avancés : snapshots nommés, partageables (fichier JSON).
  // Stockés bruts côté serveur ; la validation se fait à l'APPLICATION (clés
  // inconnues ignorées, valeurs invalides signalées) → tolérant aux versions.
  const presetController = useTrainingPresets({ datasetId: ds.currentId, trainType,
    setAdvancedSettings: setAdv, toast, confirm, promptDialog, postTrain,
    reportError: toastTrainError });
  const { preflightReport, resolvePreflight, resumeAsk, resolveResume, masked,
    setMasked, maskedRembgMissing, stepsOverride, setStepsOverride,
    stepsOverrideValid, hasInvalidStepsOverride, stepsN, enqueue, dequeue,
    queuedItem, queued, showSched, schedAt, setSchedAt, openSched, schedule,
    cloudDialog, setCloudDialog, launchCloud, preflightOk, askResumeOrFresh,
    confirmableRetryFlag } = useTrainingLaunch({
    ds, trainType, base, variant, vaePath, tePath, concept, caps, status, refreshStatus,
    setPreflightSummary, setPreflightState, toast, confirm,
    postTrain, toastTrainError, setEnqErr,
  });

  // Le barème affiché dans Training suit uniquement la configuration Training,
  // jamais le filtre indépendant du navigateur de résultats.
  useEffect(() => {
    if (!trainingVisible || !ds.currentId || !baseInfo) return undefined;
    let alive = true;
    ds.listCheckpoints(base, trainType).then((data) => {
      if (alive) setStepsInfo(data?.recommended_steps_info || null);
    }).catch(() => { /* keep the last truthful rationale */ });
    return () => { alive = false; };
  }, [base, trainType, ds.currentId, baseInfo, trainingVisible]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!ds.currentId) { setTrainingFeedback(null); return undefined; }
    let alive = true;
    getJson(`/api/dataset/${ds.currentId}/train/feedback?family=${encodeURIComponent(checkpointTrainType)}`)
      .then((data) => { if (alive) setTrainingFeedback(data); })
      .catch(() => { if (alive) setTrainingFeedback(null); });
    return () => { alive = false; };
  }, [ds.currentId, checkpointTrainType, checkpoints, imported]);
  const removeImported = async (filename, label) => {
    // Guard-rail: this LoRA may be the one the Studio's ★ best settings point to —
    // deleting it silently breaks the saved winning combo.
    const best = ds.data?.best_settings;
    const isBest = best?.lora_filename
      && baseName(best.lora_filename) === baseName(filename);
    const message = isBest
      ? `« ${label} » is the LoRA saved as this dataset's best setting in the Test Studio. The saved combination will stop working, but the file remains recoverable in Settings until you empty the Trash.`
      : `« ${label} » will be moved out of ComfyUI's ${checkpointLorasLabel} folder and remain recoverable in Settings until you empty the Trash.`;
    if (!(await confirm({
      title: `Move “${label}” to Trash?`,
      message,
      confirmLabel: 'Move to Trash',
      tone: 'danger',
    }))) return;
    await ds.deleteCheckpoint(filename, checkpointTrainType);
    loadCheckpoints();
  };
  const doPrepareBase = async () => {
    await ds.prepareBase(base);
    const info = await ds.trainBaseInfo();
    if (info) setBaseInfo(info);
  };

  // Best-epoch (jandordoe): score the run's samples vs the reference, recommend
  // the checkpoint closest to the best-scoring step. Result cleared on base change.
  const [bestEpoch, setBestEpoch] = useState(null);
  const [bestEpochBusy, setBestEpochBusy] = useState(false);
  useEffect(() => { setBestEpoch(null); }, [checkpointBase, checkpointTrainType, ds.currentId]);
  const findBestEpoch = async () => {
    setBestEpochBusy(true);
    try {
      const d = await postTrain(`/api/dataset/${ds.currentId}/train/best-epoch`,
        { base_model: checkpointBase, train_type: checkpointTrainType });
      if (d && d.ok === false) { toastTrainError(d, 'best-epoch scoring failed'); return; }
      setBestEpoch(d);
    } finally {
      setBestEpochBusy(false);
    }
  };

  // Estimation des steps adaptatifs — purement indicative ; le backend recalcule la
  // valeur autoritaire au lancement (même barème). Character : ~120/image, bornés
  // [1500,3500]. Concept/style : SOUS-LINÉAIRE 475·√n, bornés [2000,12000] — un gros
  // set doit généraliser, pas mémoriser (à 400 img : ~9500 steps, pas 3500).
  const recoSteps = concept
    ? Math.max(2000, Math.min(12000, Math.round((475 * Math.sqrt(Math.max(keptCount, 1))) / 100) * 100))
    : Math.max(1500, Math.min(3500, Math.round((keptCount * 120) / 100) * 100));
  // Libellé lisible de la base sélectionnée (pour étiqueter les checkpoints de CE run).
  // Custom weights → basename du fichier (jamais le chemin complet dans le résumé).
  const baseLabel = customBase && base
    ? `custom: ${baseName(base)}`
    : (currentBases.find((b) => b.value === base)?.label || (base || 'Official'));
  const typeLabel = trainFamilyLabel(trainType);
  const preflightFloor = Number.isFinite(preflightSummary?.floor) ? preflightSummary.floor : Infinity;
  const preflightRecommended = Number.isFinite(preflightSummary?.recommended)
    ? preflightSummary.recommended : null;
  const preflightBlocker = preflightSummary?.blockers?.[0] || null;
  const launchConfigReady = statusLoaded && baseInfoState === 'ready'
    && preflightState === 'ready' && !preflightBlocker;
  const checkpointBasesRaw = baseInfo?.bases_by_type?.[checkpointTrainType] || baseInfo?.bases || [];
  const checkpointBaseOptions = checkpointBase && !checkpointBasesRaw.some((item) => item.value === checkpointBase)
    ? [{ value: checkpointBase, label: `custom: ${baseName(checkpointBase)}` }, ...checkpointBasesRaw]
    : checkpointBasesRaw;
  const checkpointBaseLabel = checkpointBaseOptions.find((item) => item.value === checkpointBase)?.label
    || (checkpointBase ? baseName(checkpointBase) : 'Official');
  const openTrainingFolder = async (body) => {
    const d = await postTrain(`/api/dataset/${ds.currentId}/train/open-folder`, body);
    if (d?.ok === false) toastTrainError(d, 'Could not open the folder');
  };
  const checkpointTypeLabel = trainFamilyLabel(checkpointTrainType);
  const checkpointLorasLabel = loraFolderLabel(checkpointTrainType);
  const checkpointMatchesTraining = checkpointSelectionMatchesTraining(
    checkpointTrainType, checkpointBase, trainType, base);
  const onCheckpointTypeChange = (nextType) => {
    const choices = baseInfo?.bases_by_type?.[nextType] || [];
    setCheckpointTrainType(nextType);
    setCheckpointBase(defaultCheckpointBase(choices));
  };

  // Panel gated off (ai-toolkit not configured): the workspace's checkpoint
  // count must not keep a stale value from a previous dataset/session.
  useEffect(() => {
    if (!trainingVisible) onCheckpointsChange?.(0);
  }, [trainingVisible]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cloud run status (global — several cloud runs may be active at once,
  // across different datasets, up to cloudStatus.limit). Polled independently
  // of the local `status` poll above, and only while a cloud GPU API key is
  // actually configured.
  // Compat: older servers (or a stale poll) may still answer with only the
  // single `active` field — fall back to a 1-element list built from it.
  // Multi-family parallelism is safe again: each cloud run's monitor builds its
  // job config from its OWN stamped family/variant, not the shared dataset row
  // (backend _run_config_dataset — fix for the 2026-07-14 incident). So a Krea
  // run and a Z-Image run may train the same dataset at once; the button is
  // blocked only when a run of the SAME family is already active here.
  // Single source of truth for WHY « ☁ Train in cloud » is disabled — most
  // fundamental cause first (family unsupported > custom weights > too few
  // images > a run already active here > global limit). Drives BOTH the tooltip
  // AND the always-visible reason line below: a disabled button must state its
  // reason without a hover (the owner lost time guessing on a greyed SDXL button
  // whose only explanation lived in a title attribute).
  const { actives, cloudActiveHere, cloudDisabledReason } = deriveCloudTrainingState({
    cloudStatus, datasetId: ds.currentId, trainType, keptCount, preflightFloor,
    typeLabel, customBase, vaePath, tePath, hasInvalidStepsOverride,
    stepsOverrideValid, launchConfigReady,
  });

  if (!trainingVisible) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border bg-surface p-3 text-content-muted text-sm">
        <span aria-hidden>🎓</span>
        Training needs ai-toolkit (local GPU) or a cloud GPU API key (vast.ai or RunPod) — set either in Settings.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-indigo-500/30 bg-indigo-500/5 p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-content font-semibold text-sm"><span aria-hidden>🎓</span> LoRA Training ({typeLabel})</span>
        {!status.installed && (
          <span className="text-amber-300 text-[0.6875rem]">ai-toolkit not installed — run setup-aitoolkit.ps1</span>
        )}
        {status.in_progress
          ? <span className="ml-auto flex items-center gap-2">
              <span aria-live="polite" className="text-indigo-300 text-[0.6875rem]">
                <span aria-hidden>⏳</span> {status.current?.name ? `« ${status.current.name} » running` : 'running'} — ComfyUI paused
              </span>
              {/* Full progress bar, loss curve and samples live on the Runs hub —
                  this panel's own TrainingProgress only covers THIS dataset. */}
              <Link to="/cloud" title="Open the Runs page — full progress, loss curve and samples"
                className="px-1 py-0.5 text-indigo-300 hover:text-indigo-200 text-[0.6875rem] font-medium underline decoration-indigo-300/40">
                View in Runs ↗
              </Link>
            </span>
          : <span aria-live="polite" className="ml-auto text-content-subtle text-[0.6875rem]">{keptCount} image(s) kept</span>}
      </div>

      {/* A cloud run left its pod alive for manual recovery (any dataset) — it
          keeps billing until reaped, so this must stay visible regardless of
          which dataset's panel happens to be open. No action button: the
          recovery is manual (outside the app) and expiry-reaping is automatic. */}
      {(cloudStatus.recovery_required || []).length > 0 && (
        <p className="m-0 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-amber-300 text-[0.6875rem]">
          ⚠ {(cloudStatus.recovery_required || []).length} cloud pod(s) require recovery and may still be billing until reaped: {(cloudStatus.recovery_required || []).map((run) => run.vast_instance_id || run.run_id).join(', ')}
        </p>
      )}

      {/* Local training CRASHED (ai-toolkit run.py exited non-zero): the watcher
          captured the reason into training_error. Without surfacing it, a run that
          starts then dies just flips back to idle after the green "Training started"
          toast — the exact "shows confirmation but nothing happens" report (GH #3).
          Cleared automatically on the next launch (server resets training_error). */}
      {status.error && (!status.error.dataset_id || status.error.dataset_id === ds.currentId) && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-red-200 text-[0.6875rem]">
          <div className="font-semibold">
            ⚠ The last training run failed{status.error.rc != null ? ` (ai-toolkit exited ${status.error.rc})` : ''} — nothing is training now.
          </div>
          {status.error.log_tail && (
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-1.5 font-mono text-[0.625rem] text-red-300/90">
              {status.error.log_tail}
            </pre>
          )}
          <div className="mt-1 text-red-300/80">
            Common first-run causes: ai-toolkit’s Python venv is missing packages
            (re-run its install), or the base model is still downloading / needs a
            Hugging Face token (gated models like Krea 2, FLUX.1 and FLUX.2 Klein). Fix the cause above, then Train again.
          </div>
        </div>
      )}

      {/* Live progress of THIS dataset's run: bar + loss sparkline + sample
          previews. Only while it is the one training (queued/other runs: no poll). */}
      {status.in_progress && status.current?.dataset_id === ds.currentId && (
        <TrainingProgress datasetId={ds.currentId}
          base={status.current.base_model ?? base}
          trainType={status.current.train_type ?? trainType} />
      )}

      {/* Cloud run progress + stop (this dataset only) — separate from the local
          poll above; runs entirely on the cloud GPU pod. */}
      {cloudActiveHere && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 text-[0.6875rem] text-sky-200 flex-wrap">
            <span aria-hidden>☁️</span>
            <span className="font-semibold">Cloud run — {cloudActiveHere.status}</span>
            {cloudActiveHere.gpu && <span>{cloudActiveHere.gpu}</span>}
            {cloudActiveHere.price_per_hour != null && (
              <span className="tabular-nums">
                ${cloudActiveHere.price_per_hour}/h · $
                {Number(cloudActiveHere.cost_usd ?? cloudActiveHere.cost_estimate ?? 0).toFixed(2)} so far
                {cloudActiveHere.billing_seconds != null
                  ? ` · billed ${Math.max(0, Math.floor(cloudActiveHere.billing_seconds / 60))}m`
                  : ''}
              </span>
            )}
            {/* Full progress bar, loss curve and samples live on the Runs hub. */}
            <Link to="/cloud" title="Open the Runs page — full progress, loss curve and samples"
              className="ml-auto px-1 py-0.5 text-sky-300 hover:text-sky-200 font-medium underline decoration-sky-300/40">
              View in Runs ↗
            </Link>
            <button type="button" className="px-2 py-0.5 rounded bg-red-600/80 text-white text-[0.6875rem] font-semibold"
              onClick={async () => {
                if (!(await confirm({
                  title: 'Stop this cloud run?',
                  message: 'The pod will be terminated and training will stop. The latest recoverable checkpoint is downloaded when possible.',
                  confirmLabel: 'Stop run',
                  tone: 'danger',
                }))) return;
                const result = await postJson(
                  '/api/dataset/train/cloud/stop', { run_id: cloudActiveHere.run_id });
                if (!result?.ok) toastTrainError(result, 'Could not stop cloud run');
              }}>
              Stop cloud run
            </button>
          </div>
          <TrainingProgress datasetId={ds.currentId} base={base} trainType={trainType} cloud />
        </div>
      )}
      {/* Download link only when the LAST run matches the selected family
          (a legacy payload without train_type matches any family). Keeping it
          keyed on cloudStatus.last stays simple — per-family history is
          served by ?train_type= on the checkpoint route itself. */}
      {cloudConfigured && !cloudActiveHere && cloudStatus.last
        && cloudStatus.last.dataset_id === ds.currentId
        && (!cloudStatus.last.train_type || cloudStatus.last.train_type === trainType)
        && cloudStatus.last.checkpoint_ready && cloudStatus.last.status === 'done' && (
        <a href={`/api/dataset/${ds.currentId}/train/cloud/checkpoint?train_type=${encodeURIComponent(trainType)}`}
          className="text-sky-300 text-[0.6875rem] underline w-fit">
          ⬇ Download the cloud-trained LoRA (.safetensors)
        </a>
      )}

      {/* --- Chemin essentiel : choisir le type de LoRA et lancer. Le reste
           (base/variante, masked, plafond de steps, programmation) vit dans
           « Advanced options » ci-dessous — replié par défaut, tout y reste
           accessible en un clic. --- */}
      <div className="flex items-center gap-2 flex-wrap rounded-lg border border-border bg-surface px-3 py-2">
        <span className="text-content-muted text-[0.625rem] uppercase">LoRA type</span>
        <select value={trainType} onChange={(e) => onTypeChange(e.target.value)}
          aria-label="Type of LoRA to train"
          title="Z-Image (prose, Qwen3 encoder) ~20 img · SDXL (ComfyUI checkpoints) ~30 img · Krea 2 (prose, base fixe Turbo) ~20 img · FLUX.1-dev (prose, gated HF, local-only) ~20 img · FLUX.2 Klein (prose, gated HF, 4B local / 9B cloud) ~20 img"
          className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
          <option value="zimage">Z-Image (~20 img)</option>
          <option value="sdxl">SDXL (~30 img)</option>
          <option value="krea">Krea 2 (~20 img)</option>
          <option value="flux">FLUX.1 (~20 img)</option>
          <option value="flux2klein">FLUX.2 Klein (~20 img)</option>
        </select>
        <button type="button" disabled={!launchConfigReady || !status.installed || keptCount < preflightFloor || status.in_progress || baseBlocksTrain || sdxlNeedsBase || customWeightsEmpty || hasInvalidStepsOverride || !stepsOverrideValid}
          title={baseBlocksTrain ? 'Convert the custom base first'
            : customWeightsEmpty ? 'Enter the path to your custom weights .safetensors'
            : sdxlNeedsBase ? 'Choose a base SDXL checkpoint'
            : preflightBlocker ? preflightBlocker
            : !launchConfigReady ? 'Training configuration and readiness must load successfully before launch'
            : keptCount < preflightFloor
              ? `${keptCount} kept image(s) — the minimum for ${typeLabel} is ${preflightFloor}`
              : undefined}
          onClick={async () => {
            if (!(await preflightOk())) return;
            // Run existant → Resume (continue le LoRA) ou Fresh (archive le run,
            // repart de zéro). Le mismatch-retry re-passe fresh : le 1er appel a
            // échoué AVANT l'archivage (assert_trainable), rien n'a été écarté.
            const mode = await askResumeOrFresh();
            if (!mode) return;
            const fresh = mode === 'fresh';
            let opts = { baseModel: base, variant, trainType, masked, steps: stepsN, fresh,
                         vaePath, tePath };
            let d = await ds.train(opts);
            while (d && d.ok === false) {
              const flag = await confirmableRetryFlag(d.error, 'Train anyway');
              if (!flag) break;
              if (flag === 'declined') break;        // the confirm WAS the answer
              opts = { ...opts, [OPT_FOR_FLAG[flag]]: true };
              d = await ds.train(opts);
            }
            refreshStatus();
          }}
          className="px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40">
          <span aria-hidden>🚀</span> Train the LoRA
        </button>
        {caps.cloud_training && (
          <button type="button"
            disabled={!!cloudDisabledReason}
            title={cloudDisabledReason
              || `Rents a ${caps.cloud_provider?.label || 'vast.ai'} GPU for this run`}
            onClick={async () => { if (await preflightOk()) setCloudDialog(true); }}
            className="px-3 py-1.5 rounded-lg border border-sky-500/50 bg-sky-500/10 text-sky-200 text-sm font-semibold disabled:opacity-40">
            <span aria-hidden>☁️</span> Train in cloud
          </button>
        )}
        {status.in_progress && (
          <button type="button" onClick={async () => {
            const deferred = (status.queue || []).length;
            if (!(await confirm({
              title: 'Stop active training?',
              message: `Stop the active training process now? Progress since its latest checkpoint may be lost. ${deferred ? `${deferred} queued or scheduled job(s) will be kept.` : 'There are no queued or scheduled jobs.'}`,
              confirmLabel: 'Stop and keep queue', tone: 'danger',
            }))) return;
            await ds.stopTraining({ clearQueue: false });
            refreshStatus();
          }}
            className="px-3 py-1.5 rounded-lg bg-red-600/80 text-white text-sm font-semibold">
            Stop training / re-enable ComfyUI
          </button>
        )}
        {status.in_progress && (status.queue || []).length > 0 && (
          <button type="button" onClick={async () => {
            const deferred = status.queue.length;
            if (!(await confirm({
              title: 'Stop training and cancel queue?',
              message: `Stop the active training process now and permanently remove all ${deferred} queued or scheduled job(s)? Progress since the latest checkpoint may also be lost.`,
              confirmLabel: `Stop and cancel ${deferred}`, tone: 'danger',
            }))) return;
            await ds.stopTraining({ clearQueue: true });
            refreshStatus();
          }}
            className="px-3 py-1.5 rounded-lg border border-red-500/50 bg-red-500/10 text-red-200 text-sm font-semibold">
            Stop + cancel queue ({status.queue.length})
          </button>
        )}
        {status.in_progress && status.installed && (
          <button type="button" disabled={!launchConfigReady || keptCount < preflightFloor || queued || baseBlocksTrain || hasInvalidStepsOverride || !stepsOverrideValid} onClick={enqueue}
            title={baseBlocksTrain
              ? 'Convert the selected custom base first'
              : `Train THIS dataset on « ${baseLabel} » once the current training finishes`}
            className="px-3 py-1.5 rounded-lg bg-indigo-500/20 border border-indigo-400/40 text-indigo-200 text-sm font-semibold disabled:opacity-40">
            {queued ? `✓ Queued (${trainFamilyLabel(queuedItem.train_type)})` : `➕ Add to queue (${baseLabel})`}
          </button>
        )}
        {/* Résumé lisible de la config que le prochain run utilisera — les
            réglages eux-mêmes vivent dans « Advanced options ». */}
        <span className="ml-auto text-content-subtle text-[0.625rem]"
          title="The configuration the next run will use — change it in Advanced options below">
          base « {baseLabel} » · {maskedRembgMissing ? 'unmasked (rembg missing)' : masked ? 'masked' : 'unmasked'} · {stepsOverride.trim() ? `${stepsN} steps` : 'adaptive steps'}{advNetworkType === 'lokr' ? ' · LoKr' : ''}{advEma ? ` · EMA ${advEma}` : ''}
        </span>
      </div>

      {/* A disabled ☁ Train-in-cloud button always states WHY, right under the
          button row — the tooltip alone was invisible until hovered, so a greyed
          SDXL cloud button read as an unexplained limit (owner-reported). */}
      {caps.cloud_training && cloudDisabledReason && (
        <p className="m-0 text-sky-300/90 text-[0.6875rem]">
          ☁ Cloud training unavailable — {cloudDisabledReason}
        </p>
      )}

      {actives.length > 0 && (
        <p className="m-0 text-content-subtle text-[0.625rem]">
          ☁ {actives.length}/{cloudStatus.limit || 1} cloud runs — ${cloudStatus.total_price_per_hour || 0}/h total
        </p>
      )}

      {/* Pointeur visible quand le bouton Train est bloqué par un réglage qui
          vit dans la section repliée — sinon la cause resterait cachée. */}
      {(baseBlocksTrain || sdxlNeedsBase) && (
        <p className="m-0 text-amber-300 text-[0.6875rem]">
          ⚠ {sdxlNeedsBase
            ? 'SDXL needs a base checkpoint — pick one in Advanced options below.'
            : convertRunning
              ? 'The selected base is being converted — training unlocks when it finishes (details in Advanced options).'
              : 'The selected custom base must be converted once before training — open Advanced options below.'}
        </p>
      )}

      <TrainingAdvancedOptions
        LR_SCHED_LABELS={LR_SCHED_LABELS} adv={adv} advAlphaChoice={advAlphaChoice} advAlphaChoices={advAlphaChoices} advDefaultAlpha={advDefaultAlpha}
        advDefaultRank={advDefaultRank} advDropout={advDropout} advDropoutChoices={advDropoutChoices} advEffAlpha={advEffAlpha} advEffRank={advEffRank}
        advEma={advEma} advEmaChoices={advEmaChoices} advGradAccum={advGradAccum} advGradAccumChoices={advGradAccumChoices} advLrSched={advLrSched}
        advLrSchedChoices={advLrSchedChoices} advMaxPrompts={advMaxPrompts} advNetworkChoices={advNetworkChoices} advNetworkSupported={advNetworkSupported} advNetworkType={advNetworkType}
        advOptimizer={advOptimizer} advOptimizerChoices={advOptimizerChoices} advRankChoice={advRankChoice} advRes={advRes} advSampleDefault={advSampleDefault}
        advSampleEvery={advSampleEvery} advSampleEveryChoices={advSampleEveryChoices} advSave={advSave} advTimestep={advTimestep} advTimestepChoices={advTimestepChoices}
        advTimestepDefault={advTimestepDefault} advTimestepSupported={advTimestepSupported} advWarmup={advWarmup} advWarmupChoices={advWarmupChoices} advancedOpen={advancedOpen}
        base={base} baseBlocksTrain={baseBlocksTrain} baseConverted={baseConverted} baseInfo={baseInfo} baseLabel={baseLabel}
        comfyConfigured={comfyConfigured} concept={concept} convertError={convertError} convertRunning={convertRunning} currentBases={currentBases}
        customBase={customBase} customSupported={customSupported} doPrepareBase={doPrepareBase} hasInvalidStepsOverride={hasInvalidStepsOverride} baseSelected={baseSelected}
        keptCount={keptCount} launchConfigReady={launchConfigReady} masked={masked} maskedRembgMissing={maskedRembgMissing} needsConversion={needsConversion}
        openSched={openSched} preflightFloor={preflightFloor} presetController={presetController} queued={queued} recoSteps={recoSteps}
        samplePromptsText={samplePromptsText} saveAdv={saveAdv} saveSamplePrompts={saveSamplePrompts} schedAt={schedAt} schedule={schedule}
        setAdvancedOpen={setAdvancedOpen} setBase={setBase} setCustomBase={setCustomBase} setMasked={setMasked} setSamplePromptsText={setSamplePromptsText}
        setSchedAt={setSchedAt} setStepsOverride={setStepsOverride} setTePath={setTePath} setVaePath={setVaePath} setVariant={setVariant}
        showSched={showSched} status={status} stepsInfo={stepsInfo} stepsOverride={stepsOverride} stepsOverrideValid={stepsOverrideValid} tePath={tePath}
        togglePanel={togglePanel} trainType={trainType} typeLabel={typeLabel} vaePath={vaePath} vaeTeSupported={vaeTeSupported}
        variant={variant}
      />

      {Array.isArray(status.queue) && status.queue.length > 0 && (
        <div id="ds-training-queue" tabIndex={-1} data-workspace-focus
          className="flex flex-col gap-1 rounded-lg border border-indigo-400/30 bg-indigo-500/5 px-3 py-2 scroll-mt-20">
          <span className="text-content-muted text-[0.625rem] uppercase">Training queue ({status.queue.length})</span>
          {status.queue.map((q, i) => (
            <div key={q.dataset_id} className="flex items-center gap-2 text-[0.6875rem]">
              <span className="text-content-subtle tabular-nums">{i + 1}.</span>
              <span className="text-content">{q.name}</span>
              <span className="text-indigo-300/80">· {trainFamilyLabel(q.train_type)}{q.variant ? ` (${q.variant})` : ''}</span>
              {q.base_label ? <span className="text-indigo-300/80">· {q.base_label}</span> : null}
              {q.extra_steps ? <span className="text-content-subtle">(+{q.extra_steps} steps)</span> : null}
              {q.steps ? <span className="text-content-subtle">→ {q.steps} steps</span> : null}
              {q.not_before ? (
                <span className="px-1.5 py-px rounded border border-amber-400/40 bg-amber-400/10 text-amber-300"
                  title="Scheduled — starts at this time (or right after the training running then)">
                  ⏰ {String(q.not_before).replace('T', ' ')}
                </span>
              ) : null}
              <button type="button" onClick={() => dequeue(q.dataset_id)}
                className="ml-auto px-2 py-0.5 rounded bg-red-500/15 border border-red-500/40 text-red-300">
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      {enqErr && (
        <p className="m-0 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-red-300 text-[0.6875rem]">
          ⚠️ Enqueue refused: {enqErr}
        </p>
      )}

      {preflightRecommended != null && keptCount < preflightRecommended && (
        <p className="m-0 text-content-subtle text-[0.625rem]">
          {typeLabel}: minimum {preflightFloor} kept images,{' '}
          {preflightRecommended} recommended — you have {keptCount}.
        </p>
      )}

      {/* --- Résultats : checkpoints du run + LoRA déjà importés dans ComfyUI.
           Repliés par défaut ; le résumé du summary donne les comptes sans ouvrir. */}
      <TrainingCheckpointBrowserView
        bestEpoch={bestEpoch} bestEpochBusy={bestEpochBusy} checkpointBase={checkpointBase} checkpointBaseLabel={checkpointBaseLabel} checkpointBaseOptions={checkpointBaseOptions} confirm={confirm}
        checkpointHost={checkpointHost} checkpointLorasLabel={checkpointLorasLabel} checkpointMatchesTraining={checkpointMatchesTraining} checkpointTrainType={checkpointTrainType} checkpointTypeLabel={checkpointTypeLabel}
        checkpoints={checkpoints} checkpointsOpen={checkpointsOpen} ckLoaded={ckLoaded} cloudCkpts={cloudCkpts} datasetState={datasetState}
        diskUsage={diskUsage} ds={ds} findBestEpoch={findBestEpoch} imported={imported} loadCheckpoints={loadCheckpoints}
        onCheckpointTypeChange={onCheckpointTypeChange} openTrainingFolder={openTrainingFolder} postTrain={postTrain} refreshStatus={refreshStatus} removeImported={removeImported}
        setCheckpointBase={setCheckpointBase} setCheckpointsOpen={setCheckpointsOpen} status={status} toast={toast} toastTrainError={toastTrainError} togglePanel={togglePanel}
        trainingFeedback={trainingFeedback} variant={variant}
      />

      {preflightReport && (
        <PreflightModal report={preflightReport} datasetId={ds.currentId} ds={ds}
          onResolve={resolvePreflight} />
      )}

      {cloudDialog && (
        <CloudLaunchDialog
          datasetId={ds.currentId} trainType={trainType} steps={stepsN}
          keptCount={keptCount} cloudStatus={cloudStatus}
          onClose={() => setCloudDialog(false)} onLaunch={launchCloud} />
      )}

      {/* Resume ou Fresh : un run existe déjà pour ce (trigger, base). ai-toolkit
          reprendrait silencieusement son dernier checkpoint — on demande. */}
      {resumeAsk && (
        <ResumeTrainingDialog checkpoint={resumeAsk} onResolve={resolveResume} />
      )}
    </div>
  );
}
