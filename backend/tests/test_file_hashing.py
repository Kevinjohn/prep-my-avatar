import hashlib
import io
from pathlib import Path

from app.utils.file_hashing import sha256_file


def test_sha256_file_streams_in_one_mib_chunks(monkeypatch):
    content = (b'a' * (1024 * 1024)) + b'remainder'

    class TrackingFile(io.BytesIO):
        def __init__(self, data):
            super().__init__(data)
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return super().read(size)

    handle = TrackingFile(content)
    monkeypatch.setattr(Path, 'open', lambda self, mode: handle)

    assert sha256_file('checkpoint.safetensors') == hashlib.sha256(content).hexdigest()
    assert handle.read_sizes == [1024 * 1024, 1024 * 1024, 1024 * 1024]
