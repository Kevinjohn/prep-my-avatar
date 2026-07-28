import logging
import threading
from contextlib import contextmanager
from flask import current_app
from .job_queue import queue_manager

logger = logging.getLogger(__name__)

class GpuBusyError(RuntimeError):
    pass


def recover_stale_vision_window():
    """Clear a persisted vision lock during server startup.

    Vision work runs synchronously inside this Python process. If the process is
    starting, no vision request from the previous process can still be alive, but
    its database-backed TTL flag may be. Keeping that flag is what caused a restart
    after interrupted captioning to report "GPU busy" for up to 30 minutes.
    """
    previous = queue_manager._get_system_state('vision_in_progress')
    # The only in-process owners are gone at startup.  Clear the unified lease
    # as well, including leases whose wall-clock TTL has not elapsed yet.
    from .job_queue import GPU_LEASE_KEY
    previous_lease = queue_manager._get_system_state(GPU_LEASE_KEY)
    lease_owner = (previous_lease or {}).get('owner') if isinstance(previous_lease, dict) else None
    if not previous and lease_owner != 'vision':
        return False
    queue_manager._set_system_state('vision_in_progress', None)
    if lease_owner == 'vision':
        queue_manager._set_system_state(GPU_LEASE_KEY, None)
    logger.warning('startup recovery: cleared stale vision/GPU lock from the previous process')
    return True

@contextmanager
def gpu_exclusive_vision_window(flag_ttl=300):
    if queue_manager._get_system_state('vision_in_progress'):
        raise GpuBusyError('a vision task is already running')
    if queue_manager._get_system_state('training_in_progress'):
        raise GpuBusyError('training is running')
    token = queue_manager._acquire_gpu_lease('vision', flag_ttl)
    if token is None:
        raise GpuBusyError('the GPU is already in use')
    queue_manager._set_system_state('vision_in_progress', token, ttl_seconds=flag_ttl)
    stop_renewal = threading.Event()
    lease_lost = threading.Event()
    app = current_app._get_current_object()

    def renew():
        interval = min(30.0, max(0.05, flag_ttl / 3))
        while not stop_renewal.wait(interval):
            try:
                with app.app_context():
                    if not queue_manager._renew_gpu_lease(token, flag_ttl):
                        lease_lost.set()
                        return
                    queue_manager._set_system_state(
                        'vision_in_progress', token, ttl_seconds=flag_ttl)
            except Exception:
                logger.exception('failed to renew GPU vision lease')
                lease_lost.set()
                return

    renewal = threading.Thread(target=renew, name='gpu-vision-lease', daemon=True)
    renewal.start()
    try:
        try:
            from .utils.comfyui import free_comfyui_vram
            free_comfyui_vram()
        except Exception:
            pass
        yield
    finally:
        stop_renewal.set()
        renewal.join(timeout=min(1.0, max(0.1, flag_ttl / 3)))
        # only clear the flag if we still own it (it may have expired and been re-acquired)
        if queue_manager._get_system_state('vision_in_progress') == token:
            queue_manager._set_system_state('vision_in_progress', None)
        queue_manager._release_gpu_lease(token)
        if lease_lost.is_set():
            logger.error('GPU vision lease ownership was lost before work completed')
