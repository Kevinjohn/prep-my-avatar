from datetime import datetime
import hashlib
import importlib.util
import io
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'render_lora.py'
SPEC = importlib.util.spec_from_file_location('render_lora', SCRIPT)
render = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(render)


def png_bytes():
    image = Image.new('RGB', (3, 2), color='navy')
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


class FakeTransport:
    def __init__(self, *, submit_error=None, statuses=None, result=None):
        self.submit_error = submit_error
        self.statuses = list(statuses or ['COMPLETED'])
        self.result = result or {
            'images': [{'url': 'https://images.example/result.png'}],
            'seed': 42,
        }
        self.calls = []

    def submit(self, url, payload, key):
        self.calls.append(('submit', url, payload, key))
        if self.submit_error:
            raise self.submit_error
        return {
            'request_id': 'request-1',
            'status_url': 'https://queue.fal.run/fal-ai/flux-lora/requests/request-1/status',
            'response_url': 'https://queue.fal.run/fal-ai/flux-lora/requests/request-1',
        }

    def status(self, url, key):
        self.calls.append(('status', url, key))
        return {'status': self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]}

    def response(self, url, key):
        self.calls.append(('response', url, key))
        return self.result

    def download(self, url):
        self.calls.append(('download', url))
        return png_bytes()


def make_recipe(tmp_path, *, prompt='portrait in a garden', adapter_bytes=b'fictional weights', **changes):
    adapter = tmp_path / 'adapter.safetensors'
    adapter.write_bytes(adapter_bytes)
    recipe = {
        'endpoint': 'fal-ai/flux-lora',
        'adapter': {
            'path': adapter.name,
            'sha256': hashlib.sha256(adapter_bytes).hexdigest(),
            'url': 'https://weights.example/fictional.safetensors',
        },
        'arguments': {
            'prompt': prompt,
            'seed': 42,
            'image_size': 'square_hd',
            'num_inference_steps': 28,
            'guidance_scale': 3.5,
            'output_format': 'png',
            'lora_scale': 1.0,
        },
    }
    recipe.update(changes)
    recipe_path = tmp_path / 'recipe.json'
    recipe_path.write_text(json.dumps(recipe), encoding='utf-8')
    return recipe_path, adapter


def execute(recipe_path, out_dir, transport, **kwargs):
    return render.run(recipe_path, out_dir, execute=True, transport=transport,
                      key='test-secret', **kwargs)


def test_prepare_is_offline_and_builds_one_lora_entry(tmp_path):
    recipe_path, adapter = make_recipe(tmp_path)
    transport = FakeTransport()

    summary = render.run(recipe_path, tmp_path / 'out', execute=False, transport=transport)

    assert transport.calls == []
    assert summary['endpoint'] == 'fal-ai/flux-lora'
    assert summary['adapter_sha256'] == hashlib.sha256(adapter.read_bytes()).hexdigest()
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('count', [1, 2, True])
def test_explicit_image_count_is_limited_to_one(tmp_path, count):
    recipe_path, _ = make_recipe(tmp_path)
    recipe = json.loads(recipe_path.read_text())
    recipe['arguments']['num_images'] = count
    recipe_path.write_text(json.dumps(recipe))
    if type(count) is int and count == 1:
        result = render.run(recipe_path, tmp_path / 'out')
        assert result['request']['num_images'] == 1
    else:
        with pytest.raises(render.RenderError, match='num_images must be 1'):
            render.run(recipe_path, tmp_path / 'out')


