"""Resume existing E0 slots after a closed terminal, honoring runtime proxies.

All paid calls still go through development_e0.run_e0/send_once and its locks,
budget, retry, lineage and annotation logic. The original frozen inputs and
code remain intact. An explicit hashed execution revision records the changed
transport; a lost response is never replaced by a new sample.
"""
from __future__ import annotations
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import development_e0 as e
from development_provider import OpenAIProvider, redact

REVISION = 'configured_environment_proxy_v1'
RUN_ID = 'e0_20261116_gpt61_default_001'
LOST_ATTEMPT = 'conv_e0_20261116_gpt61_default_001_1f010a70a0d9427583e313c50c7094f0'


class ConfiguredProxyProvider(OpenAIProvider):
    """Same endpoint, headers, payload and retry policy; use configured proxy."""

    def send(self, body):
        request = urllib.request.Request(self.endpoint, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + os.environ[self.credential_env_var],
            'Content-Type': 'application/json'})
        started = time.monotonic()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        # Keep the environment's managed proxy in force. Never disable it or
        # redirect credentials to a different API host. One send, no retries.
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                result = {'http_status': response.status, 'raw_body': redact(response.read()),
                    'request_id': response.headers.get('x-request-id'),
                    'retry_after': response.headers.get('retry-after'), 'transport_error': None}
        except urllib.error.HTTPError as exc:
            result = {'http_status': exc.code, 'raw_body': redact(exc.read()),
                'request_id': exc.headers.get('x-request-id'),
                'retry_after': exc.headers.get('retry-after'), 'transport_error': None}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            result = {'http_status': None, 'raw_body': b'', 'request_id': None,
                'retry_after': None, 'transport_error': type(exc).__name__}
        result['elapsed_seconds'] = time.monotonic() - started
        result['transport_profile'] = REVISION
        return result


def close_lost_response(run, config, attempt_id):
    """Record a local interruption with upstream outcome and cost unknown.

    completed.json closes the coordinator's local dispatch, not the provider's
    job. No response.body or response.meta is fabricated; full reservation stays.
    """
    folder = run / 'attempts' / attempt_id
    start = e.read(folder / 'started.json')
    completed = folder / 'completed.json'
    if completed.exists():
        return e.read(completed)
    if (folder / 'response.body.txt').exists() or (folder / 'response.meta.json').exists():
        raise ValueError('Saved response evidence exists; recover it instead of declaring it lost')
    if start['kind'] != 'generation':
        raise ValueError('Only the explicitly identified interrupted generation is reconciled here')
    note = {
        'observed_at_utc': e.now(), 'kind': 'local_terminal_closed_response_not_saved',
        'source': 'User: powershell已经关上了', 'attempt_id': attempt_id,
        'provider_outcome_unknown': True, 'billing_unknown': True,
        'retry_allowed': False, 'raw_response_available': False,
        'reserved_cost_usd_retained': start['reserved_cost_usd'],
        'note': 'This is a local interruption observation, not a provider failure response.'}
    e.put(folder / 'local_interruption.json', note)
    out = dict(start, completed_at_utc=e.now(), status='unresolved_status', text='',
        provider_finish_reason=None, response_model=None, provider_response_id=None,
        usage=e.token_cost(config, {}), served_provider=None, system_fingerprint=None,
        immutable_weight_revision=None, elapsed_seconds=None, response_sha256=None,
        recovered_from_saved_response=False, provider_outcome_unknown=True,
        raw_response_available=False, completion_semantics='local_dispatch_closed_upstream_unknown',
        local_interruption_record='local_interruption.json')
    e.put(completed, out)
    e.journal(run / 'events.jsonl', dict(event='request_locally_closed_response_lost', **out))
    return out


def prepare_revision(run):
    config = e.read(run / 'config.json')
    if config['run_id'] != RUN_ID or config['provider'] != 'openai':
        raise ValueError('This recovery applies only to the existing interrupted official GPT E0')
    group = config['budget_group']
    with e.locked(e.RUNS / '_batches' / group['batch_id']), e.locked(run):
        base_hash = e.freeze(run, config)  # Every original frozen input/code hash still checked.
        source = Path(__file__).resolve()
        revision_dir = run / 'runtime_revisions' / REVISION
        target = revision_dir / 'revision.json'
        data = {
            'revision_id': REVISION, 'base_frozen_sha256': base_hash,
            'source_file': source.name, 'source_sha256': e.digest(source.read_bytes()),
            'reason': 'Work networking now supplies environment proxies; frozen transport disables those proxies.',
            'scope': 'Only HTTP transport uses the configured runtime proxy. Same registered endpoint, key variable, messages, model, sampling and max tokens.',
            'scientific_slots': 'Continue the original 15 slots; never regenerate the lost seed_k2 response.',
            'lost_attempt_id': LOST_ATTEMPT, 'user_report': 'powershell已经关上了',
            'raw_requests_and_original_frozen_files_preserved': True,
            'budget_cap_usd': group['hard_cap'], 'budget_expansion': False,
            'independent_review': False}
        if target.exists():
            old = e.read(target)
            for key, value in data.items():
                if old.get(key) != value:
                    raise ValueError('Registered execution revision differs: ' + key)
        else:
            e.safe_write_bytes(revision_dir / 'src' / source.name, source.read_bytes())
            e.put(target, dict(data, registered_at_utc=e.now()))
        if e.digest((revision_dir / 'src' / source.name).read_bytes()) != data['source_sha256']:
            raise ValueError('Saved transport revision source changed')
        close_lost_response(run, config, LOST_ATTEMPT)
    return target, base_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--limit', type=int, choices=(1,))
    args = parser.parse_args()
    run = e.run_path(RUN_ID)
    revision, base_hash = prepare_revision(run)
    if args.prepare_only:
        print(e.dumps({'status': 'recovery_prepared_no_api_sent', 'revision': str(revision)}), flush=True)
        return
    original_freeze = e.freeze

    def checked_revision(current_run, config):
        if original_freeze(current_run, config) != base_hash:
            raise ValueError('Base frozen run changed')
        registered = e.read(revision)
        if e.digest(Path(__file__).read_bytes()) != registered['source_sha256']:
            raise ValueError('Runtime revision source differs')
        return e.digest(revision.read_bytes())

    e.freeze = checked_revision
    e.OpenAIProvider = ConfiguredProxyProvider
    try:
        summary = e.run_e0(RUN_ID, limit=args.limit)
        print(e.dumps(summary), flush=True)
    finally:
        e.freeze = original_freeze
        e.OpenAIProvider = OpenAIProvider


if __name__ == '__main__':
    main()
