"""Prepare, submit, resume, and verify one private fal identity-LoRA render."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


ENDPOINTS = {'fal-ai/flux-lora', 'fal-ai/flux-krea-lora'}
HASH_RE = re.compile(r'^[0-9a-f]{64}$')
STATE_NAME = 'run.json'
IMAGE_NAME = 'result.png'


class RenderError(RuntimeError):
    """A concise, safe-to-display execution error."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect refused', headers, fp)


class UrllibTransport:
    """Small network boundary; authorization is attached only to queue calls."""

    def __init__(self, timeout: float = 30):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_NoRedirect())

    def _open(self, request: urllib.request.Request) -> bytes:
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise _HTTPFailure(exc.code, body) from None

    def _json(self, url: str, key: str, *, payload: dict | None = None) -> dict:
        url = _validate_queue_url(url)
        headers = {'Authorization': f'Key {key}', 'Accept': 'application/json'}
        data = None
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(payload).encode('utf-8')
        raw = self._open(urllib.request.Request(url, data=data, headers=headers))
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RenderError('fal returned invalid JSON') from exc
        if not isinstance(value, dict):
            raise RenderError('fal returned an invalid response')
        return value

    def submit(self, url: str, payload: dict, key: str) -> dict:
        return self._json(url, key, payload=payload)

    def status(self, url: str, key: str) -> dict:
        return self._json(url, key)

    def response(self, url: str, key: str) -> dict:
        return self._json(url, key)

    def download(self, url: str) -> bytes:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise RenderError('image URL must use HTTPS without embedded credentials')
        return self._open(urllib.request.Request(url, headers={'Accept': 'image/*'}))


class _HTTPFailure(RenderError):
    def __init__(self, status: int, body: bytes):
        super().__init__(f'fal request returned HTTP {status}')
        self.status = status
        self.body = body


