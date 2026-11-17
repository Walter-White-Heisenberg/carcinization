"""Independent ten-update development run, reusing the archived E0 engine.

No historical source or run is changed. A private module instance supplies
the existing request journal, parent checks, retry, recovery and annotation
functions with explicit E1 schedule/validation/analysis hooks. This is not the
formal six-paper pilot or a substitute for its human evidence requirements.
"""
from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import io
import math
from pathlib import Path

import development_e0 as base

PROFILE = 'carcinization_e1_development_v1'
SOURCE_RUN = 'e0_20261117_gpt61_default_001'
DEFAULT_RUN = 'e1_20261118_gpt61_default_001'
HISTORICAL_RUNS = [
    'e0_20261116_gpt61_default_001', 'e0_20261116_kimi31_default_001',
    'e0_20261117_gpt61_default_001', 'e0_20261117_kimi31_default_001',
]
POLICY = {
    'evidence_class': 'diagnostic_only', 'formal_pilot': False,
    'structural_measurement': 'automatic_P00E_P09_same_model_not_human_verified',
    'quality_audit': 'separate_exploratory_AI_source_audit_no_human_substitution',
    'gold_issue_recall': 'not_available_without_a_pre_generation_verified_denominator',
    'article_quality_change': 'not_applicable_manuscript_is_fixed',
    'fixed_updates': 10, 'experimental_unit': 'paper',
    'stopping': 'fixed_schedule_or_recorded_failure_or_budget_stop_never_result_direction',
}


def schedule():
    slots = [{'slot_id': f'seed_k{k}', 'trajectory_id': k, 'round': 0,
              'condition': 'A_LOOP'} for k in range(1, 4)]
    for t in range(1, 11):
        for k in range(1, 4):
            groups = ['A_LOOP', 'A_INDEPENDENT']
            if (t + k) % 2:
                groups.reverse()
            slots += [{'slot_id': f'{g}_k{k}_t{t}', 'trajectory_id': k,
                       'round': t, 'condition': g} for g in groups]
    return slots


def historical_cost(config):
    ids = config['historical_budget_run_ids']
    if ids != HISTORICAL_RUNS or config['run_id'] in ids:
        raise ValueError('Historical cost scope changed or includes the current run')
    return sum(base.committed(base.run_path(rid)) for rid in ids)


def validate_config(config, run):
    if (config.get('stage'), config.get('profile')) != ('E1', PROFILE):
        raise ValueError('This entry requires the explicit E1 development profile')
    if (config.get('trajectories'), config.get('updates'),
            config.get('planned_generation_slots')) != (3, 10, 63):
        raise ValueError('E1 requires three trajectories, ten updates, and 63 slots')
    if config.get('conditions') != ['A_LOOP', 'A_INDEPENDENT'] or config.get('generation_prompt') != 'P01':
        raise ValueError('E1 conditions or generation prompt changed')
    if (config.get('evidence_class') != 'diagnostic_only'
            or config.get('paper_split') != 'development'
            or any(config.get(key) is not False for key in
                   ('pilot_outputs', 'human_primary_endpoint_claim', 'confirmatory_claim', 'full_pilot_activation_applies'))
            or config.get('evidence_policy') != POLICY):
        raise ValueError('E1 cannot claim formal pilot or human evidence')
    if config.get('budget_group'):
        raise ValueError('The historical paired-E0 budget group is not an E1 group')
    if (config.get('provider'), config.get('model_snapshot'), config.get('endpoint'),
            config.get('credential_env_var')) != (
                'openai', 'gpt-6.1-sol', base.PROVIDER_ENDPOINTS['openai'], 'OPENAI_API_KEY'):
        raise ValueError('E1 must preserve the previously selected official GPT route')
    if (config.get('inference_profile') != 'provider_default_v1'
            or config.get('model_revision_precision') != 'published_alias_immutable_revision_not_exposed'
            or not config.get('default_settings_source')):
        raise ValueError('Record actual default settings and alias precision')
    for key in ('sampling', 'evaluation_sampling'):
        if config.get(key) != {'max_completion_tokens': 32768, 'stream': False}:
            raise ValueError('Preserve E0 default sampling and output limit')
    if (config.get('annotation') != base.proposed_config('validation')['annotation']
            or config.get('generation_retry_limit') != 2):
        raise ValueError('Retry or automatic annotation rules changed')
    auth = config.get('authorization', {})
    if not all(auth.get(k) for k in ('user_instruction', 'recorded_at_utc', 'budget_instruction')):
        raise ValueError('Record the user instruction and explicit budget instruction before sending')
    budget = config['budget']
    for key in ('hard_cap', 'input_per_million', 'cached_input_per_million', 'output_per_million'):
        value = budget.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Missing valid USD budget/rate: ' + key)
    if budget.get('currency') != 'USD' or budget['hard_cap'] <= historical_cost(config):
        raise ValueError('Combined cap must exceed all retained historical costs')
    if not budget.get('pricing_source') or not budget.get('verified_at_utc'):
        raise ValueError('Current provider pricing evidence is required')
    if not (run / 'frozen.json').exists() and budget.get('source_verified_on_utc_date') != base.now()[:10]:
        raise ValueError('Recheck official prices on the UTC date of the first dispatch')
    if base.read(run / 'planned_slots.json') != schedule():
        raise ValueError('Fixed E1 call order changed')
    manuscript = run / 'inputs/manuscript.txt'
    source = run / 'inputs/paper_source.json'
    if not manuscript.is_file() or not source.is_file() or not base.read(source).get('source_url_or_path'):
        raise ValueError('Run-local manuscript and source provenance are required')
    if base.digest(manuscript.read_bytes()) != config.get('manuscript_sha256'):
        raise ValueError('Prepared manuscript changed')
    canonical = next(p['text'] for p in base.CATALOG_PROMPTS if p['id'] == 'P01')
    if (base.EXP / 'prompts/P01.txt').read_text('utf8').rstrip('\n') != canonical.rstrip('\n'):
        raise ValueError('Generation P01 differs from canonical catalog')


