"""Prepare the user-requested two-model E0 batch without inventing API IDs.

This command does no generation. Account model catalog, actual gateway tariff
and manuscript bytes must be obtained before the existing E0 runner can send.
"""
from __future__ import annotations
import json
import os
import socket
from pathlib import Path
import development_e0 as e

BATCH_ID = 'e0_20261116_default_pair_001'
RUN_IDS = ['e0_20261116_kimi31_default_001', 'e0_20261116_gpt61_default_001']
REQUEST = '开始跑第一轮吧，分别用kimi3.1 default和gpt 6.1 default'


def prepare_pair():
    batch = e.RUNS / '_batches' / BATCH_ID
    with e.locked(batch):
        if (batch / 'manifest.json').exists() or any((e.run_path(x) / 'config.json').exists() for x in RUN_IDS):
            raise ValueError('Existing paired run: resume its evidence, do not overwrite it')
        checks = {}
        for host in ('www.tokentym.com', 'api.openai.com', 'arxiv.org'):
            try:
                addresses = sorted({x[4][0] for x in socket.getaddrinfo(host, 443)})
                checks[host] = {'status': 'resolved', 'addresses': addresses}
            except OSError as exc:
                checks[host] = {'status': 'dns_failed', 'error_number': exc.errno,
                                'error_type': type(exc).__name__}
        manifest = {
            'batch_id': BATCH_ID, 'run_ids': RUN_IDS,
            'prepared_at_utc': e.now(), 'stage': 'E0', 'evidence_class': 'diagnostic_only',
            'user_instruction': REQUEST,
            'scope': 'Two independent single-model E0 runs, one shared development manuscript; no E1/B/C',
            'planned_generation_slots_per_run': 15, 'planned_generation_slots_total': 30,
            'paper': {'title': 'Attention Is All You Need', 'version': 'arXiv:1706.03762v1',
                      'source_url': 'https://arxiv.org/pdf/1706.03762v1',
                      'local_bytes_available': False, 'sha256': None},
            'budget': {'currency': 'USD', 'hard_cap': 5.0},
            'authorization_basis': {
                'preceding_proposal': 'Attention Is All You Need arXiv v1; total USD 5 cap including evaluation/retries.',
                'reply': REQUEST,
                'interpretation': 'Instruction to start accepts the preceding paper/cap proposal and replaces the model with two requested default profiles. USD 5 applies once to the entire pair.',
                'no_budget_expansion': True},
            'provider_route': {'provider': 'modelhub_cn', 'base_url': 'https://www.tokentym.com/v1',
                'credential_env_var': 'MODELHUB_CN_API_KEY',
                'source_record': 'provider configuration supplied locally; credential source omitted from public export',
                'source_scope': 'Only the matched API endpoint and credential-variable name were reused; no other experiment data or budget reused.',
                'account_model_ids': 'not_yet_read_due_to_network',
                'actual_gateway_prices': 'not_yet_read_due_to_network'},
            'default_interpretation': 'Omit temperature, top_p, reasoning_effort and thinking overrides in both generation and evaluation; output cap 32768 is an explicit engineering limit.',
            'model_precision': 'Published model aliases do not expose immutable weight revisions; save actual returned IDs and fingerprints without inventing revisions.',
            'dispatch': 'Serial coordinator; acquire the shared batch budget lock and each run lock.',
            'status': 'blocked_before_first_generation',
            'actual_generation_calls': 0, 'actual_evaluation_calls': 0, 'known_cost_usd': 0,
        }
        e.put(batch / 'manifest.json', manifest)
        e.put(batch / 'network_diagnostics.json', {'checked_at_utc': e.now(), 'checks': checks,
            'credential_env_var': 'MODELHUB_CN_API_KEY',
            'credential_present': bool(os.getenv('MODELHUB_CN_API_KEY')),
            'secret_values_logged': False, 'paid_calls': 0})
        specs = [
            ('Kimi 3.1 default', 'kimi-k3.1-pro',
             'https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart'),
            ('GPT 6.1 default', 'gpt-6.1-sol',
             'https://developers.openai.com/api/docs/models/gpt-6.1-sol'),
        ]
        for run_id, (requested, candidate, source) in zip(RUN_IDS, specs):
            run = e.run_path(run_id)
            with e.locked(run):
                config = e.proposed_config(run_id)
                config.pop('recommendation_only')
                config.update(provider='modelhub_cn',
                    endpoint=e.PROVIDER_ENDPOINTS['modelhub_cn'],
                    credential_env_var='MODELHUB_CN_API_KEY',
                    paper_id='dev_arxiv_1706_03762_v1', paper_source=manifest['paper']['source_url'],
                    requested_model=requested, model_snapshot=None,
                    model_id_candidate=candidate, model_id_status='unverified_until_account_catalog_is_read',
                    inference_profile='provider_default_v1',
                    model_revision_precision='published_alias_immutable_revision_not_exposed',
                    default_settings_source=source,
                    default_gateway_effective_settings='not_independently_exposed',
                    sampling={'max_completion_tokens': 32768, 'stream': False},
                    evaluation_sampling={'max_completion_tokens': 32768, 'stream': False},
                    timeout_seconds=600,
                    budget_group={'batch_id': BATCH_ID, 'run_ids': RUN_IDS,
                                  'currency': 'USD', 'hard_cap': 5.0},
                    blocking_reason_cn='模型及共用 USD 5 预算已按本次启动指令登记；当前执行环境 DNS 失败，尚不能下载论文、查询网关实际模型 ID 和价格，真实生成/评估均未发送。D/C/ΔC 为缺失，不是零差异。')
                config['budget'].update(currency='USD', hard_cap=5.0)
                config['authorization'] = {'user_instruction': REQUEST, 'recorded_at_utc': e.now(),
                    'prior_proposal_and_interpretation': manifest['authorization_basis'],
                    'scope': 'Both independent E0 runs share this USD 5 total cap'}
                e.put(run / 'config.json', config)
                e.put(run / 'planned_slots.json', e.schedule())
                e.put(run / 'inputs/batch_manifest.json', manifest)
                e.put(run / 'preparation.json', {'prepared_at_utc': e.now(),
                    'status': 'blocked_by_network', 'user_scope_recorded': True,
                    'budget_cap_recorded': True, 'actual_api_attempts': 0,
                    'network_diagnostics': str(batch / 'network_diagnostics.json'),
                    'blocking_reason_cn': config['blocking_reason_cn']})
                e.safe_write_text(run / 'USER_REQUEST_CN.txt', REQUEST + '\n')
                e.report(run)
        report = '''# 两模型 E0 启动记录

用户指令：开始跑第一轮吧，分别用 kimi3.1 default 和 gpt 6.1 default。

设置：沿用上一条建议的 Attention Is All You Need（arXiv v1）；两个模型各自独立做 E0（3 起点、两条件各更新 2 轮），共 30 个计划生成槽。各 run 内固定模型；轨迹、审稿历史与标签不跨模型串用。

预算：沿用上一条启动建议的 **USD 5 两 run 合计上限**，包括生成、状态判定、标签、临时错误重试和格式重标。没有按每模型 USD 5 扩大。共用预算锁与各 run 的单协调器锁共同约束发送。

默认设置：不发送 temperature、top_p、reasoning_effort 或 thinking 覆盖参数；生成和评估一致使用各服务的默认推理/采样。32768 输出 token 是明确的工程限制。官方公开 ID 候选为 kimi-k3.1-pro / gpt-6.1-sol，仍须读真实网关账号 catalog 确认其实际 ID；不冒充已验证的网关映射。公开别名不等于不可变权重快照。

现有 API：已从本机既有调用资料匹配 ModelHub 国内接口 https://www.tokentym.com/v1 与 MODELHUB_CN_API_KEY。未复制其他项目数据、设置、费用或结果；密钥值未显示或写入。

实际结果：**真实生成 0，真实评估 0，已知费用 USD 0**。当前执行环境对网关、OpenAI 与 arXiv 均 DNS 解析失败（11001），因此没有发送论文生成请求。缺少的论文下载、账号模型表、网关价格均由这一网络问题阻塞；当前不需要重新授权预算或重新提供密钥。

测量：两 run 的 D、C、ΔC 全部为缺失。没有起点，因此尚不能判断测量地板；没有真实审稿，也没有可归为模型生成失败的文本。旧的 e0_20261116_001 准备记录保留，未伪装为本次结果。

下一步：恢复当前执行环境对网关与 arXiv 的联网；获取真实模型 ID/价格和论文输入，锁定后各验证首个计划槽落盘，再按共用 USD 5 上限串行继续。E1、B、C 不自动执行。新增适配仅获离线验证，未获独立方法复核。
'''
        e.safe_write_text(batch / 'START_REPORT_CN.md', report)
        state = e.read(e.ROOT / 'PROJECT_STATE.json')
        state.update(stage='development_e0_two_models_blocked_by_network',
            api_executor_status='development_e0_multi_provider_default_profiles_offline_tested',
            active_development_batch=str(batch.relative_to(e.ROOT)).replace('\\', '/'),
            active_development_run_ids=RUN_IDS,
            latest_development_run=str(e.run_path(RUN_IDS[-1]).relative_to(e.ROOT)).replace('\\', '/'),
            latest_development_status=e.read(e.run_path(RUN_IDS[-1]) / 'summary.json'),
            actual_model_calls=0, paid_experiment_calls=0,
            current_e0_budget={'currency': 'USD', 'hard_cap': 5.0, 'scope': 'combined_two_runs'},
            next_actions=['restore current executor DNS/network for the existing gateway and arXiv',
                'read actual gateway catalog and pricing; download the fixed development manuscript',
                'validate one planned real slot per model, then resume both E0 runs within the shared cap'])
        import importlib.util
        spec = importlib.util.spec_from_file_location('project_state_writer', e.ROOT / 'scripts/project.py')
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        helper.put(e.ROOT / 'PROJECT_STATE.json', state)
        return {'batch': str(batch), 'run_ids': RUN_IDS, 'status': manifest['status'],
                'actual_model_calls': 0, 'network': checks}


if __name__ == '__main__':
    print(json.dumps(prepare_pair(), ensure_ascii=False, indent=2))