@pytest.mark.parametrize('wait_seconds', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_wait_duration_is_rejected(tmp_path, wait_seconds):
    with pytest.raises(render.RenderError, match='wait-seconds'):
        render.run(None, tmp_path / 'out', execute=False, wait_seconds=wait_seconds)


def test_unknown_post_outcome_never_resubmits_and_does_not_persist_key(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    transport = FakeTransport(submit_error=TimeoutError('socket timeout'))

    with pytest.raises(render.RenderError, match='outcome is unknown'):
        execute(recipe_path, out, transport)
    with pytest.raises(render.RenderError, match='unknown'):
        execute(recipe_path, out, FakeTransport())

    state = json.loads((out / 'run.json').read_text())
    assert state['status'] == 'submission_unknown'
    assert 'test-secret' not in (out / 'run.json').read_text()
    assert len([call for call in transport.calls if call[0] == 'submit']) == 1


def test_resumes_accepted_job_and_saves_verified_image(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    transport = FakeTransport(statuses=['IN_QUEUE', 'COMPLETED'])

    result = execute(recipe_path, out, transport, wait_seconds=2)

    assert result['status'] == 'completed'
    assert (out / 'result.png').is_file()
    assert [call[0] for call in transport.calls].count('submit') == 1
    assert transport.calls[0][2]['loras'] == [
        {'path': 'https://weights.example/fictional.safetensors', 'scale': 1.0}
    ]
    assert all(call[-1] == 'test-secret' for call in transport.calls if call[0] in {'submit', 'status', 'response'})


def test_completed_rerun_verifies_artifact_without_network(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    execute(recipe_path, out, FakeTransport())

    transport = FakeTransport()
    result = render.run(recipe_path, out, execute=True, transport=transport)

    assert result['status'] == 'completed'
    assert result['verified_sha256'] == hashlib.sha256((out / 'result.png').read_bytes()).hexdigest()
    assert transport.calls == []


def test_changed_recipe_and_adapter_hash_are_rejected_before_submission(tmp_path):
    recipe_path, adapter = make_recipe(tmp_path)
    execute(recipe_path, tmp_path / 'out', FakeTransport())
    recipe = json.loads(recipe_path.read_text())
    recipe['arguments']['prompt'] = 'different'
    recipe_path.write_text(json.dumps(recipe))
    transport = FakeTransport()

    with pytest.raises(render.RenderError, match='changed recipe'):
        execute(recipe_path, tmp_path / 'out', transport)
    assert transport.calls == []

    recipe['arguments']['prompt'] = 'portrait in a garden'
    recipe_path.write_text(json.dumps(recipe))
    adapter.write_bytes(b'tampered adapter')
    with pytest.raises(render.RenderError, match='SHA-256'):
        execute(recipe_path, tmp_path / 'new-out', transport)
    assert transport.calls == []


def test_invalid_queue_urls_are_rejected_without_sending_credentials(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)

    class BadURLTransport(FakeTransport):
        def submit(self, url, payload, key):
            self.calls.append(('submit', url, payload, key))
            return {
                'request_id': 'request-1',
                'status_url': 'https://evil.example/status',
                'response_url': 'https://queue.fal.run/result',
            }

    transport = BadURLTransport()
    with pytest.raises(render.RenderError, match='unknown'):
        execute(recipe_path, tmp_path / 'out', transport)
    assert json.loads((tmp_path / 'out' / 'run.json').read_text())['status'] == 'submission_unknown'
    assert [call[0] for call in transport.calls] == ['submit']


def test_http_transport_authenticates_only_queue_requests_and_blocks_redirects():
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    class Opener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout):
            self.requests.append(request)
            if request.full_url.endswith('.png'):
                return Response(png_bytes())
            return Response(b'{"status":"COMPLETED"}')

    transport = render.UrllibTransport()
    opener = Opener()
    transport.opener = opener
    queue = 'https://queue.fal.run/fal-ai/flux-lora/requests/id'
    transport.submit('https://queue.fal.run/fal-ai/flux-lora', {}, 'test-secret')
    transport.status(queue + '/status', 'test-secret')
    transport.response(queue, 'test-secret')
    transport.download('https://images.example/result.png')

    assert [request.full_url for request in opener.requests] == [
        'https://queue.fal.run/fal-ai/flux-lora', queue + '/status', queue,
        'https://images.example/result.png',
    ]
    assert all(request.get_header('Authorization') == 'Key test-secret'
               for request in opener.requests[:3])
    assert opener.requests[3].get_header('Authorization') is None
    with pytest.raises(render.urllib.error.HTTPError, match='redirect refused'):
        render._NoRedirect().redirect_request(
            render.urllib.request.Request('https://queue.fal.run/'), None,
            302, '', {}, 'https://evil.example',
        )


@pytest.mark.parametrize('url', [
    'https://evil.example/status',
    'https://queue.fal.run:not-a-port/status',
])
def test_direct_queue_transport_rejects_bad_url_before_adding_auth(url):
    class Opener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout):
            self.requests.append(request)
            raise AssertionError('network boundary should not be reached')

    transport = render.UrllibTransport()
    opener = Opener()
    transport.opener = opener

    with pytest.raises(render.RenderError, match='fal queue URLs'):
        transport.status(url, 'test-secret')

    assert opener.requests == []


@pytest.mark.parametrize('phase,expected_state', [
    ('status', 'accepted'),
    ('response', 'provider_completed'),
    ('download', 'provider_completed'),
])
def test_transient_network_error_resumes_same_job_without_resubmitting(
        tmp_path, phase, expected_state):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'

    class FlakyTransport(FakeTransport):
        def _fail(self):
            raise TimeoutError('request to https://queue.fal.run/?token=test-secret timed out')

        def status(self, url, key):
            if phase == 'status':
                self.calls.append(('status', url, key))
                self._fail()
            return super().status(url, key)

        def response(self, url, key):
            if phase == 'response':
                self.calls.append(('response', url, key))
                self._fail()
            return super().response(url, key)

        def download(self, url):
            if phase == 'download':
                self.calls.append(('download', url))
                self._fail()
            return super().download(url)

    first = FlakyTransport()
    with pytest.raises(render.RenderError) as failure:
        execute(recipe_path, out, first)
    assert 'https://' not in str(failure.value)
    assert 'test-secret' not in str(failure.value)
    state = json.loads((out / 'run.json').read_text())
    assert state['status'] == expected_state
    assert datetime.fromisoformat(state['updated_at']).utcoffset().total_seconds() == 0
    assert 'test-secret' not in (out / 'provider-error.json').read_text()

    retry = FakeTransport()
    result = render.run(None, out, execute=True, transport=retry, key='test-secret')

    assert result['status'] == 'completed'
    assert [call[0] for call in first.calls].count('submit') == 1
    assert [call[0] for call in retry.calls].count('submit') == 0


def test_pending_run_resumes_saved_job_without_recipe_or_second_submission(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    first_transport = FakeTransport(statuses=['IN_QUEUE'])
    assert execute(recipe_path, out, first_transport, wait_seconds=0)['status'] == 'pending'
    second_transport = FakeTransport(statuses=['COMPLETED'])

    result = render.run(None, out, execute=True, transport=second_transport, key='test-secret')

    assert result['status'] == 'completed'
    assert [call[0] for call in first_transport.calls].count('submit') == 1
    assert [call[0] for call in second_transport.calls].count('submit') == 0


def test_pending_timeout_and_failed_job_do_not_restart(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    pending = FakeTransport(statuses=['IN_QUEUE'])

    result = execute(recipe_path, out, pending, wait_seconds=0)
    assert result['status'] == 'pending'
    with pytest.raises(render.RenderError, match='failed'):
        execute(recipe_path, out, FakeTransport(statuses=['FAILED']))
    assert [call[0] for call in pending.calls].count('submit') == 1


def test_bad_image_or_seed_is_preserved_for_inspection(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    bad = FakeTransport(result={'images': [{'url': 'https://images.example/bad.png'}], 'seed': 42})
    bad.download = lambda url: b'not an image'

    with pytest.raises(render.RenderError, match='invalid image'):
        execute(recipe_path, out, bad)
    assert (out / 'result.png').read_bytes() == b'not an image'
    assert json.loads((out / 'run.json').read_text())['status'] == 'completed_unverified'
    retry = FakeTransport()
    with pytest.raises(render.RenderError, match='completed_unverified'):
        execute(recipe_path, out, retry)
    assert (out / 'result.png').read_bytes() == b'not an image'
    assert retry.calls == []


def test_seed_mismatch_is_not_marked_complete(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    bad = FakeTransport(result={'images': [{'url': 'https://images.example/bad.png'}], 'seed': 41})

    with pytest.raises(render.RenderError, match='invalid result'):
        execute(recipe_path, out, bad)
    assert not (out / 'result.png').exists()
    assert json.loads((out / 'run.json').read_text())['status'] == 'completed_unverified'


def test_transient_provider_response_body_is_saved_and_resumable(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'

    class ErrorResponseTransport(FakeTransport):
        def response(self, url, key):
            self.calls.append(('response', url, key))
            raise render._HTTPFailure(500, b'private provider detail')

    with pytest.raises(render.RenderError, match='resume the same run'):
        execute(recipe_path, out, ErrorResponseTransport())

    saved_error = json.loads((out / 'provider-error.json').read_text())
    assert saved_error['body'] == 'private provider detail'
    assert json.loads((out / 'run.json').read_text())['status'] == 'provider_completed'


def test_corrupt_completed_image_is_rejected_without_network(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    execute(recipe_path, out, FakeTransport())
    (out / 'result.png').write_bytes(b'changed')
    transport = FakeTransport()

    with pytest.raises(render.RenderError, match='missing or changed'):
        execute(recipe_path, out, transport)
    assert transport.calls == []


def test_concurrent_callers_submit_only_once(tmp_path):
    recipe_path, _ = make_recipe(tmp_path)
    out = tmp_path / 'out'
    transport = FakeTransport()
    original = transport.submit
    entered = threading.Event()
    release = threading.Event()

    def slow_submit(*args):
        entered.set()
        release.wait(2)
        return original(*args)

    transport.submit = slow_submit
    results = []
    first = threading.Thread(target=lambda: results.append(execute(recipe_path, out, transport)))
    second = threading.Thread(target=lambda: results.append(execute(recipe_path, out, transport)))
    first.start()
    assert entered.wait(1)
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(2)
    second.join(2)

    assert len(results) == 2
    assert [call[0] for call in transport.calls].count('submit') == 1