def prepare(run_id=DEFAULT_RUN):
    run = base.run_path(run_id)
    with base.locked(run):
        if (run / 'config.json').exists():
            return run
        origin = base.run_path(SOURCE_RUN)
        prior = base.read(origin / 'config.json')
        config = base.proposed_config(run_id)
        for key in ('paper_id', 'paper_source', 'model_snapshot', 'provider',
                    'credential_env_var', 'endpoint', 'inference_profile',
                    'model_revision_precision', 'default_settings_source',
                    'sampling', 'evaluation_sampling', 'timeout_seconds'):
            config[key] = prior[key]
        config.pop('recommendation_only', None)
        config.update(stage='E1', profile=PROFILE, updates=10, planned_generation_slots=63,
                      historical_budget_run_ids=HISTORICAL_RUNS, evidence_policy=POLICY,
                      source_development_run=SOURCE_RUN, old_generated_texts_reused=False)
        config['budget'] = dict(prior['budget'], hard_cap=None)
        config['authorization'] = {
            'user_instruction': 'repo创建好了你可以继续跑实验了',
            'push_instruction': '记得跑完实验结果push一波',
            'recorded_at_utc': base.now(), 'budget_instruction': None,
            'scope': 'Fresh fixed-ten-update E1; no reuse of E0 generated reviews; cumulative USD cap remains to be specified.',
        }
        for name in ('manuscript.txt', 'paper_source.json', 'source.pdf'):
            base.safe_write_bytes(run / 'inputs' / name, (origin / 'inputs' / name).read_bytes())
        config['manuscript_sha256'] = base.digest((run / 'inputs/manuscript.txt').read_bytes())
        base.put(run / 'planned_slots.json', schedule())
        base.put(run / 'config.json', config)
        base.put(run / 'preparation.json', {
            'status': 'prepared_budget_pending_no_dispatch', 'prepared_at_utc': base.now(),
            'run_id': run_id, 'planned_generation_slots': 63, 'actual_api_attempts': 0,
            'historical_conservative_committed_usd': historical_cost(config),
            'evidence_policy': POLICY,
        })
        report(run)
    return run


