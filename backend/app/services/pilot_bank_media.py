"""Bounded local media validation; no shell, URLs, or executable asset loading."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
import warnings

from PIL import Image

from .pilot_bank_storage import BankError, MAX_FILE_BYTES


def tools():
    return {'ffprobe': bool(shutil.which('ffprobe')), 'ffmpeg': bool(shutil.which('ffmpeg'))}


def run_local(args, timeout=30):
    # Drain both pipes concurrently, killing the tool as soon as either output
    # exceeds the cap. Neither RAM nor a temporary output file can grow without bound.
    try:
        with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) as process:
            def read_bounded(stream):
                data = bytearray()
                while chunk := stream.read(8192):
                    data.extend(chunk)
                    if len(data) > 65536:
                        process.kill()
                        return None
                return bytes(data)

            with ThreadPoolExecutor(max_workers=2) as readers:
                stdout = readers.submit(read_bounded, process.stdout)
                stderr = readers.submit(read_bounded, process.stderr)
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise BankError('Local media tool timed out') from None
                output, errors = stdout.result(), stderr.result()
                if process.returncode or output is None or errors is None:
                    raise BankError('Local media validation failed')
                return output
    except OSError:
        raise BankError('Local media tool failed') from None


def probe(path, sha256):
    executable = shutil.which('ffprobe')
    if not executable:
        return {'status': 'unverified', 'sha256': sha256,
                'no_audio_stream_verified': False, 'reason': 'ffprobe unavailable'}
    try:
        data = json.loads(run_local([
            executable, '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-format_whitelist', 'mov,matroska,webm',
            '-show_entries', 'stream=codec_type,codec_name,width,height:format=duration',
            '-of', 'json', str(path)]))
        streams = data['streams']
        if not any(s.get('codec_type') == 'video' for s in streams):
            raise BankError('Imported video has no valid video stream')
        duration = float(data.get('format', {}).get('duration', 0))
        if not math.isfinite(duration) or duration <= 0 or duration > 600:
            raise BankError('Video duration must be at most ten minutes')
    except (BankError, ValueError, KeyError, TypeError):
        return {'status': 'unverified', 'sha256': sha256,
                'no_audio_stream_verified': False,
                'reason': 'Local probe failed, timed out, or could not validate the video'}
    return {'status': 'verified', 'sha256': sha256, 'streams': streams,
            'duration_seconds': duration,
            'no_audio_stream_verified': not any(s.get('codec_type') == 'audio' for s in streams)}


def inspect(path, kind, sha256):
    if kind == 'image':
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.format not in ('PNG', 'JPEG', 'WEBP'):
                        raise BankError('Images must be PNG, JPEG, or WebP')
                    mime = Image.MIME[image.format]
                    if image.width * image.height > 40_000_000:
                        raise BankError('Image pixel limit exceeded')
                    image.verify()
                with Image.open(path) as image:
                    image.load()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise BankError('Invalid or oversized image') from None
        return mime, None
    if kind == 'video':
        with path.open('rb') as stream:
            header = stream.read(16)
        if len(header) >= 12 and header[4:8] == b'ftyp':
            mime = 'video/mp4'
        elif header.startswith(b'\x1a\x45\xdf\xa3'):
            mime = 'video/webm'
        else:
            raise BankError('Video must be a local MP4 or WebM container')
        return mime, probe(path, sha256)
    # Weights/config are opaque immutable attachments. Never deserialize them.
    return 'application/octet-stream', None


def make_silent(source, destination):
    executable = shutil.which('ffmpeg')
    if not executable:
        raise BankError('ffmpeg unavailable; install it locally to create a silent copy')
    run_local([executable, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe',
               '-format_whitelist', 'mov,matroska,webm', '-i', str(source),
               '-map', '0:v:0', '-c:v', 'copy', '-an', '-sn', '-dn',
               '-map_metadata', '-1', '-fs', str(MAX_FILE_BYTES), '-f', 'mp4',
               '-y', str(destination)], timeout=60)
