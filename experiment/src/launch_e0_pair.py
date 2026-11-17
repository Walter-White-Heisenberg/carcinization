"""Run the authorized paired E0 from the user's network-enabled terminal.

Reuses development_e0 for every paid call, retry, lineage, budget and analysis.
Bootstrap HTTP requests are read-only and journaled separately from model calls.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import development_e0 as e
from development_provider import redact
from prepare_e0_default_pair import BATCH_ID, RUN_IDS

ORIGIN = 'https://www.tokentym.com'
CATALOG_URL = ORIGIN + '/v1/models'
OPENAI_CATALOG_URL = 'https://api.openai.com/v1/models'
OPENAI_PRICE_SOURCE = 'https://developers.openai.com/api/docs/models/gpt-6.1-sol'
PRICING_URL = ORIGIN + '/api/pricing'
STATUS_URL = ORIGIN + '/api/status'
PAPER_URL = 'https://arxiv.org/pdf/1706.03762v1'


def load_missing_user_credentials():
    """Current terminal values win; only fill absent values from HKCU env."""
    if os.name != 'nt':
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
            for name in ('OPENAI_API_KEY', 'MODELHUB_CN_API_KEY'):
                if os.getenv(name):
                    continue
                try:
                    value, _ = winreg.QueryValueEx(registry, name)
                    if isinstance(value, str) and value.strip():
                        os.environ[name] = value
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        pass


class BootstrapHTTPError(ValueError):
    def __init__(self, status, url, authenticated, evidence_path):
        self.status = status
        self.url = url
        self.authenticated = authenticated
        self.evidence_path = evidence_path
        super().__init__(f'Read-only endpoint returned HTTP {status}: {url}; '
                         f'authenticated={authenticated}; saved error: {evidence_path}')


def fetch(url, folder, name, authenticated=False, timeout=60, limit=25*1024*1024):
    allowed = {CATALOG_URL, OPENAI_CATALOG_URL, PRICING_URL, STATUS_URL, PAPER_URL}
    if url not in allowed:
        raise ValueError('Unregistered bootstrap URL')
    headers = {'User-Agent': 'Carcinization-E0-development/1.0'}
    if authenticated:
        credentials = {ORIGIN: 'MODELHUB_CN_API_KEY', 'https://api.openai.com': 'OPENAI_API_KEY'}
        variable = next((var for origin, var in credentials.items() if url.startswith(origin + '/')), None)
        if variable is None:
            raise ValueError('Do not send API credentials to a paper source')
        key = os.getenv(variable)
        if not key:
            raise ValueError(variable + ' is absent in this terminal')
        headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(url, headers=headers, method='GET')
    start = e.now()
    class Redirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if authenticated:
                return None
            from urllib.parse import urlsplit
            if urlsplit(newurl).hostname not in {'arxiv.org', 'export.arxiv.org'}:
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(limit+1)
            if len(raw) > limit:
                raise ValueError('Bootstrap response exceeds size limit')
            status = response.status
    except urllib.error.HTTPError as exc:
        error_name = 'error_' + uuid.uuid4().hex
        body_path = folder / 'errors' / (error_name + '.body.txt')
        error_body = redact(exc.read(limit))
        e.safe_write_bytes(body_path, error_body)
        e.put(folder / 'errors' / (error_name + '.meta.json'), {
            'url': url, 'http_status': exc.code, 'authenticated': authenticated,
            'content_type': exc.headers.get('content-type') if exc.headers else None,
            'started_at_utc': start, 'finished_at_utc': e.now(),
            'body_sha256': e.digest(error_body), 'actual_model_calls': 0})
        e.journal(folder / 'bootstrap_events.jsonl', {'kind': 'read_only_http', 'url': url,
            'started_at_utc': start, 'finished_at_utc': e.now(), 'http_status': exc.code,
            'authenticated': authenticated, 'saved_error_body': str(body_path),
            'actual_model_calls': 0})
        raise BootstrapHTTPError(exc.code, url, authenticated, str(body_path)) from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        e.journal(folder / 'bootstrap_events.jsonl', {'kind': 'read_only_http', 'url': url,
            'started_at_utc': start, 'finished_at_utc': e.now(), 'error_type': type(exc).__name__,
            'actual_model_calls': 0})
        raise ValueError('Cannot reach the API/paper source in this execution environment; no model call sent') from None
    raw = redact(raw)
    target_name = name
    existing = folder / name
    if existing.exists() and existing.read_bytes() != raw:
        item = Path(name)
        target_name = item.stem + '_' + uuid.uuid4().hex + item.suffix
    if not (folder / target_name).exists():
        e.safe_write_bytes(folder / target_name, raw)
    e.journal(folder / 'bootstrap_events.jsonl', {'kind': 'read_only_http', 'url': url,
        'started_at_utc': start, 'finished_at_utc': e.now(), 'http_status': status,
        'saved_as': target_name, 'sha256': e.digest(raw), 'actual_model_calls': 0})
    return raw


def fetch_metadata(url, folder, name):
    """Some installations make normally public metadata authenticated.

    Reuse the already-authorized model API credential only on its matched
    gateway origin. A second 401/403 is preserved as a distinct website/API
    permission issue; it is never silently treated as invalid model credentials.
    """
    if url not in {PRICING_URL, STATUS_URL}:
        raise ValueError('Only registered gateway metadata URLs can use this auth fallback')
    try:
        return json.loads(fetch(url, folder, name, authenticated=False))
    except BootstrapHTTPError as exc:
        if exc.status not in {401, 403}:
            raise
        print(f'Metadata HTTP {exc.status}; retrying once with the existing gateway API credential.', flush=True)
        try:
            return json.loads(fetch(url, folder, name, authenticated=True))
        except BootstrapHTTPError as authenticated_error:
            if authenticated_error.status in {401, 403}:
                raise ValueError('The model API key can query /v1/models, but this website metadata endpoint '
                    'still denies it. A website login/access token or an independently verified price snapshot '
                    'is needed; do not replace the working model key. Error body: ' +
                    authenticated_error.evidence_path) from None
            raise


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Missing/invalid live pricing field: ' + name)
    if value < 0 or (positive and value == 0):
        raise ValueError('Negative/zero live pricing field: ' + name)
    return float(value)


def public_price_bound(pricing, site, model_id):
    """Support the documented New API ratio/per-request public price schema.

    Actual token billing group is not assumed. Use the maximum published group
    multiplier as a conservative bound, and do not label it an actual invoice.
    Unsupported expression/tier pricing is refused, never guessed.
    """
    if pricing.get('success') is not True or not isinstance(pricing.get('data'), list):
        raise ValueError('Gateway did not return the supported public pricing schema')
    entries = [x for x in pricing['data'] if isinstance(x, dict) and x.get('model_name') == model_id]
    if len(entries) != 1:
        raise ValueError('Live price missing or ambiguous for ' + model_id)
    row = entries[0]
    if row.get('billing_mode') in {'tiered_expr', 'expression'} or row.get('billing_expr'):
        raise ValueError('This gateway uses an unsupported billing expression; no paid call sent')
    groups = pricing.get('group_ratio')
    if not isinstance(groups, dict) or not groups:
        raise ValueError('Actual published group multipliers are missing')
    multiplier = max(number(v, 'group_ratio') for v in groups.values())
    result = {'currency': 'USD', 'hard_cap': 5.0,
        'rate_semantics': 'public_tariff_upper_bound_not_invoice',
        'pricing_source': PRICING_URL, 'verified_at_utc': e.now(),
        'maximum_published_group_multiplier': multiplier,
        'actual_token_billing_group': None,
        'formula_source': 'https://github.com/QuantumNous/new-api/blob/main/service/quota.go'}
    if type(row.get('quota_type')) is not int:
        raise ValueError('Missing/invalid quota_type')
    if row.get('quota_type') == 1:
        price = number(row.get('model_price'), 'model_price')*multiplier
        result.update(input_per_million=0.0, output_per_million=0.0,
            cached_input_per_million=0.0, per_request_upper_bound_usd=price)
    elif row.get('quota_type') == 0:
        info = site.get('data') if isinstance(site.get('data'), dict) else site
        units = number(info.get('quota_per_unit'), 'quota_per_unit', positive=True)
        base = number(row.get('model_ratio'), 'model_ratio')*multiplier*1e6/units
        output = base*number(row.get('completion_ratio'), 'completion_ratio')
        cache = base*number(row.get('cache_ratio', 1.0), 'cache_ratio')
        write = base*number(row.get('create_cache_ratio', 1.0), 'create_cache_ratio')
        result.update(input_per_million=base, output_per_million=output,
            cached_input_per_million=cache, cache_write_per_million=write,
            quota_per_unit=units)
    else:
        raise ValueError('Unsupported/missing quota_type; no paid call sent')
    return result


def official_openai_price_bound():
    snapshot = e.read(e.EXP / 'config/provider_pricing/openai_gpt61_20261116.json')
    if e.now()[:10] != snapshot['verified_on_utc_date']:
        raise ValueError('Refresh the dated official OpenAI tariff snapshot before a new launch')
    return dict(snapshot['budget_rates'], currency='USD', hard_cap=5.0,
        rate_semantics='public_tariff_upper_bound_not_invoice',
        pricing_source=OPENAI_PRICE_SOURCE, verified_at_utc=e.now(),
        source_verification_method=snapshot['verification_method'],
        source_verified_on_utc_date=snapshot['verified_on_utc_date'])


def modelhub_price_bound(run, batch):
    """Use account tariff evidence, never guessed website-backend endpoints.

    The terminal operator supplies conservative USD rates from their account.
    No missing rate is inferred from the upstream model's official pricing.
    """
    if (run / 'frozen.json').exists():
        return e.read(run / 'config.json')['budget']
    path = batch / 'bootstrap/modelhub_account_price_bound.json'
    if path.exists():
        entry = e.read(path)
        if entry.get('model_id') != 'kimi-k3.1-pro' or entry.get('currency') != 'USD':
            raise ValueError('Saved ModelHub tariff has a different model or currency')
        if str(entry.get('verified_at_utc', ''))[:10] != e.now()[:10]:
            raise ValueError('Saved ModelHub tariff is from a previous date; update its account-price evidence')
        for key in ('input_per_million', 'cached_input_per_million', 'cache_write_per_million', 'output_per_million'):
            number(entry.get(key), key, positive=True)
        if not entry.get('pricing_source'):
            raise ValueError('Saved ModelHub tariff lacks its account-price source')
        return entry
    print('\nKimi 需要账号实际单价；启动器不再请求 /api/pricing 或 /api/status。', flush=True)
    print('请从平台账号价格页填写保守上界，单位为 USD / 100万 token，包含账号倍率。', flush=True)
    print('输入价须覆盖普通输入、缓存读取和缓存写入；输出价须覆盖推理 token。', flush=True)
    print('若只知道人民币价格、按次计价或不确定，留空跳过 Kimi；不要猜价格。', flush=True)
    if not sys.stdin.isatty():
        raise ValueError('Kimi account tariff missing; run this launcher in an interactive PowerShell window')
    try:
        input_text = input('Kimi 输入单价上界 (USD / 1M tokens，留空跳过): ').strip()
        if not input_text:
            raise ValueError('Kimi skipped: account tariff has not been supplied; no Kimi generation sent')
        input_rate = number(float(input_text), 'input_per_million', positive=True)
        output_rate = number(float(input('Kimi 输出单价上界 (USD / 1M tokens): ').strip()),
                             'output_per_million', positive=True)
        source = input('价格来源（账号价格页 URL 或说明）: ').strip()
        if not source:
            raise ValueError('Kimi tariff needs an account-price source; no Kimi generation sent')
    except (EOFError, ValueError) as exc:
        raise ValueError('Kimi account tariff incomplete: ' + str(exc)) from None
    entry = {'model_id': 'kimi-k3.1-pro', 'currency': 'USD', 'hard_cap': 5.0,
        'input_per_million': input_rate, 'cached_input_per_million': input_rate,
        'cache_write_per_million': input_rate, 'output_per_million': output_rate,
        'pricing_source': source, 'verified_at_utc': e.now(),
        'rate_semantics': 'public_tariff_upper_bound_not_invoice',
        'verification_method': 'account tariff upper bounds transcribed by terminal operator',
        'scope': 'Includes account billing multipliers, cache charges and reasoning tokens; actual invoice unknown'}
    e.put(path, entry)
    return entry


def materialize_paper(batch):
    source = batch / 'bootstrap/source.pdf'
    if not source.exists():
        raw = fetch(PAPER_URL, batch / 'bootstrap', 'source.pdf', timeout=120)
    else:
        raw = source.read_bytes()
    if not raw.startswith(b'%PDF-'):
        raise ValueError('Paper source is not a PDF; do not feed an HTML error page as manuscript')
    import pymupdf
    document = pymupdf.open(stream=raw, filetype='pdf')
    pages = [{'physical_page': i+1, 'text': page.get_text(sort=True)} for i, page in enumerate(document)]
    if not pages or any(len(x['text'].strip()) < 25 for x in pages):
        raise ValueError('Incomplete paper text extraction; retain PDF and stop before paid generation')
    text = ('[Input representation: full-paper PDF text extraction. Visual figure pixels are not supplied; '
            'available captions, equations and table text follow. Do not claim visual inspection.]\n\n' +
            '\n\n'.join(f"[Source page {x['physical_page']}]\n{x['text']}" for x in pages))
    if 'Attention Is All You Need' not in text or '2017' not in text:
        raise ValueError('Unexpected manuscript identity')
    e.put(batch / 'bootstrap/extracted_pages.json', pages)
    metadata = {'source_url_or_path': PAPER_URL, 'research_id': 'arxiv_1706_03762',
        'version': 'v1', 'pdf_sha256': e.digest(raw), 'pages': len(pages),
        'source_availability': 'public arXiv preprint; retain source, no ownership assertion',
        'converter': 'PyMuPDF ' + pymupdf.VersionBind,
        'input_representation': 'whole_document_text_extraction_engineering_development_only',
        'limitations': ['Figure pixels not supplied to generation models; original PDF retained for inspection',
            'Extracted math and table layout may differ from PDF; no scientific quality claim or human conversion certification'],
        'manuscript_sha256': e.digest(text.encode('utf-8')), 'prepared_at_utc': e.now()}
    return raw, text, metadata


def configure_run(run, model_id, catalog, pricing, status, paper, provider='modelhub_cn'):
    config = e.read(run / 'config.json')
    if (run / 'frozen.json').exists():
        if config['provider'] != provider or config['model_snapshot'] != model_id:
            raise ValueError('Existing frozen run belongs to a different provider/model; preserve it and create a new run')
        return config
    if any((run / 'attempts').glob('*/started.json')):
        raise ValueError('Unfrozen existing attempts require explicit recovery; never rewrite inputs')
    pdf, text, metadata = paper
    e.put(run / 'inputs/provider_catalog.json', catalog)
    e.put(run / 'inputs/provider_pricing.json', pricing)
    e.put(run / 'inputs/provider_status.json', status)
    e.safe_write_bytes(run / 'inputs/source.pdf', pdf)
    e.safe_write_text(run / 'inputs/manuscript.txt', text)
    e.put(run / 'inputs/paper_source.json', metadata)
    config.update(provider=provider, endpoint=e.PROVIDER_ENDPOINTS[provider],
                  credential_env_var='OPENAI_API_KEY' if provider == 'openai' else 'MODELHUB_CN_API_KEY',
                  model_snapshot=model_id, model_id_status='verified_in_actual_account_catalog',
                  blocking_reason_cn=None)
    config['budget'] = (pricing if provider == 'openai' or pricing.get('currency') == 'USD'
                        else public_price_bound(pricing, status, model_id))
    e.put(run / 'inputs/provider_routing.json', {'provider': provider, 'endpoint': config['endpoint'],
        'credential_env_var': config['credential_env_var'], 'model_id': model_id,
        'catalog_source': OPENAI_CATALOG_URL if provider == 'openai' else CATALOG_URL,
        'user_steering': '还有openai的key呢',
        'reason': 'Use the existing official OpenAI credential for GPT; keep Kimi on ModelHub and keep the shared USD 5 cap.'})
    e.put(run / 'config.json', config)
    e.validate_config(config, run)
    return config


def first_slot_check(run):
    records = e.lines(run / 'records.jsonl')
    if not records:
        raise ValueError('No first scientific slot persisted')
    first = records[0]
    attempt = run / 'attempts' / first['generation_attempt_id']
    required = ('request.body.json', 'response.body.txt', 'response.meta.json', 'completed.json')
    if not all((attempt / x).is_file() for x in required):
        raise ValueError('First attempt did not preserve all raw evidence; stop before continuing')
    if e.digest(first['raw_text'].encode('utf-8')) != first['output_sha256']:
        raise ValueError('First generated review hash mismatch')
    source, registry = e.base_registry(run, e.read(run / 'config.json'), records)
    e.assert_generation_lineage(first, registry)
    e.put(run / 'first_slot_persistence_check.json', {'checked_at_utc': e.now(),
        'status': 'passed', 'record_id': first['record_id'], 'generation_status': first['status'],
        'required_raw_files': list(required), 'independent_human_review': False})


def update_batch_state(batch, results):
    summaries = {rid: e.read(e.run_path(rid) / 'summary.json') for rid in RUN_IDS}
    e.put(batch / 'execution_status.json', {'updated_at_utc': e.now(),
        'per_run': results, 'summaries': summaries,
        'shared_budget_committed_usd': sum(e.committed(e.run_path(rid)) for rid in RUN_IDS),
        'actual_api_attempts': sum(x['actual_api_attempts'] for x in summaries.values())})
    spec = importlib.util.spec_from_file_location('e0_project_writer', e.ROOT / 'scripts/project.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    state = e.read(e.ROOT / 'PROJECT_STATE.json')
    attempted = sum(x['actual_api_attempts'] for x in summaries.values())
    finished = all(x['status'] == 'e0_development_finished' for x in summaries.values())
    state['stage'] = ('development_e0_pair_finished' if finished else
        'development_e0_pair_partial' if attempted else 'development_e0_pair_blocked_before_generation')
    state['active_development_run_statuses'] = results
    state['next_actions'] = (['review the real E0 outputs, missing endpoints and cost bounds'] if attempted else
        ['read per-provider bootstrap errors; no model request has been sent']) + [
        'use the existing OPENAI_API_KEY for official GPT independently of the ModelHub pricing website',
        'resolve the separate ModelHub pricing permission without replacing its working model key',
        'keep the shared USD 5 cap; E1/B/C not automatically executed']
    helper.put(e.ROOT / 'PROJECT_STATE.json', state)


def launch():
    load_missing_user_credentials()
    batch = e.RUNS / '_batches' / BATCH_ID
    results = {}
    # Bootstrap is read-only. Individual paid runs acquire the shared budget
    # lock themselves; no duplicate alternative model dispatch path exists.
    paper = None
    plans = [(RUN_IDS[1], 'gpt-6.1-sol', 'openai', OPENAI_CATALOG_URL),
             (RUN_IDS[0], 'kimi-k3.1-pro', 'modelhub_cn', CATALOG_URL)]
    try:
        # Bootstrap failures in one provider never block the other provider.
        # GPT uses the official API key; it does not require website pricing.
        for rid, model, provider, catalog_url in plans:
            run = e.run_path(rid)
            try:
                catalog = json.loads(fetch(catalog_url, batch / 'bootstrap', provider + '_catalog.json', True))
                if not isinstance(catalog.get('data'), list):
                    raise ValueError('Account did not return a model list')
                ids = {x.get('id') for x in catalog['data'] if isinstance(x, dict)}
                if model not in ids:
                    results[rid] = {'status': 'requested_model_not_in_account_catalog',
                        'provider': provider, 'requested_model_id': model}
                    e.put(run / 'model_unavailable.json', dict(results[rid], checked_at_utc=e.now(),
                        observed_model_ids=sorted(x for x in ids if isinstance(x, str))))
                    print('Requested model unavailable on ' + provider + ': ' + model, flush=True)
                    continue
                if provider == 'openai':
                    pricing, status = official_openai_price_bound(), {'source': 'official OpenAI tariff snapshot'}
                else:
                    pricing = modelhub_price_bound(run, batch)
                    status = {'source': 'account tariff entered in local terminal; no website-backend requests'}
                if paper is None:
                    paper = materialize_paper(batch)
                configure_run(run, model, catalog, pricing, status, paper, provider)
                print('Starting first planned slot: ' + model, flush=True)
                e.run_e0(rid, limit=1)
                first_slot_check(run)
                print('First slot persisted; resuming fixed E0 schedule: ' + model, flush=True)
                summary = e.run_e0(rid)
                results[rid] = {'status': summary['status'], 'provider': provider, 'summary': summary}
            except (ValueError, OSError) as exc:
                results[rid] = {'status': 'stopped_with_preserved_evidence', 'provider': provider, 'reason': str(exc)}
                e.put(run / 'launcher_stop.json', dict(results[rid], stopped_at_utc=e.now()))
                e.report(run)
                print('Stopped ' + model + ': ' + str(exc), file=sys.stderr, flush=True)
        update_batch_state(batch, results)
        print(e.dumps({'per_run': results, 'report_directory': str(batch)}), flush=True)
        if not any(e.lines(e.run_path(rid) / 'records.jsonl') for rid in RUN_IDS):
            raise ValueError('No generation slot was reached; see the separate per-provider errors above')
    except (ValueError, OSError) as exc:
        e.put(batch / 'launcher_stop.json', {'stopped_at_utc': e.now(), 'reason': str(exc),
            'actual_generation_attempts': sum(
                e.read(p).get('kind') == 'generation' for rid in RUN_IDS
                for p in (e.run_path(rid) / 'attempts').glob('*/started.json')),
            'note': 'See per-run attempt journals for actual call counts; bootstrap GETs are not model calls.'})
        raise


if __name__ == '__main__':
    try:
        launch()
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