def analysis(run):
    config = base.read(run / 'config.json')
    records = base.lines(run / 'records.jsonl')
    sequences = {}
    for row in records:
        path = run / 'annotations' / (row['slot_id'] + '.json')
        label = base.read(path) if path.exists() else {}
        sequences[row['slot_id']] = label.get('sequence') if row['status'] == 'success' and label.get('status') == 'success' else None
    curves = []
    for t in range(11):
        point = {'round': t, 'expected_trajectories': 3, 'human_verified': False}
        for group, suffix in (('A_LOOP', 'loop'), ('A_INDEPENDENT', 'independent')):
            seqs = [sequences.get(f'seed_k{k}' if t == 0 else f'{group}_k{k}_t{t}') for k in (1, 2, 3)]
            point['available_' + suffix] = sum(bool(s) for s in seqs)
            point['D_' + suffix] = base.mean_pairwise_edit(seqs, expected_k=3)
            point['pairs_' + suffix] = [
                {'left': i + 1, 'right': j + 1,
                 'distance': base.normalized_edit(seqs[i], seqs[j]) if seqs[i] and seqs[j] else None}
                for i, j in ((0, 1), (0, 2), (1, 2))]
        curves.append(point)
    for point in curves:
        point['C_loop'] = base.contraction(curves[0]['D_loop'], point['D_loop'])
        point['C_independent'] = base.contraction(curves[0]['D_independent'], point['D_independent'])
        point['delta_C'] = base.extra_contraction(curves[0]['D_loop'], point['D_loop'], curves[0]['D_independent'], point['D_independent'])
        point['measurement_floor'] = None if curves[0]['D_loop'] is None else curves[0]['D_loop'] == 0
        point['missing_reason'] = 'Fewer than three successful, fully labeled trajectories' if point['D_loop'] is None or point['D_independent'] is None else None
    result = {'run_id': config['run_id'], 'evidence_class': 'diagnostic_only',
              'n_papers': int(bool(records)), 'human_endpoint_status': 'not_performed',
              'label_source': POLICY['structural_measurement'], 'curves': curves,
              'interpretation_limit': 'One fixed development paper, ten updates; descriptive automatic measurement, no general convergence or quality claim.'}
    base.put(run / 'analysis/metrics.json', result)
    fields = ['round', 'expected_trajectories', 'available_loop', 'available_independent',
              'D_loop', 'D_independent', 'C_loop', 'C_independent', 'delta_C', 'measurement_floor', 'missing_reason']
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fields, extrasaction='ignore')
    writer.writeheader(); writer.writerows(curves)
    base.safe_write_text(run / 'analysis/metrics.csv', stream.getvalue())
    return result


