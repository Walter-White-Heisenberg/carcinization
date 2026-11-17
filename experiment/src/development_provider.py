"""Minimal official OpenAI REST adapter; one HTTP request, no hidden retries.

stdlib transport is intentional: SDK installation is unavailable in this host's
network sandbox. See docs/DEVELOPMENT_E0_CN.md for official API references.
Authorization headers and credentials are never returned to the coordinator.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

ENDPOINT = 'https://api.openai.com/v1/chat/completions'
PROVIDER_ENDPOINTS = {
    'openai': ENDPOINT,
    'moonshot': 'https://api.moonshot.ai/v1/chat/completions',
    'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
    # Matched to MODELHUB_CN_API_KEY in existing local invocation records;
    # never infer this destination from the shape of a secret token.
    'modelhub_cn': 'https://www.tokentym.com/v1/chat/completions',
}


def redact(raw: bytes) -> bytes:
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(x in name.upper() for x in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            raw = raw.replace(value.encode('utf-8'), b'[REDACTED]')
    return raw


class OpenAIProvider:
    endpoint = ENDPOINT

    def __init__(self, credential_env_var='OPENAI_API_KEY', timeout_seconds=180, endpoint=None):
        if not os.environ.get(credential_env_var):
            raise ValueError('Missing credential environment variable: ' + credential_env_var)
        self.credential_env_var = credential_env_var
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint or ENDPOINT
        if self.endpoint not in PROVIDER_ENDPOINTS.values():
            raise ValueError('Unregistered provider endpoint; do not send credentials to guessed gateways')

    def send(self, body: bytes):
        """Return the exact response body, except any accidentally echoed secrets.

        Transport ambiguity is never silently resent. HTTP transient errors are
        classified by the coordinator and receive separately registered attempts.
        """
        req = urllib.request.Request(self.endpoint, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + os.environ[self.credential_env_var],
            'Content-Type': 'application/json',
        })
        started = time.monotonic()
        try:
            # Disable environment proxies and redirects: credentials only reach
            # the frozen official endpoint, never a redirected host.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(req, timeout=self.timeout_seconds) as response:
                raw = response.read()
                result = {'http_status': response.status, 'raw_body': redact(raw),
                          'request_id': response.headers.get('x-request-id'),
                          'retry_after': response.headers.get('retry-after'), 'transport_error': None}
        except urllib.error.HTTPError as exc:
            result = {'http_status': exc.code, 'raw_body': redact(exc.read()),
                      'request_id': exc.headers.get('x-request-id'),
                      'retry_after': exc.headers.get('retry-after'), 'transport_error': None}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # Do not print exception messages which can contain proxy credentials.
            result = {'http_status': None, 'raw_body': b'', 'request_id': None,
                      'retry_after': None, 'transport_error': type(exc).__name__}
        result['elapsed_seconds'] = time.monotonic() - started
        return result


def classify_http(result):
    code = result['http_status']
    if result['transport_error']:
        return 'unresolved_status'
    if code == 200:
        return None
    try:
        error = json.loads(result['raw_body']).get('error', {})
        error_code = error.get('code')
    except (ValueError, AttributeError):
        error_code = None
    if error_code in {'insufficient_quota', 'billing_hard_limit_reached', 'invalid_api_key'}:
        return 'provider_terminal_error'
    if error_code in {'context_length_exceeded', 'max_tokens_exceeded'}:
        return 'context_overflow'
    if code in {408, 409, 429, 500, 502, 503, 504}:
        return 'transient_api_error'
    return 'provider_terminal_error'
