import { useEffect, useRef, useState } from 'react'
import { getJson } from '../api/fetchClient'
import { confirmableTrainingRefusal, parseTrainingSteps, trainingLaunchBody } from '../components/dataset/trainingLaunchPolicy'

/** Owns local, queued, scheduled, and cloud launch decisions and dialogs. */
export function useTrainingLaunch({ ds, trainType, base, variant, vaePath, tePath,
  concept, caps, status, refreshStatus, setPreflightSummary,
  setPreflightState, toast, confirm, postTrain, toastTrainError, setEnqErr }) {
  // Confirmable launch refusals: the server prefixes the error with a marker;
  // the dialog IS the user's answer, the retry carries the matching
  // force flag. Both can fire in sequence (uncaptioned first, then mismatch) —
  // call sites loop until launched, declined, or a non-confirmable error.
  const confirmableRetryFlag = async (error, actionLabel) => {
    const refusal = confirmableTrainingRefusal(error);
    if (!refusal) return null;
    return await confirm({ title: actionLabel, message: refusal.message,
      confirmLabel: actionLabel, tone: 'warning' }) ? refusal.flag : 'declined';
  };

  // Pre-launch sanity gate (server preflight): blockers stop with a toast,
  // warnings open the interactive PreflightModal (lists WHICH captions leak /
  // WHICH pairs duplicate, editable/rejectable in place) and await the user's
  // Start-anyway / Cancel. Unreachable preflight never blocks.
  const [preflightReport, setPreflightReport] = useState(null);
  const preflightResolver = useRef(null);
  const resolvePreflight = (ok) => {
    setPreflightReport(null);
    preflightResolver.current?.(ok);
    preflightResolver.current = null;
  };
  const preflightOk = async () => {
    try {
      const d = await getJson(
        `/api/dataset/${ds.currentId}/train/preflight?train_type=${encodeURIComponent(trainType)}`);
      setPreflightSummary(d);
      setPreflightState('ready');
      if (d.blockers?.length) { toast.error(d.blockers.join('\n')); return false; }
      if (d.warnings?.length) {
        return await new Promise((resolve) => {
          preflightResolver.current = resolve;
          setPreflightReport(d);
        });
      }
      return true;
    } catch {
      setPreflightState('error');
      toast.error('Training readiness could not be checked. Retry when the server is reachable.');
      return false;
    }
  };
  // Des checkpoints existent déjà → cliquer Train demande Resume ou Fresh :
  // ai-toolkit REPREND silencieusement le dernier checkpoint du run (les images
  // supprimées du dataset restent apprises dans ses poids) — après un remaniement
  // du dataset, l'utilisateur veut presque toujours repartir de zéro. Le choix
  // résout une promesse : 'fresh' | 'resume' | null (annuler).
  const [resumeAsk, setResumeAsk] = useState(null);   // {latest, final} | null
  const resumeResolver = useRef(null);
  const resolveResume = (v) => {
    setResumeAsk(null);
    resumeResolver.current?.(v);
    resumeResolver.current = null;
  };
  const askResumeOrFresh = async () => {
    // Ne pas lire la liste affichée dans le navigateur de résultats : elle peut
    // volontairement pointer vers une autre famille/base. Le backend fait foi
    // pour la configuration d'entraînement actuellement sélectionnée.
    try {
      const data = await ds.listCheckpoints(base, trainType);
      const existing = Array.isArray(data?.checkpoints) ? data.checkpoints : [];
      if (!existing.length) return 'resume';
      const latest = Math.max(...existing.map((c) => c.step));
      const final = existing.some((c) => c.final);
      return new Promise((resolve) => {
        resumeResolver.current = resolve;
        setResumeAsk({ latest, final });
      });
    } catch {
      toast.error('Checkpoints could not be checked. Training was not started; retry the checkpoint check first.');
      return null;
    }
  };

  // Masked training (fond 10 %) — défaut ON, persisté (partagé lancement/file/programmation).
  const [masked, setMaskedS] = useState(() => {
    try { return localStorage.getItem('trainMasked_v1') !== '0'; } catch { return true; }
  });
  const setMasked = (v) => {
    setMaskedS(v);
    try { localStorage.setItem('trainMasked_v1', v ? '1' : '0'); } catch { /* ignore */ }
  };
  // Dataset CONCEPT : masked OFF par défaut (un masque « personne » effacerait le
  // concept qu'on veut apprendre). On force l'état SANS écrire la préférence perso
  // (setMaskedS direct) → rouvrir un personnage retrouve ON. Rejoué au changement de
  // dataset ou de nature.
  useEffect(() => {
    if (concept) setMaskedS(false);
    else { try { setMaskedS(localStorage.getItem('trainMasked_v1') !== '0'); } catch { setMaskedS(true); } }
  }, [ds.currentId, concept]);
  // Masked ON but rembg (person-mask backend) unavailable → the export silently
  // drops the masks and trains UNMASKED. Surface that instead of lying about it.
  // `=== false` (not `!caps.masks`) so we don't warn before caps have loaded.
  const maskedRembgMissing = masked && !concept && caps.masks === false;
  // Plafond de steps CHOISI (vide → adaptatif). NON persisté à dessein : un cap
  // oublié (ex. 2000) ne doit pas s'appliquer en douce au prochain dataset.
  const [stepsOverride, setStepsOverride] = useState('');
  // Cible envoyée au backend (Train / Add to queue / Schedule) : null = adaptatif ;
  // sinon plancher à 500 (le backend re-clampe pareil). Non numérique → 500.
  const { valid: stepsOverrideValid, invalidFormat: hasInvalidStepsOverride, steps: stepsN } = parseTrainingSteps(stepsOverride);

  const enqueue = async () => {
    if (!(await preflightOk())) return;
    const mode = await askResumeOrFresh();
    if (!mode) return;
    // Mise en file AVEC la base/variante choisie (sinon le job reprend la base persistée).
    let body = trainingLaunchBody({ base, variant, trainType, masked, steps: stepsN,
      mode, vaePath, tePath });
    let d = await postTrain(`/api/dataset/${ds.currentId}/train/enqueue`, body);
    while (d && d.ok === false) {
      const flag = await confirmableRetryFlag(d.error, 'Queue anyway');
      if (!flag) break;
      if (flag === 'declined') { d = null; break; }  // the confirm WAS the answer
      body = { ...body, [flag]: true };
      d = await postTrain(`/api/dataset/${ds.currentId}/train/enqueue`, body);
    }
    if (d && d.ok === false) { setEnqErr(d.error || 'enqueue refused'); toastTrainError(d, 'enqueue refused'); }
    else setEnqErr(null);
    refreshStatus();
  };
  const dequeue = async (id) => {
    const d = await postTrain(`/api/dataset/${id}/train/dequeue`);
    if (d && d.ok === false) toastTrainError(d, 'dequeue failed');
    refreshStatus();
  };
  const queuedItem = (status.queue || []).find((q) => q.dataset_id === ds.currentId);
  const queued = Boolean(queuedItem);

  // --- Entraînement PROGRAMMÉ (jour + heure) : entre en file avec une échéance ;
  // à l'heure dite le ticker serveur le lance, ou le met en attente si un autre
  // entraînement occupe déjà le GPU (jamais d'erreur). ---
  const [showSched, setShowSched] = useState(false);
  const [schedAt, setSchedAt] = useState('');
  const openSched = () => {
    if (!schedAt) {
      // Défaut : dans 1 h, arrondi au quart d'heure (format datetime-local, heure locale).
      const t = new Date(Date.now() + 3600e3);
      t.setMinutes(Math.ceil(t.getMinutes() / 15) * 15, 0, 0);
      const p = (n) => String(n).padStart(2, '0');
      setSchedAt(`${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}T${p(t.getHours())}:${p(t.getMinutes())}`);
    }
    setShowSched((v) => !v);
  };
  const schedule = async () => {
    if (!schedAt) return;
    if (!(await preflightOk())) return;
    const mode = await askResumeOrFresh();
    if (!mode) return;
    let body = trainingLaunchBody({ base, variant, trainType, masked, steps: stepsN,
      mode, vaePath, tePath }, { at: schedAt });
    let d = await postTrain(`/api/dataset/${ds.currentId}/train/schedule`, body);
    while (d && d.ok === false) {
      const flag = await confirmableRetryFlag(d.error, 'Schedule anyway');
      if (!flag) break;
      if (flag === 'declined') { d = null; break; }  // the confirm WAS the answer
      body = { ...body, [flag]: true };
      d = await postTrain(`/api/dataset/${ds.currentId}/train/schedule`, body);
    }
    if (d && d.ok === false) { setEnqErr(d.error || 'schedule refused'); toastTrainError(d, 'schedule refused'); }
    else { setEnqErr(null); setShowSched(false); }
    refreshStatus();
  };

  // Launch-time GPU speed picker: the ☁️ button opens a dialog that lists live
  // vast.ai offers by speed (price/h + approx time + cost); the chosen class is
  // forwarded as gpu_name. launchCloud carries the POST + the MISMATCH_CAPTION
  // retry that used to live inline in the button handler.
  const [cloudDialog, setCloudDialog] = useState(false);
  const launchCloud = async (gpuName) => {
    let body = { variant, train_type: trainType, masked,
      ...(stepsN ? { steps: stepsN } : {}), ...(gpuName ? { gpu_name: gpuName } : {}) };
    let d = await postTrain(`/api/dataset/${ds.currentId}/train/cloud`, body);
    while (d && d.ok === false) {
      const flag = await confirmableRetryFlag(d.error, 'Train anyway');
      if (!flag) break;
      if (flag === 'declined') { d = null; break; }  // the confirm WAS the answer
      body = { ...body, [flag]: true };
      d = await postTrain(`/api/dataset/${ds.currentId}/train/cloud`, body);
    }
    if (d && d.ok === false) {
      toastTrainError(d, 'Cloud training failed');
      return false;
    }
    if (!d) return false;
    // Success needs no toast — the 5s cloud-status poll picks it up.
    return true;
  };

  return { preflightReport, resolvePreflight, resumeAsk, resolveResume, masked,
    setMasked, maskedRembgMissing, stepsOverride, setStepsOverride,
    stepsOverrideValid, hasInvalidStepsOverride, stepsN, enqueue, dequeue,
    queuedItem, queued, showSched, schedAt, setSchedAt, openSched, schedule,
    cloudDialog, setCloudDialog, launchCloud, preflightOk, askResumeOrFresh,
    confirmableRetryFlag }
}