def report(run):
    config = base.read(run / 'config.json')
    result = analysis(run)
    starts = [base.read(p) for p in (run / 'attempts').glob('*/started.json')]
    records = base.lines(run / 'records.jsonl')
    good = sum(row['status'] == 'success' for row in records)
    skipped = sum(base.read(p).get('status') == 'not_attempted' for p in (run / 'slots').glob('*.json'))
    labels = [base.read(p) for p in (run / 'annotations').glob('*.json')]
    complete = len(records) + skipped == 63 and len(labels) == good
    summary = {'run_id': config['run_id'], 'updated_at_utc': base.now(),
               'status': 'e1_development_finished' if complete else 'partial' if starts else 'prepared_budget_pending',
               'evidence_class': 'diagnostic_only', 'planned_generation_slots': 63,
               'successful_generation_slots': good, 'terminal_failed_slots': len(records) - good,
               'not_attempted_descendant_slots': skipped, 'uncompleted_slots': 63 - len(records) - skipped,
               'annotated_successful_slots': sum(a.get('status') == 'success' for a in labels),
               'annotation_failed_or_unresolved_slots': sum(a.get('status') != 'success' for a in labels),
               'actual_api_attempts': len(starts), 'human_annotations': 0,
               'conservative_budget_committed_usd': base.committed(run),
               'combined_conservative_budget_committed_usd': historical_cost(config) + base.committed(run)}
    base.put(run / 'summary.json', summary)
    fmt = lambda v: '缺失' if v is None else f'{v:.4f}'
    table = ['| 轮次 | D 接力 | D 独立 | C 接力 | C 独立 | ΔC |', '|---|---:|---:|---:|---:|---:|']
    for point in result['curves']:
        table.append('| ' + str(point['round']) + ' | ' + ' | '.join(fmt(point[key]) for key in ('D_loop', 'D_independent', 'C_loop', 'C_independent', 'delta_C')) + ' |')
    text = '# E1 十轮开发观察\n\n' + (
        '固定一篇开发论文，重新独立生成三个共享起点；两组固定更新十轮，共 63 个生成槽。'
        '沿用原 P01、GPT 6.1 默认参数及输出限制，E0 原始结果不复用、不覆写。\n\n'
        f"状态：{summary['status']}；成功 {good}/63；已登记真实 API 尝试 {len(starts)}。"
        f"本次保守费用 USD {summary['conservative_budget_committed_usd']:.6f}；"
        f"连同全部旧记录 USD {summary['combined_conservative_budget_committed_usd']:.6f}。\n\n"
        '未观测的数值保留缺失。自动结构标签不是独立人审；质量核验单独报告，固定原稿不能用于衡量改稿质量变化。\n\n')
    text += '\n'.join(table) + '\n'
    base.safe_write_text(run / 'REPORT_CN.md', text)
    cells = ''.join('<tr><td>' + str(p['round']) + '</td>' + ''.join('<td>' + fmt(p[k]) + '</td>' for k in ('D_loop', 'D_independent', 'C_loop', 'C_independent', 'delta_C')) + '</tr>' for p in result['curves'])
    doc = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>E1 十轮开发观察</title><style>body{font:16px/1.6 sans-serif;max-width:960px;margin:32px auto}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:right}</style><h1>E1 十轮开发观察</h1><p>' + html.escape(text.split('\n\n', 1)[1].split('\n\n|', 1)[0]).replace('\n\n', '</p><p>') + '</p><table><tr><th>轮次</th><th>D 接力</th><th>D 独立</th><th>C 接力</th><th>C 独立</th><th>ΔC</th></tr>' + cells + '</table></html>'
    base.safe_write_text(run / 'REPORT_CN.html', doc)
    return summary


def engine():
    spec = importlib.util.spec_from_file_location('_carcinization_e1_engine', Path(base.__file__))
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    instance.schedule = schedule
    instance.validate_config = validate_config
    instance.analysis = analysis
    instance.report = report
    instance.budget_committed = lambda run, config: historical_cost(config) + base.committed(run)
    instance.BASE = dict(instance.BASE, rubric_version='CONV-v2.3-E1-development-v1')
    instance.FREEZE_CODE = (*instance.FREEZE_CODE, 'development_e1.py', 'resume_e0_network_recovery.py')
    return instance


def execute(run_id, limit=None, labels_only=False):
    from resume_e0_network_recovery import ConfiguredProxyProvider
    run = base.run_path(run_id)
    # Lock the shared cost scope before the run, preventing two E1 coordinators.
    with base.locked(base.RUNS / '_batches' / 'e1_shared_cost_scope'), base.locked(run):
        config = base.read(run / 'config.json')
        core = engine()
        frozen = core.freeze(run, config)  # Budget missing => stop before credential or network access.
        provider = ConfiguredProxyProvider(config['credential_env_var'], config['timeout_seconds'], config['endpoint'])
        try:
            if not labels_only:
                core.generate(run, config, provider, frozen, limit)
            if limit is None or labels_only:
                core.annotate(run, config, provider, frozen)
        except core.BudgetStop as exc:
            base.put(run / 'budget_stop.json', {'stopped_at_utc': base.now(), 'reason': str(exc),
                'combined_committed_usd': core.budget_committed(run, config), 'cap_usd': config['budget']['hard_cap']})
        finally:
            summary = report(run)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run', 'annotate', 'report'))
    parser.add_argument('--run-id', default=DEFAULT_RUN)
    parser.add_argument('--limit', type=int, choices=(1,))
    args = parser.parse_args()
    if args.command == 'prepare':
        run = prepare(args.run_id)
        print(base.dumps(base.read(run / 'summary.json')))
        return
    run = base.run_path(args.run_id)
    if args.command == 'preflight':
        validate_config(base.read(run / 'config.json'), run)
        print('E1 preflight passed; no network calls')
    elif args.command == 'report':
        with base.locked(run):
            print(base.dumps(report(run)))
    else:
        print(base.dumps(execute(args.run_id, args.limit, args.command == 'annotate')))


if __name__ == '__main__':
    main()
