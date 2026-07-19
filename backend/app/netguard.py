"""Network access guard for non-loopback binds.

The app has NO user accounts (single local user by design): every route can read
API keys, launch GPU trainings or delete datasets. That is fine on 127.0.0.1 —
but `server.host` is configurable, and binding 0.0.0.0 (e.g. to reach the app
from a phone) would otherwise expose everything to the whole LAN.

Rule: requests from loopback clients are always allowed (the normal local flow,
untouched). Non-loopback clients require a token by default; `run.py` generates
one when the LAN bind starts. A dedicated login form converts it into a signed
session cookie, so credentials never appear in URLs, browser history, QR codes,
referrer headers or proxy logs.
Token sources, in order:
  - `Authorization: Bearer <token>` header
  - `X-LDS-Token: <token>` header

Escape hatch for setups with their own network isolation (VPN, reverse proxy
with auth, trusted Docker network): `LDS_ALLOW_UNAUTHENTICATED=1`.
"""
from __future__ import annotations
import ipaddress
import hashlib
import hmac
import os
import secrets

from flask import jsonify, redirect, render_template_string, request, session

SESSION_FLAG = 'lds_token_ok'


def _is_loopback(addr: str | None) -> bool:
    if not addr:
        # No REMOTE_ADDR (unit tests, some WSGI shims): treat as local rather
        # than locking the single-user app out of itself.
        return True
    try:
        return ipaddress.ip_address(addr.split('%')[0]).is_loopback
    except ValueError:
        return False


def _presented_token() -> str | None:
    auth = request.headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return request.headers.get('X-LDS-Token')


_LOGIN_HTML = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Prep My Avatar · Remote access</title>
<style>body{font:16px system-ui;background:#111827;color:#e5e7eb;display:grid;place-items:center;min-height:100vh;margin:0}main{width:min(26rem,calc(100% - 2rem));padding:1.5rem;border:1px solid #374151;border-radius:.75rem;background:#1f2937}label,input,button{display:block;width:100%;box-sizing:border-box}input{margin:.5rem 0 1rem;padding:.7rem;border:1px solid #4b5563;border-radius:.4rem;background:#111827;color:white}button{padding:.7rem;border:0;border-radius:.4rem;background:#6366f1;color:white;font-weight:700}.error{color:#fca5a5}</style>
</head><body><main><h1>Remote access</h1><p>Enter the access token shown in Settings on the host computer.</p>
{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
<form method="post" action="/remote-login"><label for="token">Access token</label>
<input id="token" name="token" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Open Prep My Avatar</button></form></main></body></html>'''


def install_network_guard(app):
    def configured_token():
        from . import config as cfg
        return (os.environ.get('LDS_ACCESS_TOKEN') or app.config.get('LDS_ACCESS_TOKEN')
                or cfg.get('server.access_token'))

    def token_fingerprint(token):
        key = str(app.secret_key).encode('utf-8')
        return hmac.new(key, str(token).encode('utf-8'), hashlib.sha256).hexdigest()

    def remote_login():
        if request.method == 'GET':
            return render_template_string(_LOGIN_HTML, error=None)
        expected = configured_token()
        presented = request.form.get('token', '')
        if expected and secrets.compare_digest(str(presented), str(expected)):
            session.clear()
            session[SESSION_FLAG] = token_fingerprint(expected)
            return redirect('/')
        return render_template_string(
            _LOGIN_HTML, error='Invalid access token.'), 403

    app.add_url_rule('/remote-login', 'remote_login', remote_login,
                     methods=('GET', 'POST'))
    # The access token itself authenticates this pre-session POST; requiring an
    # unrelated CSRF session token would make first login impossible.
    from .extensions import csrf
    csrf.exempt(remote_login)

    @app.before_request
    def _network_guard():
        if _is_loopback(request.remote_addr):
            return None
        if os.environ.get('LDS_ALLOW_UNAUTHENTICATED') == '1':
            return None
        if request.path == '/remote-login':
            return None
        # Read lazily so the Settings opt-out takes effect on the next request.
        from . import config as cfg
        if not cfg.get('server.require_token'):
            return None
        # config.server.access_token is read here too (not only the boot-time env)
        # so turning the gate on with a saved token works LIVE — no restart, unlike
        # the bind change. run.py still seeds the env token at boot for the custom
        # WSGI path that never writes config.
        token = configured_token()
        if not token:
            # Non-loopback client but no token configured (custom WSGI launch that
            # bypassed run.py): fail CLOSED with an actionable message.
            return jsonify({'error': 'remote access requires an access token — '
                                     'set LDS_ACCESS_TOKEN (see README) or bind 127.0.0.1'}), 403
        authenticated = session.get(SESSION_FLAG)
        expected_fingerprint = token_fingerprint(token)
        if isinstance(authenticated, str) and secrets.compare_digest(
                authenticated, expected_fingerprint):
            return None
        session.pop(SESSION_FLAG, None)
        presented = _presented_token()
        if presented and secrets.compare_digest(str(presented), str(token)):
            session[SESSION_FLAG] = expected_fingerprint
            return None
        if request.method == 'GET' and request.path == '/' \
                and 'text/html' in request.headers.get('Accept', ''):
            return redirect('/remote-login')
        return jsonify({'error': 'invalid or missing access token'}), 403