def _private_mode(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    data = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _private_mode(temporary, 0o600)
        os.replace(temporary, path)
        _private_mode(path, 0o600)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


@contextlib.contextmanager
def _run_lock(out_dir: Path):
    lock_path = out_dir / '.lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    _private_mode(lock_path, 0o600)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            with contextlib.suppress(OSError):
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_recipe(path: Path) -> tuple[dict, dict, str]:
    try:
        recipe = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RenderError('recipe could not be read as JSON') from exc
    if not isinstance(recipe, dict) or recipe.get('endpoint') not in ENDPOINTS:
        raise RenderError('recipe endpoint must be fal-ai/flux-lora or fal-ai/flux-krea-lora')
    adapter = recipe.get('adapter')
    args = recipe.get('arguments')
    if not isinstance(adapter, dict) or not isinstance(args, dict):
        raise RenderError('recipe must include adapter and arguments objects')
    if set(recipe) != {'endpoint', 'adapter', 'arguments'} or set(adapter) != {'path', 'sha256', 'url'}:
        raise RenderError('recipe contains unsupported fields')
    adapter_path = Path(str(adapter.get('path', '')))
    if not adapter_path.is_absolute():
        adapter_path = path.parent / adapter_path
    declared_hash = adapter.get('sha256')
    if not isinstance(declared_hash, str) or HASH_RE.fullmatch(declared_hash) is None:
        raise RenderError('adapter.sha256 must be a lowercase 64-character SHA-256')
    adapter_url = adapter.get('url')
    _validate_https_url(adapter_url, 'adapter URL')
    required = {
        'prompt': str,
        'seed': int,
        'image_size': str,
        'num_inference_steps': int,
        'guidance_scale': (int, float),
        'output_format': str,
        'lora_scale': (int, float),
    }
    for field, expected in required.items():
        value = args.get(field)
        if isinstance(value, bool) or not isinstance(value, expected):
            raise RenderError(f'arguments.{field} has an invalid value')
    if set(args) - {'num_images'} != set(required):
        raise RenderError('recipe contains unsupported argument fields')
    if type(args.get('num_images', 1)) is not int or args.get('num_images', 1) != 1:
        raise RenderError('arguments.num_images must be 1')
    if not args['prompt'].strip() or args['seed'] < 0 or args['num_inference_steps'] < 1:
        raise RenderError('prompt, seed, or inference steps are outside the supported range')
    if not args['image_size'].strip():
        raise RenderError('arguments.image_size cannot be empty')
    if args['output_format'] != 'png':
        raise RenderError("arguments.output_format must be 'png'")
    if not 0 <= args['lora_scale'] <= 4 or not 0 <= args['guidance_scale'] <= 30:
        raise RenderError('guidance_scale or lora_scale is outside the supported range')
    normalized = {
        'endpoint': recipe['endpoint'],
        'adapter_sha256': declared_hash,
        'adapter_url': adapter_url,
        'arguments': args,
        'recipe_sha256': hashlib.sha256(
            json.dumps(recipe, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        ).hexdigest(),
    }
    request = {field: value for field, value in args.items() if field != 'lora_scale'}
    request['num_images'] = 1
    request['loras'] = [{'path': adapter_url, 'scale': args['lora_scale']}]
    return normalized, request, str(adapter_path)


def _validate_https_url(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise RenderError(f'{label} must be an HTTPS URL')
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        username, password = parsed.username, parsed.password
    except ValueError as exc:
        raise RenderError(f'{label} must be a valid HTTPS URL') from exc
    if parsed.scheme != 'https' or not hostname or username or password:
        raise RenderError(f'{label} must be HTTPS without embedded credentials')
    return value


def _validate_queue_url(value: Any) -> str:
    url = _validate_https_url(value, 'fal queue URL')
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise RenderError('fal queue URLs must use https://queue.fal.run') from exc
    if hostname != 'queue.fal.run' or port not in (None, 443):
        raise RenderError('fal queue URLs must use https://queue.fal.run')
    return url


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RenderError('saved run record is unreadable; preserve it for recovery') from exc
    if not isinstance(state, dict):
        raise RenderError('saved run record is invalid')
    return state


def _save_error(out_dir: Path, body: Any, key: str | None = None) -> None:
    if isinstance(body, bytes):
        payload = body.decode('utf-8', errors='replace')
    elif isinstance(body, str):
        payload = body
    else:
        payload = json.dumps(body, sort_keys=True, ensure_ascii=False)
    if key:
        payload = payload.replace(key, '[redacted]')
    _atomic_json(out_dir / 'provider-error.json', {'body': payload})


def _image_is_valid(path: Path) -> None:
    try:
        with Image.open(path) as image:
            if image.format != 'PNG' or image.width < 1 or image.height < 1:
                raise RenderError('collected artifact is not a valid PNG image')
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise RenderError('collected artifact is not a valid PNG image') from exc


def _completed_result(state: dict, image_path: Path) -> dict:
    if state['status'] != 'completed':
        raise RenderError(f"saved run is {state['status']}; it will not be restarted")
    if not image_path.is_file() or _digest_file(image_path) != state.get('image_sha256'):
        raise RenderError('completed image is missing or changed; it will not be resubmitted')
    _image_is_valid(image_path)
    return {'status': 'completed', 'verified_sha256': state['image_sha256']}


def _state_write(path: Path, state: dict) -> None:
    state.setdefault('created_at', datetime.now(timezone.utc).isoformat())
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    _atomic_json(path, state)


def _record_retryable_error(state_path: Path, state: dict, out_dir: Path,
                            exc: Exception, key: str | None) -> None:
    body = exc.body if isinstance(exc, _HTTPFailure) else str(exc)
    _save_error(out_dir, body, key)
    _state_write(state_path, state)


def _record_unverified(state_path: Path, state: dict, out_dir: Path,
                       detail: str | bytes, key: str | None) -> None:
    state['status'] = 'completed_unverified'
    _state_write(state_path, state)
    _save_error(out_dir, detail, key)


def _is_retryable_transport_error(exc: Exception) -> bool:
    return isinstance(exc, (
        _HTTPFailure, urllib.error.URLError, TimeoutError, ConnectionError, OSError,
    ))


def _submit_url(endpoint: str) -> str:
    return f'https://queue.fal.run/{endpoint}'


def _is_pending(status: str) -> bool:
    return status in {'IN_QUEUE', 'IN_PROGRESS', 'PENDING', 'RUNNING'}


def run(recipe_path: Path | None, out_dir: Path, *, execute: bool = False,
        wait_seconds: float = 180, transport=None, key: str | None = None) -> dict:
    if not math.isfinite(wait_seconds) or wait_seconds < 0 or wait_seconds > 3600:
        raise RenderError('--wait-seconds must be between 0 and 3600')
    if recipe_path is not None:
        normalized, request, adapter_path = _read_recipe(Path(recipe_path))
        if not Path(adapter_path).is_file():
            raise RenderError('local adapter file does not exist')
        adapter_hash = _digest_file(Path(adapter_path))
        if adapter_hash != normalized['adapter_sha256']:
            raise RenderError('local adapter SHA-256 does not match recipe')
    else:
        normalized = request = None
        adapter_path = None
    if not execute:
        if normalized is None:
            raise RenderError('a recipe is required for offline preparation')
        return {
            'endpoint': normalized['endpoint'],
            'adapter_sha256': normalized['adapter_sha256'],
            'request': request,
        }
    transport = transport or UrllibTransport()
    out_dir = Path(out_dir)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_mode(out_dir, 0o700)
    state_path, image_path = out_dir / STATE_NAME, out_dir / IMAGE_NAME

    with _run_lock(out_dir):
        state = _load_state(state_path)
        if state is not None:
            if normalized is not None and state.get('intent') != normalized:
                raise RenderError('saved run conflicts with changed recipe; use a new output directory')
            if state.get('status') == 'submitting':
                state['status'] = 'submission_unknown'
                _state_write(state_path, state)
            if state.get('status') == 'submission_unknown':
                raise RenderError('submission outcome is unknown; inspect fal before taking manual action')
            if state.get('status') in {'rejected', 'failed', 'cancelled', 'completed_unverified'}:
                raise RenderError(f"saved run is {state['status']}; it will not be restarted")
            if state.get('status') == 'completed':
                return _completed_result(state, image_path)
        else:
            if normalized is None:
                raise RenderError('a recipe is required when no saved run exists')
            if not key:
                raise RenderError('set FAL_KEY in the environment to execute or resume a render')
            if image_path.exists():
                raise RenderError('output directory already contains an image without a run record')
            state = {
                'schema_version': 1,
                'intent': normalized,
                'request': request,
                'status': 'submitting',
            }
            _state_write(state_path, state)
            try:
                accepted = transport.submit(_submit_url(normalized['endpoint']), request, key)
            except _HTTPFailure as exc:
                _save_error(out_dir, exc.body, key)
                state['status'] = 'rejected' if 400 <= exc.status < 500 else 'submission_unknown'
                _state_write(state_path, state)
                if state['status'] == 'rejected':
                    raise RenderError(f'fal rejected submission with HTTP {exc.status}; details saved privately') from None
                raise RenderError('submission outcome is unknown; inspect fal before taking manual action') from None
            except Exception as exc:
                _save_error(out_dir, str(exc), key)
                state['status'] = 'submission_unknown'
                _state_write(state_path, state)
                raise RenderError('submission outcome is unknown; inspect fal before taking manual action') from None
            try:
                if not isinstance(accepted, dict) or not accepted.get('request_id'):
                    raise RenderError('fal acceptance response was incomplete')
                state['request_id'] = accepted['request_id']
                state['status_url'] = _validate_queue_url(accepted.get('status_url'))
                state['response_url'] = _validate_queue_url(accepted.get('response_url'))
                state['status'] = 'accepted'
                _state_write(state_path, state)
            except Exception as exc:
                _save_error(out_dir, str(exc), key)
                state['status'] = 'submission_unknown'
                _state_write(state_path, state)
                raise RenderError('submission outcome is unknown; inspect fal before taking manual action') from None

            if state['status'] not in {'accepted', 'pending'}:
                raise RenderError(f"saved run is {state['status']}; it will not be restarted")
        if not key:
            raise RenderError('set FAL_KEY in the environment to execute or resume a render')
        state['status_url'] = _validate_queue_url(state.get('status_url'))
        state['response_url'] = _validate_queue_url(state.get('response_url'))
        deadline = time.monotonic() + wait_seconds
        while True:
            if time.monotonic() >= deadline:
                state['status'] = 'pending'
                _state_write(state_path, state)
                return {'status': 'pending', 'request_id': state['request_id']}
            try:
                status_result = transport.status(state['status_url'], key)
            except Exception as exc:
                _record_retryable_error(state_path, state, out_dir, exc, key)
                raise RenderError('fal status request failed; saved job remains resumable') from None
            if not isinstance(status_result, dict) or not isinstance(status_result.get('status'), str):
                _record_retryable_error(
                    state_path, state, out_dir,
                    RenderError('fal returned an invalid status response'), key,
                )
                raise RenderError('fal status response was invalid; saved job remains resumable')
            provider_status = str(status_result.get('status', '')).upper()
            state['provider_status'] = provider_status
            if _is_pending(provider_status):
                state['status'] = 'pending'
                _state_write(state_path, state)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {'status': 'pending', 'request_id': state['request_id']}
                time.sleep(min(1, remaining))
                continue
            if provider_status in {'FAILED', 'CANCELLED'}:
                state['status'] = provider_status.lower()
                _state_write(state_path, state)
                _save_error(out_dir, status_result, key)
                raise RenderError(f"fal job {provider_status.lower()}; details saved privately")
            if provider_status != 'COMPLETED':
                state['status'] = 'pending'
                _state_write(state_path, state)
                return {'status': 'pending', 'request_id': state['request_id']}
            state['status'] = 'provider_completed'
            _state_write(state_path, state)
            break

        try:
            response = transport.response(state['response_url'], key)
        except Exception as exc:
            if _is_retryable_transport_error(exc):
                _record_retryable_error(state_path, state, out_dir, exc, key)
                raise RenderError('fal job completed but result retrieval failed; resume the same run') from None
            _record_unverified(state_path, state, out_dir, str(exc), key)
            raise RenderError('fal returned an unreadable result; details saved privately') from None
        try:
            expected_seed = state['intent']['arguments']['seed']
            if not isinstance(response, dict):
                raise RenderError('fal returned an invalid result document')
            if response.get('seed') != expected_seed:
                raise RenderError('fal returned a seed that does not match the recipe')
            images = response.get('images')
            if not isinstance(images, list) or not images or not isinstance(images[0], dict):
                raise RenderError('fal response did not include an image')
            image_url = _validate_https_url(images[0].get('url'), 'image URL')
        except Exception as exc:
            _record_unverified(state_path, state, out_dir, str(exc), key)
            raise RenderError('fal returned an invalid result; details saved privately') from None
        if not image_path.exists():
            try:
                artifact = transport.download(image_url)
            except Exception as exc:
                if _is_retryable_transport_error(exc):
                    _record_retryable_error(state_path, state, out_dir, exc, key)
                    raise RenderError('fal image download failed; resume the same run') from None
                _record_unverified(state_path, state, out_dir, str(exc), key)
                raise RenderError('fal returned an unreadable image; details saved privately') from None
            temporary_image = image_path.with_suffix(image_path.suffix + '.tmp')
            try:
                fd = os.open(temporary_image, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(artifact)
                    stream.flush()
                    os.fsync(stream.fileno())
                _private_mode(temporary_image, 0o600)
                os.replace(temporary_image, image_path)
                _private_mode(image_path, 0o600)
            except OSError as exc:
                with contextlib.suppress(FileNotFoundError):
                    temporary_image.unlink()
                _record_retryable_error(state_path, state, out_dir, exc, key)
                raise RenderError('could not save fal image; resume the same run') from None
        try:
            _image_is_valid(image_path)
        except RenderError as exc:
            _record_unverified(state_path, state, out_dir, str(exc), key)
            raise RenderError('fal returned an invalid image; raw artifact preserved for inspection') from None
        state['status'] = 'completed'
        state['image_sha256'] = _digest_file(image_path)
        state['returned_seed'] = response['seed']
        _state_write(state_path, state)
        return {'status': 'completed', 'verified_sha256': state['image_sha256']}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', nargs='?', type=Path, help='private JSON recipe; omit to resume --out')
    parser.add_argument('--out', required=True, type=Path, help='private run directory')
    parser.add_argument('--execute', action='store_true', help='submit or resume the fal queue job')
    parser.add_argument('--wait-seconds', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        result = run(args.recipe, args.out, execute=args.execute,
                     wait_seconds=args.wait_seconds, key=os.environ.get('FAL_KEY'))
    except RenderError as exc:
        print(f'render-lora: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
