"""New E0 run authorized after key refresh; old data and costs are retained.

Reuse the original coordinator and configured-proxy transport. No model,
sampling, prompt, paper, slot order or retry-policy substitution is performed.
"""
from __future__ import annotations
import argparse
import csv
import html
import importlib.util
import io
import json
import os
import urllib.request
from pathlib import Path

import development_e0 as e
from development_provider import OpenAIProvider, redact
from resume_e0_network_recovery import ConfiguredProxyProvider

BATCH_ID = 'e0_20261117_key_refresh_pair_001'
GPT_ID = 'e0_20261117_gpt61_default_001'
KIMI_ID = 'e0_20261117_kimi31_default_001'
PRIOR_IDS = ['e0_20261116_gpt61_default_001', 'e0_20261116_kimi31_default_001']
BUDGET_IDS = [GPT_ID, KIMI_ID]
ALL_BUDGET_IDS = PRIOR_IDS + BUDGET_IDS
BASE_BUDGET_COMMITTED = e.budget_committed
REQUEST = '我重新搞了一下api，你看看能不能把第一轮再跑一下'
PRICE_FILE = e.EXP / 'config/provider_pricing/openai_gpt61_20261117.json'
KEY_RECHECK = e.RUNS / '_batches/e0_20261117_key_refresh_recheck_001'


def all_budget_committed(run, config):
    # Keep the coordinator's exactly-two-run group intact; count every old
    # real attempt as an additional debit on this same original USD 5 ceiling.
    return BASE_BUDGET_COMMITTED(run, config) + sum(e.committed(e.run_path(rid)) for rid in PRIOR_IDS)


def refresh_saved_credentials():
    # User explicitly just changed the saved user key. Prefer that current value
    # to an inherited process value; do not log values or credential hashes.
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
        for name in ('OPENAI_API_KEY', 'MODELHUB_CN_API_KEY'):
            try:
                value, _ = winreg.QueryValueEx(registry, name)
            except FileNotFoundError:
                continue
            if isinstance(value, str) and value.strip():
                os.environ[name] = value.strip()


