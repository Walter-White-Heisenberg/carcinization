"""E0 development ONLY: prepare, execute, recover, measure and report.

Formal pilot activation and its scientific checks are untouched. This entry
reuses the catalog renderer, generation lineage, execution audit, parser,
distance formulas and safe atomic workspace writes from the active protocol.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import msvcrt
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from pathlib import Path

from development_provider import OpenAIProvider, PROVIDER_ENDPOINTS, classify_http, redact
from execution_audit import assert_next_attempt, validate_execution_history
from generation_contracts import _render_catalog_slots
from reference_metrics import (body_roles, contraction, extra_contraction,
    mean_pairwise_edit, normalized_edit, parse_markdown_blocks, render_prompt)
from safe_files import safe_write_bytes, safe_write_text
from spec_data import PROMPTS as CATALOG_PROMPTS
from v2_validation import assert_generation_lineage, strict_json_loads

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / 'experiment'
RUNS = EXP / 'runs' / 'development'
PROMPTS = ('P00R', 'P01', 'P00E', 'P09', 'P27')
FREEZE_CODE = ('development_e0.py', 'development_provider.py', 'reference_metrics.py',
    'generation_contracts.py', 'execution_audit.py', 'v2_validation.py',
    'safe_files.py', 'spec_data.py', 'launch_e0_pair.py', 'prepare_e0_default_pair.py')
BASE = {'schema_version': '2.3', 'namespace': 'CONVERGENCE',
    'study_id': 'conv_review_trajectory', 'evidence_class': 'diagnostic_only',
    'fixture': False, 'illustrative': False, 'data_origin': 'real',
    'label_source': 'provider_generation_status_and_P27_automatic',
    'rubric_version': 'CONV-v2.3-E0-development-v1'}

# Explicit provider IDs requested by the user on 2026-11-16. The published APIs
# expose aliases, not immutable weight revisions; record that limitation rather
# than inventing a dated snapshot or silently using the old GPT-5.1 profile.
DEFAULT_MODELS = {
    ('openai', 'gpt-6.1-sol'): {'reasoning_effort': 'medium',
        'source': 'https://developers.openai.com/api/docs/models/gpt-6.1-sol'},
    ('moonshot', 'kimi-k3.1-pro'): {'reasoning_effort': 'max',
        'source': 'https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart'},
    ('openrouter', 'moonshotai/kimi-k3.1-pro'): {'reasoning_effort': 'provider_default_unverified_until_catalog_read',
        'source': 'https://openrouter.ai/moonshotai/kimi-k3.1-pro'},
    ('modelhub_cn', 'kimi-k3.1-pro'): {'reasoning_effort': 'gateway_default_not_independently_exposed',
        'source': 'account /v1/models and gateway configuration required'},
    ('modelhub_cn', 'gpt-6.1-sol'): {'reasoning_effort': 'gateway_default_not_independently_exposed',
        'source': 'account /v1/models and gateway configuration required'},
}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def put(path, obj):
    safe_write_text(path, dumps(obj))


def read(path):
    return strict_json_loads(Path(path).read_text(encoding='utf-8-sig'))


def lines(path):
    if not path.exists():
        return []
    return [strict_json_loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]


def journal(path, row):
    # Only used while holding the OS lock. Atomic complete replacement means a
    # crash cannot leave a partially written JSONL tail.
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    safe_write_text(path, old + json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def run_path(run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise ValueError('run_id must contain only letters, digits, underscores and hyphens')
    return RUNS / run_id


@contextmanager
def locked(run):
    run.mkdir(parents=True, exist_ok=True)
    lockpath = run / 'coordinator.lock'
    # An OS-held byte-range lock releases automatically on process death.
    with lockpath.open('a+b') as stream:
        if lockpath.stat().st_size == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError('Another coordinator holds this run lock') from None
        try:
            yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def schedule():
    slots = [{'slot_id': f'seed_k{k}', 'trajectory_id': k, 'round': 0,
              'condition': 'A_LOOP'} for k in range(1, 4)]
    for t in (1, 2):
        for k in range(1, 4):
            # Alternate which condition goes first, before seeing any output.
            groups = ('A_LOOP', 'A_INDEPENDENT') if (t + k) % 2 == 0 else ('A_INDEPENDENT', 'A_LOOP')
            for group in groups:
                slots.append({'slot_id': f'{group}_k{k}_t{t}', 'trajectory_id': k,
                              'round': t, 'condition': group})
    return slots


def proposed_config(run_id):
    return {
        'run_id': run_id, 'stage': 'E0', 'profile': 'carcinization_development_v1',
        'evidence_class': 'diagnostic_only', 'paper_split': 'development',
        'paper_id': None, 'paper_source': None, 'model_snapshot': None,
        'provider': 'openai', 'credential_env_var': 'OPENAI_API_KEY',
        'endpoint': OpenAIProvider.endpoint, 'trajectories': 3, 'updates': 2,
        'planned_generation_slots': 15, 'generation_prompt': 'P01',
        'conditions': ['A_LOOP', 'A_INDEPENDENT'],
        'sampling': {'temperature': 1.0, 'top_p': 1.0, 'max_completion_tokens': 4096,
                     'reasoning_effort': 'none', 'n': 1, 'stream': False, 'store': False,
                     'service_tier': 'default'},
        'evaluation_sampling': {'temperature': 0.0, 'top_p': 1.0,
                     'max_completion_tokens': 4096, 'reasoning_effort': 'none',
                     'n': 1, 'stream': False, 'store': False, 'service_tier': 'default'},
        'evaluation_model': 'same_fixed_model_as_generation',
        'annotation': {'method': 'P00E+P09', 'batch_size': 20, 'neighbor_context': 2,
                       'format_relabels': 1, 'human_verified': False},
        'budget': {'currency': None, 'hard_cap': None,
                   'input_per_million': None, 'cached_input_per_million': None,
                   'output_per_million': None, 'pricing_source': None,
                   'verified_at_utc': None},
        'authorization': {'user_instruction': None, 'recorded_at_utc': None},
        'generation_retry_limit': 2, 'timeout_seconds': 180,
        'pilot_outputs': False, 'human_primary_endpoint_claim': False,
        'confirmatory_claim': False, 'full_pilot_activation_applies': False,
        'recommendation_only': {'paper': 'Attention Is All You Need, arXiv:1706.03762v1',
            'paper_url': 'https://arxiv.org/abs/1706.03762v1',
            'model_snapshot': 'gpt-5.1-2025-11-13', 'currency': 'USD', 'hard_cap': 5.0,
            'rationale': 'Matches the available OPENAI_AUDIT_MODEL family; E0 checks engineering only.',
            'paper_exposure': 'Well-known public paper; no claim of training-data independence.'},
    }


def prepare(run_id):
    run = run_path(run_id)
    with locked(run):
        if (run / 'config.json').exists():
            raise ValueError('Existing run: inspect it or resume; do not overwrite')
        config = proposed_config(run_id)
        put(run / 'config.json', config)
        put(run / 'planned_slots.json', schedule())
        put(run / 'preparation.json', {'status': 'awaiting_paper_model_budget_and_network',
            'prepared_at_utc': now(), 'actual_api_attempts': 0, 'paid_calls': 0,
            'paper_model_budget_authorized': False,
            'observed_blockers': ['No development paper in project',
                'No project model snapshot authorization', 'No budget currency or amount authorization',
                'Host DNS resolution failed for api.openai.com/arxiv.org/pypi.org (11001)'],
            'python_executable': sys.executable,
            'credential_environment_names_present': [x for x in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY') if os.getenv(x)],
            'offline_only': True})
        report(run)
    return run


def validate_config(config, run):
    if config.get('stage') != 'E0' or config.get('profile') != 'carcinization_development_v1':
        raise ValueError('This entry only supports E0 development')
    if (config.get('trajectories'), config.get('updates'), config.get('planned_generation_slots')) != (3, 2, 15):
        raise ValueError('E0 requires 3 trajectories, 2 updates, 15 slots')
    if config.get('conditions') != ['A_LOOP', 'A_INDEPENDENT'] or config.get('generation_prompt') != 'P01':
        raise ValueError('E0 conditions or prompt changed')
    if config.get('pilot_outputs') is not False or config.get('human_primary_endpoint_claim') is not False:
        raise ValueError('Development entry cannot claim pilot or human evidence')
    if config.get('endpoint') != PROVIDER_ENDPOINTS.get(config.get('provider')):
        raise ValueError('Provider and registered endpoint do not match')
    if not config.get('paper_id') or not config.get('model_snapshot'):
        raise ValueError('Actual paper and exact model snapshot are required')
    is_default = config.get('inference_profile') == 'provider_default_v1'
    if is_default:
        if (config['provider'], config['model_snapshot']) not in DEFAULT_MODELS:
            raise ValueError('Unregistered provider-default model mapping')
        if config.get('model_revision_precision') != 'published_alias_immutable_revision_not_exposed':
            raise ValueError('Record the real alias/version precision; never invent an immutable revision')
        if not config.get('default_settings_source'):
            raise ValueError('Record the source of model default settings')
        if config['provider'] == 'modelhub_cn':
            catalog = run / 'inputs/provider_catalog.json'
            if not catalog.exists() or not any(x.get('id') == config['model_snapshot'] for x in read(catalog).get('data', [])):
                raise ValueError('Gateway model ID must be verified in its actual account model catalog')
    elif config['provider'] != 'openai' or not re.fullmatch(r'gpt-(?:5\.1|4\.1)-\d{4}-\d{2}-\d{2}', config['model_snapshot']):
        raise ValueError('Use a dated legacy snapshot or an explicitly registered provider-default profile')
    auth = config.get('authorization', {})
    if not auth.get('user_instruction') or not auth.get('recorded_at_utc'):
        raise ValueError('Record the actual user model/data/budget instruction once before execution')
    budget = config['budget']
    if budget.get('currency') != 'USD' or not isinstance(budget.get('hard_cap'), (int, float)) or not math.isfinite(budget['hard_cap']) or budget['hard_cap'] <= 0:
        raise ValueError('An explicitly authorized positive USD hard cap is required')
    for key in ('input_per_million', 'cached_input_per_million', 'output_per_million'):
        if not isinstance(budget.get(key), (int, float)) or not math.isfinite(budget[key]) or budget[key] < 0:
            raise ValueError('Actual provider price required: ' + key)
    if not budget.get('pricing_source') or not budget.get('verified_at_utc'):
        raise ValueError('Record current pricing source and verification time')
    if not (run / 'inputs/manuscript.txt').is_file():
        raise ValueError('Missing run-local inspectable manuscript.txt')
    source = run / 'inputs/paper_source.json'
    if not source.is_file() or not read(source).get('source_url_or_path'):
        raise ValueError('Record actual paper provenance and conversion limitations')
    if read(run / 'planned_slots.json') != schedule():
        raise ValueError('Planned call order changed')
    catalog_p01 = next(x['text'] for x in CATALOG_PROMPTS if x['id'] == 'P01')
    if (EXP / 'prompts/P01.txt').read_text(encoding='utf-8').rstrip('\n') != catalog_p01.rstrip('\n'):
        raise ValueError('Exported P01 differs from the canonical catalog renderer')
    for field in ('sampling', 'evaluation_sampling'):
        if is_default:
            # Provider defaults are requested by omission. An output limit is
            # an explicit engineering/budget bound, shared by both models.
            if set(config[field]) != {'max_completion_tokens', 'stream'} or config[field]['stream'] is not False:
                raise ValueError('Default profile must omit temperature/top_p/reasoning overrides')
            cap = config[field]['max_completion_tokens']
            if type(cap) is not int or not 1 <= cap <= 32768:
                raise ValueError('Invalid engineering output cap')
            continue
        if set(config[field]) != set(proposed_config('validation')[field]):
            raise ValueError('Unexpected sampling fields')
        if config[field]['n'] != 1 or config[field]['stream'] or config[field]['store'] or config[field]['service_tier'] != 'default':
            raise ValueError('Only one unstreamed default-tier answer with store=false is supported')
        if not 0 <= config[field]['temperature'] <= 2 or not 0 < config[field]['top_p'] <= 1:
            raise ValueError('Invalid sampling')
        if not isinstance(config[field]['max_completion_tokens'], int) or not 1 <= config[field]['max_completion_tokens'] <= 32768:
            raise ValueError('Invalid output cap')
        if config[field]['reasoning_effort'] != 'none':
            raise ValueError('E0 non-reasoning profile is fixed; a different setting requires a new version')
    if config.get('generation_retry_limit') != 2 or config['annotation'] != proposed_config('validation')['annotation']:
        raise ValueError('Retry or annotation rules changed')
    group = config.get('budget_group')
    if group:
        group_run_ids(group)
        manifest = run / 'inputs/batch_manifest.json'
        registered = read(manifest) if manifest.exists() else {}
        if (registered.get('budget') != {'currency': 'USD', 'hard_cap': group['hard_cap']}
                or registered.get('run_ids') != group['run_ids'] or registered.get('batch_id') != group['batch_id']):
            raise ValueError('Shared budget manifest is missing or differs')
        if config['run_id'] not in group['run_ids'] or config['budget']['hard_cap'] != group['hard_cap']:
            raise ValueError('Run is not a member of the authorized shared cap')


def freeze(run, config):
    validate_config(config, run)
    target = run / 'frozen.json'
    if not target.exists():
        files = {}
        for pid in PROMPTS:
            rel = 'prompts/' + pid + '.txt'
            raw = (EXP / rel).read_bytes()
            safe_write_bytes(run / 'frozen' / rel, raw)
            files['frozen/' + rel] = digest(raw)
        for name in FREEZE_CODE:
            raw = (EXP / 'src' / name).read_bytes()
            safe_write_bytes(run / 'frozen/src' / name, raw)
            files['frozen/src/' + name] = digest(raw)
        for rel in ('config.json', 'planned_slots.json', 'inputs/manuscript.txt', 'inputs/paper_source.json'):
            files[rel] = digest((run / rel).read_bytes())
        if config.get('budget_group'):
            files['inputs/batch_manifest.json'] = digest((run / 'inputs/batch_manifest.json').read_bytes())
        if (run / 'inputs/provider_catalog.json').exists():
            files['inputs/provider_catalog.json'] = digest((run / 'inputs/provider_catalog.json').read_bytes())
        for rel in ('inputs/provider_pricing.json', 'inputs/provider_status.json', 'inputs/provider_routing.json', 'inputs/source.pdf'):
            if (run / rel).exists():
                files[rel] = digest((run / rel).read_bytes())
        raw = (EXP / 'CONVERGENCE_SPEC.md').read_bytes()
        safe_write_bytes(run / 'frozen/CONVERGENCE_SPEC.md', raw)
        files['frozen/CONVERGENCE_SPEC.md'] = digest(raw)
        put(target, {'frozen_at_utc': now(), 'evidence_class': 'diagnostic_only',
            'files': files, 'python_version': sys.version, 'python_executable': sys.executable,
            'no_formal_pilot_activation': True})
    frozen = read(target)
    for rel, sha in frozen['files'].items():
        if digest((run / rel).read_bytes()) != sha:
            raise ValueError('Frozen run content changed: ' + rel)
    for name in FREEZE_CODE:
        if digest((EXP / 'src' / name).read_bytes()) != frozen['files']['frozen/src/' + name]:
            raise ValueError('Live runner differs from frozen code; preserve old run and create a new version')
    for pid in PROMPTS:
        if digest((EXP / 'prompts' / (pid + '.txt')).read_bytes()) != frozen['files']['frozen/prompts/' + pid + '.txt']:
            raise ValueError('Live prompt differs from frozen run')
    return digest(target.read_bytes())


def payload(config, system, user, evaluation=False):
    sample = dict(config['evaluation_sampling' if evaluation else 'sampling'])
    if config['model_snapshot'].startswith('gpt-4.1-'):
        sample.pop('reasoning_effort')
    result = dict(model=config['model_snapshot'], messages=[{'role': 'system', 'content': system},
                 {'role': 'user', 'content': user}], **sample)
    if config['provider'] == 'openai':
        result['service_tier'] = 'default'
    if config['provider'] == 'openrouter':
        # Disable invisible provider fallbacks; each retry is coordinator-owned.
        result['provider'] = {'allow_fallbacks': False, 'require_parameters': True}
    return result


def reserve_cost(config, body):
    # Text-only input upper bound: one token per UTF-8 byte plus 2048 tokens for
    # message/protocol overhead. Intentionally pessimistic; no cached discount.
    request = json.loads(body)
    tokens = sum(len(x['content'].encode('utf-8')) for x in request['messages']) + 2048
    rate = config['budget']
    if rate.get('per_request_upper_bound_usd') is not None:
        return rate['per_request_upper_bound_usd']
    input_rate = max(rate['input_per_million'], rate['cached_input_per_million'], rate.get('cache_write_per_million') or 0)
    output_rate = rate['output_per_million']
    if tokens > rate.get('long_context_input_threshold_tokens', math.inf):
        input_rate *= rate['long_context_input_multiplier']
        output_rate *= rate['long_context_output_multiplier']
    return (tokens * input_rate + request['max_completion_tokens'] * output_rate) / 1e6


def token_cost(config, response):
    u = response.get('usage') or {}
    if not isinstance(u, dict):
        u = {}
    it, ot = u.get('prompt_tokens'), u.get('completion_tokens')
    cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens')
    reasoning = (u.get('completion_tokens_details') or {}).get('reasoning_tokens')
    # OpenRouter documents usage.cost in USD. A gateway's arbitrary cost field
    # is not assumed to use dollars without a verified contract.
    reported_cost = u.get('cost') if config.get('provider') == 'openrouter' else None
    if isinstance(reported_cost, (int, float)) and math.isfinite(reported_cost) and reported_cost >= 0:
        cost = reported_cost
        source = 'provider_reported_cost_usd'
    elif it is None or ot is None:
        cost = None
        source = 'unknown'
    else:
        # Missing cache detail conservatively uses the full input rate. This is
        # labeled a usage-based estimate, not a provider invoice.
        c = cached or 0; p = config['budget']
        cost = ((it-c)*p['input_per_million'] + c*p['cached_input_per_million'] + ot*p['output_per_million']) / 1e6
        source = 'provider_usage_times_frozen_rates'
    upper_bound = None
    if config['budget'].get('rate_semantics') == 'public_tariff_upper_bound_not_invoice' and source != 'provider_reported_cost_usd':
        p = config['budget']
        if p.get('per_request_upper_bound_usd') is not None:
            upper_bound = p['per_request_upper_bound_usd']
        elif it is not None and ot is not None:
            # No discount is assumed without the token's actual billing group.
            input_rate = max(p['input_per_million'], p['cached_input_per_million'], p.get('cache_write_per_million') or 0)
            output_rate = p['output_per_million']
            if it > p.get('long_context_input_threshold_tokens', math.inf):
                input_rate *= p['long_context_input_multiplier']
                output_rate *= p['long_context_output_multiplier']
            upper_bound = (it*input_rate + ot*output_rate)/1e6
        cost = None
        source = 'actual_charge_unknown_public_tariff_upper_bound_only'
    return {'input_tokens': it, 'output_tokens': ot, 'cache_read_tokens': cached,
            'reasoning_tokens': reasoning, 'cost_amount': cost, 'currency': 'USD',
            'cost_upper_bound_amount': upper_bound,
            'cost_source': source,
            'unknown_reason': ('Actual gateway charge/billing group not exposed; only a public-tariff cost upper bound is known.'
                if source == 'actual_charge_unknown_public_tariff_upper_bound_only'
                else None if all(x is not None for x in (it, ot, cached, reasoning))
                else 'Provider did not return all token details; no missing values imputed.')}


def committed(run):
    # Pending/ambiguous requests retain their full reservation across restarts.
    total = 0.0
    for path in sorted((run / 'attempts').glob('*/started.json')):
        start = read(path); done = path.with_name('completed.json')
        usage = read(done)['usage'] if done.exists() else {}
        cost = usage.get('cost_amount')
        if cost is None:
            cost = usage.get('cost_upper_bound_amount')
        total += start['reserved_cost_usd'] if cost is None else cost
    return total


def group_run_ids(group):
    if not isinstance(group.get('run_ids'), list) or len(group['run_ids']) != 2 or len(set(group['run_ids'])) != 2:
        raise ValueError('This paired E0 batch has exactly two distinct runs')
    for run_id in group['run_ids']:
        run_path(run_id)  # validate path containment
    if not re.fullmatch(r'[A-Za-z0-9_-]+', group.get('batch_id', '')):
        raise ValueError('Invalid budget batch ID')
    return group['run_ids']


def budget_committed(run, config):
    group = config.get('budget_group')
    return sum(committed(run_path(x)) for x in group_run_ids(group)) if group else committed(run)


def finish_attempt(run, config, folder, start, result, recovered=False):
    state = classify_http(result)
    response = {}
    try:
        response = strict_json_loads(result['raw_body'].decode('utf-8')) if result['raw_body'] else {}
    except (ValueError, UnicodeError):
        state = state or 'unresolved_status'
    if not isinstance(response, dict):
        response = {}; state = state or 'unresolved_status'
    actual_model = response.get('model')
    model_matches = actual_model == config['model_snapshot']
    if config.get('inference_profile') == 'provider_default_v1' and isinstance(actual_model, str):
        # Accept only the exact selected ID or an explicit dated revision of it.
        model_matches = bool(re.fullmatch(re.escape(config['model_snapshot']) + r'(?:-\d{4}-?\d{2}-?\d{2})?', actual_model))
    if state is None and not model_matches:
        state = 'unresolved_status'
    text = ''; finish = None
    if state is None:
        try:
            choices = response['choices']
            if len(choices) != 1:
                raise ValueError('Unexpected number of outputs')
            choice = choices[0]; message = choice['message']; finish = choice['finish_reason']
            text = message.get('content') or ''
            if message.get('refusal') or finish == 'content_filter':
                state = 'refusal'
            elif finish == 'length':
                state = 'truncated'
            elif not text.strip():
                state = 'empty'
            elif finish != 'stop':
                state = 'unresolved_status'
            else:
                state = 'success'
        except (KeyError, TypeError, ValueError):
            state = 'unresolved_status'
    out = dict(start, completed_at_utc=now(), status=state, text=text,
        provider_finish_reason=finish, response_model=response.get('model'),
        provider_response_id=response.get('id'), usage=token_cost(config, response),
        served_provider=response.get('provider'), system_fingerprint=response.get('system_fingerprint'),
        immutable_weight_revision=None,
        elapsed_seconds=result['elapsed_seconds'], response_sha256=digest(result['raw_body']),
        recovered_from_saved_response=recovered)
    put(folder / 'completed.json', out)
    journal(run / 'events.jsonl', dict(event='request_completed', **out))
    return out


def send_once(run, config, provider, job_id, body, kind, retry_index, frozen_sha, provenance=None):
    reserve = reserve_cost(config, body)
    if budget_committed(run, config) + reserve > config['budget']['hard_cap'] + 1e-12:
        raise BudgetStop('Next full request reservation exceeds the authorized cap')
    aid = 'conv_' + config['run_id'] + '_' + uuid.uuid4().hex
    folder = run / 'attempts' / aid
    safe_write_bytes(folder / 'request.body.json', body)
    start = {'attempt_id': aid, 'job_id': job_id, 'kind': kind, 'retry_index': retry_index,
        'request_started_at_utc': now(), 'request_sha256': digest(body),
        'reserved_cost_usd': reserve, 'endpoint': provider.endpoint, 'frozen_sha256': frozen_sha,
        'budget_group_id': (config.get('budget_group') or {}).get('batch_id'),
        'provenance': provenance or {}}
    put(folder / 'started.json', start)
    journal(run / 'events.jsonl', dict(event='request_started', **start))
    result = provider.send(body)
    safe_write_bytes(folder / 'response.body.txt', result['raw_body'])
    meta = {k: v for k, v in result.items() if k != 'raw_body'}
    put(folder / 'response.meta.json', dict(meta, received_at_utc=now(),
        response_sha256=digest(result['raw_body'])))
    return finish_attempt(run, config, folder, start, result)


class BudgetStop(ValueError):
    pass


def call_job(run, config, provider, job_id, request, kind, frozen_sha, provenance=None):
    body = json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if redact(body) != body:
        raise ValueError('Credential-like content found in a request; refusing to persist or transmit it')
    previous = []
    for path in (run / 'attempts').glob('*/started.json'):
        start = read(path)
        if start['job_id'] != job_id:
            continue
        if start['request_sha256'] != digest(body):
            raise ValueError('Same job requested with a different frozen payload')
        if start.get('provenance', {}) != (provenance or {}):
            raise ValueError('Same job requested with different parent records')
        if not path.with_name('completed.json').exists():
            folder = path.parent
            if (folder / 'response.body.txt').exists() and (folder / 'response.meta.json').exists():
                meta = read(folder / 'response.meta.json')
                raw = (folder / 'response.body.txt').read_bytes()
                if digest(raw) != meta['response_sha256']:
                    raise ValueError('Saved response hash mismatch')
                finish_attempt(run, config, folder, start, dict(meta, raw_body=raw), recovered=True)
            else:
                raise ValueError('Unresolved in-flight attempt: ' + start['attempt_id'] + '; retain reservation and verify provider outcome, never resend blindly')
        previous.append(read(path.with_name('completed.json')))
    previous.sort(key=lambda x: x['retry_index'])
    if [x['retry_index'] for x in previous] != list(range(len(previous))):
        raise ValueError('Attempt numbering or history is inconsistent')
    if previous and (previous[-1]['status'] != 'transient_api_error' or len(previous) == 3):
        return previous[-1]
    while len(previous) < 3:
        out = send_once(run, config, provider, job_id, body, kind, len(previous), frozen_sha, provenance)
        previous.append(out)
        if out['status'] != 'transient_api_error' or len(previous) == 3:
            return out
        time.sleep(min(2 ** len(previous), 8))


def base_registry(run, config, records):
    text = (run / 'inputs/manuscript.txt').read_text(encoding='utf-8')
    source_id = 'conv_' + config['run_id'] + '_paper'
    registry = {source_id: {'record_id': source_id, 'paper_id': config['paper_id'],
        'artifact_kind': 'fixed_manuscript_source', 'document_kind': 'manuscript',
        'kind': 'manuscript', 'text': text, 'sha256': digest(text.encode('utf-8')),
        'private': False, 'approved_for_generation': True}}
    for row in records:
        registry[row['record_id']] = dict(row, kind='review', text=row['raw_text'],
            sha256=digest(row['raw_text'].encode('utf-8')), private=False,
            approved_for_generation=row['status'] == 'success')
    return source_id, registry


def planned_record(config, slot, source_id, records):
    k, t, group = slot['trajectory_id'], slot['round'], slot['condition']
    seed = next((x for x in records if x['trajectory_id'] == k and x['round'] == 0 and x['status'] == 'success'), None)
    prior = next((x for x in reversed(records) if x['trajectory_id'] == k and x['round'] == t-1 and x['condition'] == 'A_LOOP' and x['status'] == 'success'), None) if t and group == 'A_LOOP' else None
    if t and seed is None:
        return None, 'shared_seed_failed_or_missing'
    # Even the no-history condition stops after a failure in its own trajectory.
    if t > 1 and not any(x['trajectory_id'] == k and x['round'] == t-1 and x['condition'] == group and x['status'] == 'success' for x in records):
        return None, 'previous_branch_slot_failed_or_missing'
    if t and group == 'A_LOOP' and prior is None:
        return None, 'previous_loop_review_failed_or_missing'
    rid = 'conv_' + config['run_id'] + '_' + slot['slot_id']
    review_id = prior['record_id'] if prior else None
    return dict(BASE, record_id=rid, paper_id=config['paper_id'], track='A',
        condition=group, trajectory_id=k, round=t, stage='review', substep=None,
        prompt_id='P01', document_kind='review', status='planned', raw_text='',
        parent_record_ids=[source_id] + ([review_id] if review_id else []),
        input_state_record_id=source_id, input_manuscript_record_id=source_id,
        input_review_record_id=review_id, input_description_record_id=None,
        input_fact_record_id=None, input_fact_sha256=None,
        history_mode='previous_review_only' if review_id else 'none',
        history_record_ids=[review_id] if review_id else [], prefix_record_ids=[],
        lineage_root_record_id=seed['record_id'] if seed else rid,
        intervention_type='NONE', intervention_id=None, reset_from_record_id=None,
        terminal_no_issue=False, attempt=0, model_snapshot=config['model_snapshot'],
        input_sha256=None, output_sha256=None), None


def task_prompt(run, pid, params):
    return render_prompt((run / 'frozen/prompts' / (pid + '.txt')).read_text(encoding='utf-8'), params)


def status_check(run, config, provider, row, attempt, frozen_sha):
    if attempt['status'] != 'success':
        return attempt['status'], False, None
    job_id = row['record_id'] + '_P27'
    user = task_prompt(run, 'P27', {'task_kind': 'complete manuscript review',
        'provider_finish_reason': attempt['provider_finish_reason'], 'raw_output': attempt['text']})
    request = payload(config, task_prompt(run, 'P00E', {}), user, evaluation=True)
    for revision in (0, 1):
        result = call_job(run, config, provider, job_id + f'_format{revision}', request, 'status_evaluation', frozen_sha,
                          {'generation_record_id': row['record_id'], 'generation_attempt_id': attempt['attempt_id']})
        if result['status'] != 'success':
            return 'unresolved_status', False, result['attempt_id']
        try:
            data = strict_json_loads(result['text'])
            if data['status'] not in {'success', 'truncated', 'empty', 'refusal', 'off_task', 'parse_failure', 'uncertain'}:
                raise ValueError('Invalid status label')
            if type(data['terminal_no_issue']) is not bool or not isinstance(data['reason'], str):
                raise ValueError('Invalid status fields')
            status = 'unresolved_status' if data['status'] == 'uncertain' else data['status']
            return status, data['terminal_no_issue'], result['attempt_id']
        except (ValueError, KeyError, TypeError):
            continue
    return 'unresolved_status', False, result['attempt_id']


def generate(run, config, provider, frozen_sha, limit=None):
    records = lines(run / 'records.jsonl')
    # Only final scientific slot rows live in records.jsonl. All network attempts
    # (including status and labels) live in attempts/ and events.jsonl.
    completed = {x['slot_id'] for x in records}
    generated = 0
    for slot in schedule():
        if slot['slot_id'] in completed:
            continue
        source_id, registry = base_registry(run, config, records)
        row, skip = planned_record(config, slot, source_id, records)
        if skip:
            put(run / 'slots' / (slot['slot_id'] + '.json'), dict(slot, status='not_attempted', reason=skip))
            continue
        assert_generation_lineage(row, registry)
        bindings = {'manuscript': source_id, 'previous_review': row['input_review_record_id'] or 'NONE'}
        rendered = _render_catalog_slots('P01', bindings, registry, row)
        row = rendered['record']
        # Persist parent bindings before dispatch, even if the process dies
        # before a final scientific slot record can be written.
        plan_path = run / 'plans' / (row['record_id'] + '.json')
        if plan_path.exists() and read(plan_path) != row:
            raise ValueError('Existing slot parent plan changed')
        if not plan_path.exists():
            put(plan_path, row)
        # Reuse retry/lineage validation without pretending to have a formal
        # activation manifest. Each actual generation attempt is audited below.
        request = payload(config, task_prompt(run, 'P00R', {}), rendered['text'])
        attempt = call_job(run, config, provider, row['record_id'], request, 'generation', frozen_sha,
            {key: row[key] for key in ('parent_record_ids', 'input_manuscript_record_id',
             'input_review_record_id', 'history_record_ids', 'lineage_root_record_id',
             'trajectory_id', 'round', 'condition')})
        state, no_issue, status_id = status_check(run, config, provider, row, attempt, frozen_sha)
        out = dict(row, slot_id=slot['slot_id'], status=state, raw_text=attempt['text'],
            terminal_no_issue=no_issue if state == 'success' else False,
            request_sent_at_utc=attempt['request_started_at_utc'],
            completed_at_utc=attempt['completed_at_utc'], generation_attempt_id=attempt['attempt_id'],
            status_evaluation_attempt_id=status_id, provider_finish_reason=attempt['provider_finish_reason'],
            response_model=attempt['response_model'], output_sha256=digest(attempt['text'].encode('utf-8')),
            usage=attempt['usage'], attempt=attempt['retry_index'])
        # Audit the complete generation attempt history, retaining failed raw
        # responses. P27 doesn't replace an actual transport failure state.
        history = lines(run / 'generation_attempts.jsonl')
        existing_ids = {x['record_id'] for x in history}
        attempts = []
        for path in (run / 'attempts').glob('*/completed.json'):
            a = read(path)
            if a['job_id'] == row['record_id']:
                attempts.append(a)
        for a in sorted(attempts, key=lambda x: x['retry_index']):
            if a['attempt_id'] in existing_ids:
                continue
            audit_row = dict(row, record_id=a['attempt_id'], attempt=a['retry_index'],
                status=a['status'], raw_text=a['text'], request_sent_at_utc=a['request_started_at_utc'],
                usage=dict(a['usage'], generation_call_count=1))
            if row['round'] == 0:
                audit_row['lineage_root_record_id'] = audit_row['record_id']
            assert_next_attempt(audit_row, history)
            journal(run / 'generation_attempts.jsonl', audit_row); history.append(audit_row)
        journal(run / 'records.jsonl', out); records.append(out)
        safe_write_text(run / 'reviews' / (slot['slot_id'] + '.txt'), out['raw_text'])
        put(run / 'slots' / (slot['slot_id'] + '.json'), dict(slot, status=state, record_id=out['record_id']))
        generated += 1
        print(json.dumps({'slot': slot['slot_id'], 'status': state,
            'committed_budget_usd': round(committed(run), 6)}, ensure_ascii=False), flush=True)
        if limit is not None and generated >= limit:
            break
    return records


def annotate(run, config, provider, frozen_sha):
    for row in lines(run / 'records.jsonl'):
        if row['status'] != 'success':
            continue
        output = run / 'annotations' / (row['slot_id'] + '.json')
        if output.exists():
            continue
        # A deterministic opaque ID is coordinator-owned and contains no group,
        # round, model or directory information sent to the annotation model.
        blind = 'D' + digest(row['record_id'].encode('utf-8'))[:20]
        try:
            blocks = parse_markdown_blocks(row['raw_text'], blind)
        except ValueError as exc:
            put(output, {'status': 'segmentation_unresolved', 'reason': str(exc),
                'sequence': None, 'label_source': 'not_annotated', 'human_verified': False})
            continue
        refs = []; failed = False
        for start in range(0, len(blocks), 20):
            stop = min(start + 20, len(blocks))
            batch = [dict(b, annotation_target=start <= i < stop) for i, b in enumerate(blocks)
                     if max(0, start-2) <= i < min(len(blocks), stop+2)]
            expected = {b['block_id']: b for b in blocks[start:stop]}
            user = task_prompt(run, 'P09', {'document_kind': 'review', 'blocks_json': dumps(batch)})
            request = payload(config, task_prompt(run, 'P00E', {}), user, evaluation=True)
            valid = False
            for revision in (0, 1):
                a = call_job(run, config, provider, row['record_id'] + f'_P09_{start}_format{revision}',
                             request, 'structure_annotation', frozen_sha,
                             {'generation_record_id': row['record_id'], 'blind_document_id': blind,
                              'target_block_ids': list(expected)})
                refs.append(a['attempt_id'])
                if a['status'] != 'success':
                    break
                try:
                    data = strict_json_loads(a['text'])
                    if data['document_kind'] != 'review' or not isinstance(data['labels'], list):
                        raise ValueError('Wrong annotation kind')
                    labels = data['labels']
                    if len(labels) != len(expected) or {x['block_id'] for x in labels} != set(expected):
                        raise ValueError('Missing, duplicate or extraneous block IDs')
                    for label in labels:
                        b = expected[label['block_id']]
                        if (b['block_type'] == 'heading' and label['role'] is not None) or (b['block_type'] != 'heading' and label['role'] not in set('SPNQAVMO')):
                            raise ValueError('Invalid role')
                        if label['confidence'] not in {'high', 'medium', 'low'} or not isinstance(label['reason'], str) or not label['reason'].strip():
                            raise ValueError('Missing confidence/reason')
                    for label in labels:
                        expected[label['block_id']].update(role=label['role'],
                            label_confidence=label['confidence'], label_reason=label['reason'])
                    valid = True; break
                except (ValueError, KeyError, TypeError):
                    continue
            if not valid:
                failed = True; break
        sequence = None if failed else body_roles(blocks, 'review')
        if not sequence:
            failed = True; sequence = None
        put(output, {'record_id': row['record_id'], 'blind_document_id': blind,
            'status': 'annotation_validation_error' if failed else 'success',
            'sequence': sequence, 'blocks': blocks, 'attempt_ids': refs,
            'raw_text_sha256': row['output_sha256'],
            'label_source': 'automatic_P00E_P09_same_frozen_model',
            'human_verified': False, 'evidence_class': 'diagnostic_only'})


def analysis(run):
    records = lines(run / 'records.jsonl'); curves = []; sequences = {}
    for row in records:
        path = run / 'annotations' / (row['slot_id'] + '.json')
        a = read(path) if path.exists() else {}
        sequences[row['slot_id']] = a.get('sequence') if row['status'] == 'success' and a.get('status') == 'success' else None
    def sequence(group, k, t):
        return sequences.get(f'seed_k{k}' if t == 0 else f'{group}_k{k}_t{t}')
    for t in (0, 1, 2):
        row = {'round': t, 'expected_trajectories': 3, 'label_source': 'automatic_P00E_P09_same_frozen_model',
               'human_verified': False}
        for group, suffix in (('A_LOOP', 'loop'), ('A_INDEPENDENT', 'independent')):
            seq = [sequence(group, k, t) for k in (1, 2, 3)]
            row['available_' + suffix] = sum(bool(s) for s in seq)
            row['D_' + suffix] = mean_pairwise_edit(seq, expected_k=3)
            row['pairs_' + suffix] = [
                {'left': i+1, 'right': j+1,
                 'distance': normalized_edit(seq[i], seq[j]) if seq[i] and seq[j] else None}
                for i, j in ((0, 1), (0, 2), (1, 2))]
        curves.append(row)
    for row in curves:
        row['C_loop'] = contraction(curves[0]['D_loop'], row['D_loop'])
        row['C_independent'] = contraction(curves[0]['D_independent'], row['D_independent'])
        row['delta_C'] = extra_contraction(curves[0]['D_loop'], row['D_loop'], curves[0]['D_independent'], row['D_independent'])
        row['measurement_floor'] = curves[0]['D_loop'] == 0 if curves[0]['D_loop'] is not None else None
        row['missing_reason'] = 'Fewer than three successful, fully labeled trajectories' if row['D_loop'] is None or row['D_independent'] is None else None
    result = {'evidence_class': 'diagnostic_only', 'n_papers': 1 if records else 0,
        'human_endpoint_status': 'not_performed', 'curves': curves,
        'interpretation_limit': 'Two updates test chain and measurement feasibility; no long-run convergence or hypothesis rejection claim.'}
    put(run / 'analysis/metrics.json', result)
    fields = ['round', 'expected_trajectories', 'available_loop', 'available_independent',
              'D_loop', 'D_independent', 'C_loop', 'C_independent', 'delta_C', 'measurement_floor', 'missing_reason']
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fields, extrasaction='ignore')
    writer.writeheader(); writer.writerows(curves)
    safe_write_text(run / 'analysis/metrics.csv', stream.getvalue())
    # SVG is generated from observed values only. Empty data are visibly missing.
    colors = {'D_loop': '#ae3343', 'D_independent': '#234d75'}
    pieces = ['<svg xmlns="http://www.w3.org/2000/svg" width="740" height="300" viewBox="0 0 740 300">',
        '<rect width="740" height="300" fill="#fff"/>',
        '<text x="35" y="25" font-family="sans-serif" font-size="15">E0 automatic structural distance D (not human verified)</text>']
    for y in (0, .25, .5, .75, 1):
        yy = 235 - 175*y
        pieces.append(f'<path d="M65 {yy} H500" stroke="#ddd"/><text x="25" y="{yy+5}" font-family="sans-serif" font-size="12">{y:.2f}</text>')
    for t in (0, 1, 2):
        pieces.append(f'<text x="{65+210*t}" y="260" font-family="sans-serif" font-size="13">{t}</text>')
    pieces.append('<text x="230" y="287" font-family="sans-serif" font-size="12">Update round</text>')
    for field, color in colors.items():
        previous = None
        for row in curves:
            value = row[field]
            if value is None:
                previous = None; continue
            point = (65 + row['round']*210, 235-value*175)
            if previous:
                pieces.append(f'<path d="M{previous[0]} {previous[1]} L{point[0]} {point[1]}" fill="none" stroke="{color}" stroke-width="2"/>')
            pieces.append(f'<circle cx="{point[0]}" cy="{point[1]}" r="4" fill="{color}"/>')
            previous = point
    pieces.append('<text x="530" y="80" font-family="sans-serif" fill="#ae3343">A_LOOP</text><text x="530" y="105" font-family="sans-serif" fill="#234d75">A_INDEPENDENT</text>')
    if not any(r['D_loop'] is not None or r['D_independent'] is not None for r in curves):
        pieces.append('<text x="125" y="155" font-family="sans-serif" font-size="16" fill="#666">No observed distances - all values missing</text>')
    pieces.append('</svg>')
    safe_write_text(run / 'analysis/curves.svg', ''.join(pieces))
    return result


def report(run):
    config = read(run / 'config.json'); result = analysis(run)
    starts = [read(p) for p in (run / 'attempts').glob('*/started.json')]
    attempts = [read(p) for p in (run / 'attempts').glob('*/completed.json')]
    records = lines(run / 'records.jsonl')
    known = sum(a['usage']['cost_amount'] for a in attempts if a['usage']['cost_amount'] is not None)
    unknown = sum(a['usage']['cost_amount'] is None for a in attempts) + len(starts)-len(attempts)
    good = sum(x['status'] == 'success' for x in records)
    gen = sum(x['kind'] == 'generation' for x in starts)
    slot_states = [read(p) for p in (run / 'slots').glob('*.json')]
    skipped = sum(x['status'] == 'not_attempted' for x in slot_states)
    complete = len(records) + skipped == 15
    annotation_files = list((run / 'annotations').glob('*.json'))
    annotation_successes = sum(read(p).get('status') == 'success' for p in annotation_files)
    summary = {'run_id': config['run_id'], 'updated_at_utc': now(),
        'status': 'e0_development_finished' if complete and len(annotation_files) == good else 'partial_or_not_started',
        'evidence_class': 'diagnostic_only', 'planned_generation_slots': 15,
        'successful_generation_slots': good, 'terminal_failed_slots': len(records)-good,
        'not_attempted_descendant_slots': skipped, 'uncompleted_slots': 15-len(records)-skipped,
        'annotated_successful_slots': annotation_successes,
        'annotation_failed_or_unresolved_slots': len(annotation_files)-annotation_successes,
        'actual_api_attempts': len(starts),
        'generation_attempts': gen, 'evaluation_attempts': len(starts)-gen,
        'known_usage_priced_cost_usd': known, 'unknown_cost_attempts': unknown,
        'conservative_budget_committed_usd': committed(run), 'human_annotations': 0}
    put(run / 'summary.json', summary)
    rows = ['| 轮次 | D 接力 | D 独立 | C 接力 | C 独立 | ΔC |', '|---|---:|---:|---:|---:|---:|']
    fmt = lambda x: '缺失' if x is None else f'{x:.4f}'
    for row in result['curves']:
        rows.append('| ' + str(row['round']) + ' | ' + ' | '.join(fmt(row[x]) for x in ('D_loop', 'D_independent', 'C_loop', 'C_independent', 'delta_C')) + ' |')
    purpose = '检查固定论文、三起点、接力/无历史两条件各两轮的父记录与 S01–S03 测量链条。实验单位为论文；E0 不用于判断长期趋同。'
    model_display = config.get('model_snapshot') or ((config['requested_model'] + '（已指定，网关 ID 待查询）') if config.get('requested_model') else '尚未授权')
    settings = f"开发论文：{config.get('paper_id') or '尚未指定'}；模型：{model_display}；原版 P00R+P01；计划 15 槽；预算：{config['budget']['hard_cap'] if config['budget']['hard_cap'] is not None else '尚未授权'} {config['budget']['currency'] or ''}。"
    if config.get('inference_profile') == 'provider_default_v1':
        settings += '生成与评估均省略采样/推理覆盖参数，使用提供者默认；输出 token 上限是明确的工程限制。公开别名未暴露不可变权重版本，不伪称精确快照。'
    if config.get('budget_group'):
        settings += '此为两个独立 run 共用的合计上限，不是每个 run 各一份预算。'
    calls = f"真实 API 尝试 {len(starts)} 次（生成 {gen}，评估/标注 {len(starts)-gen}）；成功生成槽 {good}/15，已终止失败槽 {len(records)-good}；已知用量计价 ${known:.6f}，未知费用 {unknown} 次。未发送槽不计作调用失败。"
    if config['budget'].get('rate_semantics') == 'public_tariff_upper_bound_not_invoice':
        calls += f'公共价目只用作费用上界；实际账单未返回则保留未知。当前保守预算占用 ${committed(run):.6f}。'
    explanation = '标签计划来自同一冻结模型的 P00E+P09 自动标注，20 单元一批、邻接各 2 单元；未做人审。正文不合并连续相同标签。每轮固定三轨迹、三对距离；任一必要端点缺失则 D/C/ΔC 缺失，不缩小分母。'
    floor = '起点 D0=0：存在测量地板，不重抽起点。' if result['curves'][0]['measurement_floor'] else '当前没有可判断测量地板的完整起点。' if result['curves'][0]['measurement_floor'] is None else '起点 D0>0；只描述本次自动表示下的结果。'
    if not starts:
        interpretation = config.get('blocking_reason_cn') or '本次完成离线准备，未发生真实实验调用，尚无正常审稿或失败响应可分析。论文、固定模型、预算缺失；本机外部 API 域名 DNS 解析失败。曲线为空、数值均为缺失，不是零差异结果。'
    else:
        interpretation = '参见 records.jsonl、attempts/ 原始请求响应和 annotations/ 逐块标签；所有成功与失败均保留。调用状态和自动标签未经独立人审。'
    next_step = '补齐实际论文来源、模型及预算原指令并恢复 API 网络；先执行 1 槽并核验落盘，再从日志恢复余下计划。E0 完成后另行建议 E1，不自动执行。'
    if config.get('requested_model') and config.get('budget_group'):
        next_step = '恢复当前执行环境联网后，下载已选论文、查询网关实际模型 ID 与价格；各验证一个计划槽落盘，再在两个 run 共用预算内继续。已登记的模型选择和预算无需再次确认；E1 不自动执行。'
    text = '# E0 开发实验记录（单页）\n\n' + '\n\n'.join((purpose, settings, calls, '\n'.join(rows), explanation, floor, interpretation, next_step)) + '\n'
    safe_write_text(run / 'REPORT_CN.md', text)
    table = '<table><tr><th>轮次</th><th>D 接力</th><th>D 独立</th><th>C 接力</th><th>C 独立</th><th>ΔC</th></tr>'
    for row in result['curves']:
        table += '<tr><td>' + str(row['round']) + '</td>' + ''.join('<td>' + fmt(row[x]) + '</td>' for x in ('D_loop', 'D_independent', 'C_loop', 'C_independent', 'delta_C')) + '</tr>'
    table += '</table>'
    content = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>E0 开发实验</title><style>body{font:14px/1.5 "Microsoft YaHei",sans-serif;color:#203040;max-width:900px;margin:30px auto;padding:0 28px}h1{font-size:24px;margin-bottom:12px}p{margin:10px 0}table{width:100%;border-collapse:collapse}th,td{padding:6px 10px;border-bottom:1px solid #ddd;text-align:right}th:first-child,td:first-child{text-align:left}img{width:100%;max-height:260px}@media print{body{margin:0;font-size:11px}h1{font-size:20px}@page{size:A4;margin:14mm}}</style><h1>E0 开发实验记录</h1>'
    content += ''.join('<p>' + html.escape(x) + '</p>' for x in (purpose, settings, calls)) + table
    content += '<img src="analysis/curves.svg" alt="自动结构距离；缺失数据不连线">'
    content += ''.join('<p>' + html.escape(x) + '</p>' for x in (explanation, floor, interpretation, next_step)) + '</html>'
    safe_write_text(run / 'REPORT_CN.html', content)
    return summary


def sync_state(run, summary):
    # Root helper provides a separate project-scoped atomic writer. Never alter
    # the formal pilot configuration or claim formal execution is enabled.
    import importlib.util
    module_spec = importlib.util.spec_from_file_location('carcinization_project_state', ROOT / 'scripts/project.py')
    helper = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(helper)
    state = read(ROOT / 'PROJECT_STATE.json')
    state['api_executor_status'] = 'development_e0_stdlib_rest_adapter_implemented_offline_tested'
    state['latest_development_run'] = run.relative_to(ROOT).as_posix()
    state['latest_development_status'] = summary
    state['stage'] = ('development_e0_completed' if summary['status'] == 'e0_development_finished'
        else 'development_e0_partial' if summary['actual_api_attempts'] else 'development_e0_prepared_pending_inputs_authorization_and_network')
    all_summaries = [read(p) for p in RUNS.glob('*/summary.json')]
    state['actual_model_calls'] = sum(x['actual_api_attempts'] for x in all_summaries)
    state['paid_experiment_calls'] = state['actual_model_calls']
    state['paid_experiment_calls_note'] = 'Counts registered API attempts, not proof every request was billed; consult known and unknown costs.'
    state['next_actions'] = ['provide actual development paper and model/budget instruction, restore API network',
        'validate first real E0 slot and persistence, then resume remaining fixed slots',
        'finish automatic S01-S03 analysis and E0 report; E1 requires a separate run and instruction'] if summary['status'] != 'e0_development_finished' else ['review E0 chain and automatic measurement results', 'consider separate E1; not automatically executed']
    helper.put(ROOT / 'PROJECT_STATE.json', state)


def run_e0(run_id, limit=None, labels_only=False):
    run = run_path(run_id)
    with ExitStack() as stack:
        config = read(run / 'config.json')
        if config.get('budget_group'):
            group = config['budget_group']; group_run_ids(group)
            stack.enter_context(locked(RUNS / '_batches' / group['batch_id']))
        stack.enter_context(locked(run))
        frozen_sha = freeze(run, config)
        provider = OpenAIProvider(config['credential_env_var'], config['timeout_seconds'], config['endpoint'])
        try:
            if not labels_only:
                generate(run, config, provider, frozen_sha, limit)
            if limit is None or labels_only:
                annotate(run, config, provider, frozen_sha)
        except BudgetStop as exc:
            put(run / 'budget_stop.json', {'stopped_at_utc': now(), 'reason': str(exc),
                'committed_usd': committed(run), 'cap_usd': config['budget']['hard_cap']})
        finally:
            summary = report(run)
            sync_state(run, summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run', 'annotate', 'report'))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--limit', type=int, choices=(1,), help='First real generation slot plus its P27 status check')
    args = parser.parse_args()
    if args.command == 'prepare':
        run = prepare(args.run_id)
        sync_state(run, read(run / 'summary.json'))
        print(run); return
    run = run_path(args.run_id)
    if args.command == 'preflight':
        validate_config(read(run / 'config.json'), run)
        print('E0 development preflight passed; no network calls'); return
    if args.command == 'report':
        with locked(run):
            summary = report(run); sync_state(run, summary)
            print(dumps(summary))
        return
    print(dumps(run_e0(args.run_id, args.limit, args.command == 'annotate')))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
