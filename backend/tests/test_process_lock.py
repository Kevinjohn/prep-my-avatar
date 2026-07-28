import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_process_lock_rejects_a_second_server_and_releases_on_close(tmp_path):
    from app.process_lock import AlreadyRunning, acquire

    first = acquire(tmp_path)
    try:
        with pytest.raises(AlreadyRunning, match='another Prep My Avatar server'):
            acquire(tmp_path)
        if os.name != 'nt':
            assert (tmp_path / 'server.lock').stat().st_mode & 0o777 == 0o600
    finally:
        first.close()

    # Windows deliberately denies a second handle access while the byte is
    # locked. Verify the durable owner record after releasing that lock.
    assert (tmp_path / 'server.lock').read_text(encoding='ascii').startswith('pid=')
    second = acquire(tmp_path)
    second.close()


def test_process_lock_competes_across_processes_and_recovers_after_kill(tmp_path):
    backend = str(Path(__file__).resolve().parents[1])
    env = {**os.environ, 'PYTHONPATH': backend}
    holder_code = (
        "import sys; from pathlib import Path; from app.process_lock import acquire; "
        "lock=acquire(Path(sys.argv[1])); print('ready', flush=True); "
        "sys.stdin.read(); lock.close()"
    )
    contender_code = (
        "import sys; from pathlib import Path; "
        "from app.process_lock import acquire, AlreadyRunning; "
        "\ntry:\n lock=acquire(Path(sys.argv[1]))\n"
        "except AlreadyRunning:\n sys.exit(23)\n"
        "else:\n lock.close()\n"
    )
    holder = subprocess.Popen(
        [sys.executable, '-c', holder_code, str(tmp_path)], env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'ready'
        contender = subprocess.run(
            [sys.executable, '-c', contender_code, str(tmp_path)], env=env,
            check=False, timeout=10)
        assert contender.returncode == 23
        holder.kill()
        holder.wait(timeout=10)
        recovered = subprocess.run(
            [sys.executable, '-c', contender_code, str(tmp_path)], env=env,
            check=False, timeout=10)
        assert recovered.returncode == 0
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)
        if holder.stdin is not None:
            holder.stdin.close()
        if holder.stdout is not None:
            holder.stdout.close()


def test_direct_app_factory_fails_before_shared_state_mutation(tmp_path):
    backend = str(Path(__file__).resolve().parents[1])
    data_dir = tmp_path / 'factory-data'
    env = {**os.environ, 'PYTHONPATH': backend, 'LDS_DATA_DIR': str(data_dir),
           'LDS_CONFIG': str(tmp_path / 'config.json'),
           'LDS_ENV': str(tmp_path / '.env')}
    holder_code = (
        "import sys; from pathlib import Path; from app.process_lock import acquire; "
        "lock=acquire(Path(sys.argv[1])); print('ready', flush=True); "
        "sys.stdin.read(); lock.close()"
    )
    factory_code = (
        "from app import create_app; from app.process_lock import AlreadyRunning\n"
        "try:\n create_app()\n"
        "except AlreadyRunning:\n raise SystemExit(23)\n"
    )
    holder = subprocess.Popen(
        [sys.executable, '-c', holder_code, str(data_dir)], env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'ready'
        contender = subprocess.run(
            [sys.executable, '-c', factory_code], env=env,
            check=False, timeout=15)
        assert contender.returncode == 23
        assert not (data_dir / 'studio.db').exists()
        assert not (data_dir / 'app.log').exists()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)
        if holder.stdin is not None:
            holder.stdin.close()
        if holder.stdout is not None:
            holder.stdout.close()
