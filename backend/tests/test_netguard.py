"""Network guard: loopback untouched; remote access authenticated by default."""
REMOTE = {'REMOTE_ADDR': '192.168.1.50'}


def _require_token(client):
    """Turn the opt-in token gate ON (persists server.require_token in the tmp config)."""
    client.put('/api/settings', json={'config': {'server': {'require_token': True}}})


def test_loopback_client_needs_no_token(client):
    r = client.get('/api/health')            # default REMOTE_ADDR = 127.0.0.1
    assert r.status_code == 200


def test_remote_client_blocked_by_default_no_token(client):
    response = client.get('/api/health', environ_base=REMOTE)
    assert response.status_code == 403
    assert 'access token' in response.get_json()['error']


def test_remote_client_blocked_when_token_required_but_none_configured(client):
    _require_token(client)
    r = client.get('/api/health', environ_base=REMOTE)
    assert r.status_code == 403
    assert 'LDS_ACCESS_TOKEN' in r.get_json()['error']


def test_remote_client_blocked_with_wrong_token(app, monkeypatch):
    monkeypatch.setenv('LDS_ACCESS_TOKEN', 'sekret')
    c = app.test_client()
    c.put('/api/settings', json={'config': {'server': {'require_token': True}}})
    r = c.get('/api/health', environ_base=REMOTE,
              headers={'Authorization': 'Bearer nope'})
    assert r.status_code == 403


def test_remote_client_bearer_token_ok(app, monkeypatch):
    monkeypatch.setenv('LDS_ACCESS_TOKEN', 'sekret')
    c = app.test_client()
    c.put('/api/settings', json={'config': {'server': {'require_token': True}}})
    r = c.get('/api/health', environ_base=REMOTE,
              headers={'Authorization': 'Bearer sekret'})
    assert r.status_code == 200


def test_query_token_is_rejected(app, monkeypatch):
    monkeypatch.setenv('LDS_ACCESS_TOKEN', 'sekret')
    c = app.test_client()
    c.put('/api/settings', json={'config': {'server': {'require_token': True}}})
    assert c.get('/api/health?token=sekret', environ_base=REMOTE).status_code == 403


def test_remote_login_form_sets_session_without_token_in_url(app, monkeypatch):
    monkeypatch.setenv('LDS_ACCESS_TOKEN', 'sekret')
    c = app.test_client()
    page = c.get('/remote-login', environ_base=REMOTE)
    assert page.status_code == 200 and b'type="password"' in page.data
    login = c.post('/remote-login', data={'token': 'sekret'}, environ_base=REMOTE)
    assert login.status_code == 302 and login.headers['Location'].endswith('/')
    assert 'sekret' not in login.headers['Location']
    assert c.get('/api/health', environ_base=REMOTE).status_code == 200


def test_rotating_remote_token_revokes_existing_sessions(app, monkeypatch):
    monkeypatch.setenv('LDS_ACCESS_TOKEN', 'first-token')
    c = app.test_client()
    login = c.post('/remote-login', data={'token': 'first-token'}, environ_base=REMOTE)
    assert login.status_code == 302
    assert c.get('/api/health', environ_base=REMOTE).status_code == 200

    monkeypatch.setenv('LDS_ACCESS_TOKEN', 'second-token')
    assert c.get('/api/health', environ_base=REMOTE).status_code == 403
    assert c.get('/api/health', environ_base=REMOTE,
                 headers={'Authorization': 'Bearer second-token'}).status_code == 200


def test_remote_html_shell_redirects_to_login(app, monkeypatch):
    monkeypatch.setenv('LDS_ACCESS_TOKEN', 'sekret')
    c = app.test_client()
    response = c.get('/', environ_base=REMOTE, headers={'Accept': 'text/html'})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/remote-login')


def test_escape_hatch_env(app, monkeypatch):
    monkeypatch.setenv('LDS_ALLOW_UNAUTHENTICATED', '1')
    c = app.test_client()
    c.put('/api/settings', json={'config': {'server': {'require_token': True}}})
    assert c.get('/api/health', environ_base=REMOTE).status_code == 200
