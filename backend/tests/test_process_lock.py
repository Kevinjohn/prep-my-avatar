import os

import pytest


def test_process_lock_rejects_a_second_server_and_releases_on_close(tmp_path):
    from app.process_lock import AlreadyRunning, acquire

    first = acquire(tmp_path)
    try:
        with pytest.raises(AlreadyRunning, match='another Prep My Avatar server'):
            acquire(tmp_path)
        assert (tmp_path / 'server.lock').read_text(encoding='ascii').startswith('pid=')
        if os.name != 'nt':
            assert (tmp_path / 'server.lock').stat().st_mode & 0o777 == 0o600
    finally:
        first.close()

    second = acquire(tmp_path)
    second.close()
