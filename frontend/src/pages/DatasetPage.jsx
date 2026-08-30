/**
 * Dataset Maker page — build a face dataset for LoRA character training:
 * generate Klein variations from a reference, import real photos, curate,
 * caption (Qwen3-VL), and export a training-ready ZIP.
 */
import { useEffect } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useDataset } from '../hooks/useDataset';
import DatasetListPanel from '../components/dataset/DatasetListPanel';
import DatasetWorkspace from '../components/dataset/DatasetWorkspace';
import {
  datasetWorkflowPath, legacyWorkspaceStep,
} from '../components/dataset/datasetWorkflow';

export default function DatasetPage() {
  const ds = useDataset();
  const { currentId, notFoundId, data, open, close } = ds;
  const navigate = useNavigate();
  const { datasetId, step } = useParams();
  const [searchParams] = useSearchParams();
  const routeId = datasetId ? Number(datasetId) : null;
  const validRouteId = routeId == null || (Number.isInteger(routeId) && routeId > 0);

  useEffect(() => {
    if (!validRouteId) {
      navigate('/datasets', { replace: true });
      return;
    }
    if (routeId != null && currentId !== routeId && notFoundId !== routeId) open(routeId);
  }, [routeId, validRouteId, currentId, notFoundId, open, navigate]);

  useEffect(() => {
    if (routeId != null && notFoundId === routeId) navigate('/datasets', { replace: true });
  }, [routeId, notFoundId, navigate]);

  useEffect(() => {
    if (routeId != null || !currentId) return;
    const legacyStep = legacyWorkspaceStep(searchParams);
    navigate(datasetWorkflowPath(currentId, legacyStep), { replace: true });
  }, [routeId, currentId, searchParams, navigate]);

  const openDataset = (id) => {
    open(id);
    navigate(datasetWorkflowPath(id));
  };

  const closeDataset = () => {
    close();
    navigate('/datasets');
  };

  if (routeId != null && (currentId !== routeId || data?.id !== routeId)) {
    return <p role="status" className="text-content-subtle text-sm">Loading dataset…</p>;
  }

  return (
    <div className="p-4">
      {currentId ? (
        <DatasetWorkspace ds={ds} onBack={closeDataset} stepSlug={step || null}
          onStepChange={(nextStep, options) => navigate(
            datasetWorkflowPath(currentId, nextStep), options,
          )} />
      ) : (
        <div className="max-w-4xl mx-auto">
          <DatasetListPanel datasets={ds.datasets} onOpen={openDataset} onCreate={ds.create}
            onDelete={ds.deleteDataset} onRestore={ds.importBackup} />
        </div>
      )}
    </div>
  );
}
