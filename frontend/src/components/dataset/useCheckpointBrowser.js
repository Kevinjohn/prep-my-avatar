import { useCallback, useEffect, useRef, useState } from 'react';
import { normalizeCheckpointPayload } from './trainingPanelResponsibilities';

/** Owns the result-browser filters and stale-safe checkpoint list lifecycle. */
export function useCheckpointBrowser({ dataset, baseInfo, visible, toast, onCountChange }) {
  const [trainType, setTrainType] = useState('zimage');
  const [base, setBase] = useState('');
  const [checkpoints, setCheckpoints] = useState([]);
  const [imported, setImported] = useState([]);
  const [cloudCheckpoints, setCloudCheckpoints] = useState([]);
  const [datasetState, setDatasetState] = useState(null);
  const [diskUsage, setDiskUsage] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const request = useRef(0);

  const refresh = useCallback(async (requestedBase, requestedType) => {
    const effectiveBase = typeof requestedBase === 'string' ? requestedBase : base;
    const effectiveType = typeof requestedType === 'string' ? requestedType : trainType;
    const requestId = ++request.current;
    try {
      const data = await dataset.listCheckpoints(effectiveBase, effectiveType);
      if (requestId !== request.current) return;
      const normalized = normalizeCheckpointPayload(data);
      const { checkpoints: local, imported: deployed, cloudCheckpoints: cloud } = normalized;
      setCheckpoints(local); setImported(deployed); setCloudCheckpoints(cloud);
      setDatasetState(normalized.datasetState); setDiskUsage(normalized.diskUsage);
      setLoaded(true);
      onCountChange?.(normalized.count);
    } catch {
      if (requestId === request.current) {
        setLoaded(true);
        toast.error('Checkpoint list could not be refreshed. Showing the last successful list.');
      }
    }
  }, [base, dataset, onCountChange, toast, trainType]);

  useEffect(() => {
    if (!visible || !dataset.currentId || !baseInfo) return;
    setLoaded(false); refresh(base, trainType);
  }, [base, trainType, dataset.currentId, baseInfo, visible]); // eslint-disable-line react-hooks/exhaustive-deps

  return { trainType, setTrainType, base, setBase, checkpoints, imported,
    cloudCheckpoints, datasetState, diskUsage, loaded, refresh };
}