def openai_catalog(batch):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    url = 'https://api.openai.com/v1/models'
    request = urllib.request.Request(url, method='GET', headers={
        'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
        raw = redact(response.read(8 * 1024 * 1024))
    data = json.loads(raw)
    if not any(x.get('id') == 'gpt-6.1-sol' for x in data.get('data', [])):
        raise ValueError('Requested GPT model is not in the official account catalog')
    e.safe_write_bytes(batch / 'bootstrap/openai_catalog.json', raw)
    return data


def prepare():
    refresh_saved_credentials()
    batch = e.RUNS / '_batches' / BATCH_ID
    if (batch / 'manifest.json').exists():
        return batch
    price = e.read(PRICE_FILE)
    if e.now()[:10] != price['verified_on_utc_date']:
        raise ValueError('Refresh current official pricing before creating a new paid run')
    catalog = openai_catalog(batch)
    modelhub = e.read(KEY_RECHECK / 'modelhub_catalog.json')
    if any(x.get('id') == 'kimi-k3.1-pro' for x in modelhub.get('data', [])):
        raise ValueError('Kimi access changed; configure its actual account tariff instead of using the unavailable-model branch')
    manifest = {'batch_id': BATCH_ID, 'run_ids': BUDGET_IDS,
        'execution_run_ids': [GPT_ID, KIMI_ID], 'historical_cost_run_ids': PRIOR_IDS,
        'prepared_at_utc': e.now(), 'stage': 'E0', 'evidence_class': 'diagnostic_only',
        'budget': {'currency': 'USD', 'hard_cap': 5.0}, 'user_instruction': REQUEST,
        'budget_basis': 'Original combined USD 5 ceiling remains; all old known/unknown cost reservations are included.',
        'rerun_reason': 'User explicitly requests another first experiment after key refresh. New complete 15-slot E0, not replacement of selected old failed outputs.',
        'paper_prompt_sampling': 'Reuse original manuscript bytes, P01, 3 trajectories, 2 updates, provider defaults, output limit 32768.',
        'old_generated_texts_reused': False, 'prior_conservative_budget_committed_usd': sum(e.committed(e.run_path(x)) for x in PRIOR_IDS),
        'incremental_cost_estimate_usd': [1.5, 2.0],
        'scope': 'E0 only, no B/C/E1 and no scientific-quality evaluation',
        'modelhub_status': 'Authenticated current saved key is valid but requested Kimi model is absent; no replacement model selected.'}
    with e.locked(batch):
        if any((e.run_path(rid) / 'config.json').exists() for rid in (GPT_ID, KIMI_ID)):
            raise ValueError('Partial preparation exists; inspect without overwriting it')
        source = e.run_path(PRIOR_IDS[0])
        for rid, old_id in ((GPT_ID, PRIOR_IDS[0]), (KIMI_ID, PRIOR_IDS[1])):
            run = e.run_path(rid)
            config = e.read(e.run_path(old_id) / 'config.json')
            config['run_id'] = rid
            config['budget_group'] = {'batch_id': BATCH_ID, 'run_ids': BUDGET_IDS,
                'currency': 'USD', 'hard_cap': 5.0}
            config['authorization'] = {'user_instruction': REQUEST, 'recorded_at_utc': e.now(),
                'original_model_instruction': '开始跑第一轮吧，分别用kimi3.1 default和gpt 6.1 default',
                'budget': 'Original USD 5 combined ceiling including prior runs; not an additional USD 5.',
                'scope': 'Fresh E0 with identical scientific settings; no old output replacement or endpoint selection.'}
            for name in ('manuscript.txt', 'paper_source.json', 'source.pdf'):
                e.safe_write_bytes(run / 'inputs' / name, (source / 'inputs' / name).read_bytes())
            e.put(run / 'inputs/batch_manifest.json', manifest)
            e.put(run / 'planned_slots.json', e.schedule())
            if rid == GPT_ID:
                config['budget'] = dict(price['budget_rates'], currency='USD', hard_cap=5.0,
                    rate_semantics='public_tariff_upper_bound_not_invoice',
                    pricing_source=price['source'], verified_at_utc=e.now(),
                    source_verified_on_utc_date=price['verified_on_utc_date'],
                    source_verification_method=price['verification_method'])
                config['blocking_reason_cn'] = None
                e.put(run / 'inputs/provider_catalog.json', catalog)
                e.put(run / 'inputs/provider_pricing.json', price)
                e.put(run / 'inputs/provider_routing.json', {'provider': 'openai',
                    'endpoint': config['endpoint'], 'credential_env_var': 'OPENAI_API_KEY',
                    'reason': 'Same previously authorized official GPT route; current ModelHub catalog does not expose GPT 6.1.'})
            else:
                config['blocking_reason_cn'] = '已直接读取用户新保存的 key；ModelHub 模型表 HTTP 200，但仍没有 kimi-k3.1-pro。'
                e.put(run / 'inputs/provider_catalog.json', modelhub)
                e.put(run / 'model_unavailable.json', {'checked_at_utc': e.now(),
                    'requested_model': 'kimi-k3.1-pro', 'observed_model_ids': [x['id'] for x in modelhub['data']],
                    'credential_recheck': e.read(KEY_RECHECK / 'credential_recheck.json'),
                    'generation_requests_sent': 0})
            e.put(run / 'config.json', config)
            e.report(run)
        e.put(batch / 'manifest.json', manifest)
    return batch


def register_transport(run):
    original_hash = e.freeze(run, e.read(run / 'config.json'))
    paths = [Path(__file__).resolve(), Path(__file__).resolve().with_name('resume_e0_network_recovery.py')]
    version = run / 'runtime_revisions/configured_proxy_fresh_run_v1'
    expected = {p.name: e.digest(p.read_bytes()) for p in paths}
    target = version / 'revision.json'
    data = {'revision_id': 'configured_proxy_fresh_run_v1', 'base_frozen_sha256': original_hash,
        'source_files_sha256': expected, 'transport': 'ConfiguredProxyProvider; honors managed runtime proxy; redirects disabled; same raw request bytes.',
        'coordinator': 'Original development_e0.run_e0, locks, retries, lineage, annotation and analysis; budget check additionally reads all prior real costs/reservations from PRIOR_IDS.',
        'historical_cost_run_ids': PRIOR_IDS,
        'no_original_frozen_files_overwritten': True}
    if target.exists():
        saved = e.read(target)
        if any(saved.get(k) != v for k, v in data.items()):
            raise ValueError('Runtime transport revision changed')
    else:
        for p in paths:
            e.safe_write_bytes(version / 'src' / p.name, p.read_bytes())
        e.put(target, dict(data, registered_at_utc=e.now()))
    for p in paths:
        if e.digest((version / 'src' / p.name).read_bytes()) != expected[p.name]:
            raise ValueError('Saved runtime source changed')
    return target, original_hash


def final_report(batch):
    gpt = e.run_path(GPT_ID)
    summary = e.report(gpt)
    metrics = e.read(gpt / 'analysis/metrics.json')['curves']
    config = e.read(gpt / 'config.json')
    total = all_budget_committed(gpt, config)
    fmt = lambda v: '缺失' if v is None else f'{v:.4f}'
    table = ['| 轮次 | D 接力 | D 独立 | C 接力 | C 独立 | ΔC |', '|---|---:|---:|---:|---:|---:|']
    table += ['| '+str(r['round'])+' | '+' | '.join(fmt(r[k]) for k in
        ('D_loop','D_independent','C_loop','C_independent','delta_C'))+' |' for r in metrics]
    main = [
        '目的：独立重跑 E0，验证 3 轨迹、接力/无历史两条件各 2 轮及 S01–S03 自动结构测量。原论文、P01、默认采样和 32768 输出上限与上次相同。旧输出未选取或复制到新 run。',
        f"GPT：成功 {summary['successful_generation_slots']}/15 槽，终止/未决 {summary['terminal_failed_slots']} 槽，依赖停发 {summary['not_attempted_descendant_slots']} 槽；成功自动标注 {summary['annotated_successful_slots']} 份，标注失败/未决 {summary['annotation_failed_or_unresolved_slots']} 份。登记 API 尝试 {summary['actual_api_attempts']} 次，生成 {summary['generation_attempts']}、评估/标注 {summary['evaluation_attempts']}。",
        f"预算：本次保守占用 USD {summary['conservative_budget_committed_usd']:.6f}；含全部旧运行及旧未决请求预留的总占用 USD {total:.6f} / 5。公开价与用量只提供费用上界，实际账单未独立核对。",
        'Kimi：新 key 已从 Windows 用户环境直接读取，/v1/models 返回 HTTP 200、22 个型号，但没有 kimi-k3.1-pro；Kimi 生成 0 次，不替换型号或转发密钥到未确认的服务。',
        '标签来源：同一固定 GPT 模型 P00E/P09 自动功能标注，未经独立人审。正文标签不合并；完整 D 使用 3 条轨迹的 3 对标准化编辑距离均值，C=D(0)-D(t)，ΔC=C接力-C独立。任何必要端点缺失即保留缺失。',
        '解释边界：E0 两轮只能说明本次流程及自动结构表示下的变化；实验单位仍为一篇论文，不能证明长期趋同或一般规律。本文未改稿；审稿质量与文章五维质量尚未评价，E1/B/C 未运行。']
    text = '# E0 独立重跑报告（2026-11-17）\n\n'+'\n\n'.join(main[:5])+'\n\n'+'\n'.join(table)+'\n\n'+main[5]+'\n'
    e.safe_write_text(batch / 'E0_REPORT_CN.md', text)
    rows = ''.join('<tr><td>'+str(r['round'])+'</td>'+''.join('<td>'+fmt(r[k])+'</td>' for k in
        ('D_loop','D_independent','C_loop','C_independent','delta_C'))+'</tr>' for r in metrics)
    doc = '<!doctype html><meta charset="utf-8"><title>E0 独立重跑报告</title><style>body{font:15px/1.6 "Microsoft YaHei",sans-serif;max-width:980px;margin:30px auto;color:#21344b}h1{font-size:27px}table{width:100%;border-collapse:collapse;margin:16px 0}td,th{padding:9px;text-align:center;border-bottom:1px solid #cedae6}th{background:#edf3f8}img{max-width:100%}@page{size:A4;margin:12mm}@media print{body{font-size:10px;margin:0}h1{font-size:18px}img{max-height:170px}}</style><h1>E0 独立重跑报告（2026-11-17）</h1>'+''.join('<p>'+html.escape(p)+'</p>' for p in main[:5])+ \
        '<table><tr><th>轮次</th><th>D 接力</th><th>D 独立</th><th>C 接力</th><th>C 独立</th><th>ΔC</th></tr>'+rows+'</table>'+ \
        '<img src="../../'+GPT_ID+'/analysis/curves.svg" alt="三轨迹自动结构距离曲线"><p>'+html.escape(main[5])+'</p>'
    # From _batches/<batch> to development/<run> requires two parent steps.
    e.safe_write_text(batch / 'E0_REPORT_CN.html', doc)
    spec = importlib.util.spec_from_file_location('project_writer', e.ROOT / 'scripts/project.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    state = e.read(e.ROOT / 'PROJECT_STATE.json')
    state.update(stage='e0_20261117_gpt_'+summary['status'],
        active_development_batch=batch.relative_to(e.ROOT).as_posix(),
        active_development_run_ids=[GPT_ID, KIMI_ID], latest_development_run=gpt.relative_to(e.ROOT).as_posix(),
        latest_development_status=summary, shared_budget_conservative_committed_usd=total,
        latest_development_report=(batch / 'E0_REPORT_CN.html').relative_to(e.ROOT).as_posix(),
        current_e0_budget={'currency':'USD','hard_cap':5.0,'scope':'all previous and current E0 runs','run_ids':ALL_BUDGET_IDS},
        next_actions=['Review new E0 automatic structure metrics and raw evidence',
            'Kimi 3.1 must be enabled for the ModelHub key before its original requested run can proceed',
            'No automatic E1/B/C or scientific quality scoring'])
    helper.put(e.ROOT / 'PROJECT_STATE.json', state)
    e.put(batch / 'execution_status.json', {'updated_at_utc':e.now(),'gpt_summary':summary,
        'kimi_status':'requested_model_not_in_authenticated_account_catalog','shared_budget_committed_usd':total})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--limit', type=int, choices=(1,))
    args = parser.parse_args()
    batch = prepare()
    run = e.run_path(GPT_ID)
    revision, base_hash = register_transport(run)
    if args.prepare_only:
        print(e.dumps({'status':'prepared_no_generation_sent','run_id':GPT_ID,
            'budget_committed_before_run':all_budget_committed(run,e.read(run/'config.json'))}))
        return
    original_freeze = e.freeze
    def checked_revision(current_run, config):
        if original_freeze(current_run,config) != base_hash:
            raise ValueError('Original frozen run changed')
        data=e.read(revision)
        for name,sha in data['source_files_sha256'].items():
            if e.digest((e.EXP/'src'/name).read_bytes()) != sha:
                raise ValueError('Runtime revision source changed: '+name)
        return e.digest(revision.read_bytes())
    e.freeze=checked_revision
    e.OpenAIProvider=ConfiguredProxyProvider
    e.budget_committed=all_budget_committed
    try:
        e.run_e0(GPT_ID,limit=args.limit)
    finally:
        e.freeze=original_freeze
        e.OpenAIProvider=OpenAIProvider
        e.budget_committed=BASE_BUDGET_COMMITTED
        summary=final_report(batch)
        print(e.dumps(summary),flush=True)


if __name__ == '__main__':
    main()
