"""Offline engineering tests only. Fake transport never constitutes E0 evidence."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import development_e0 as e
from development_provider import classify_http, redact


class FakeProvider:
    endpoint = e.OpenAIProvider.endpoint

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.requests = []

    def send(self, raw):
        body = json.loads(raw); self.requests.append(body)
        if self.responses:
            status, text, finish = self.responses.pop(0)
        else:
            status, finish = 200, 'stop'
            user = body['messages'][1]['content']
            if 'Classify the output status' in user:
                text = json.dumps({'status': 'success', 'terminal_no_issue': False, 'reason': 'simulated engineering review'})
            elif 'Label the provided pre-segmented blocks' in user:
                blocks = json.loads(user.split('<blocks>', 1)[1].rsplit('</blocks>', 1)[0])
                labels = [{'block_id': x['block_id'], 'role': None if x['block_type'] == 'heading' else 'N',
                           'confidence': 'medium', 'reason': 'SIMULATED label, not scientific evidence'}
                          for x in blocks if x['annotation_target']]
                text = json.dumps({'document_kind': 'review', 'labels': labels})
            else:
                text = '# SIMULATED FIXTURE\n\nThis is an engineering fixture review, not a real experimental result.\n\n- A simulated concern.'
        response = {'model': 'gpt-5.1-2025-11-13', 'id': 'SIMULATED',
            'choices': [{'message': {'content': text}, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 120, 'completion_tokens': 70,
                      'prompt_tokens_details': {'cached_tokens': 20},
                      'completion_tokens_details': {'reasoning_tokens': 0}}}
        if status != 200:
            response = {'error': {'code': 'rate_limit_exceeded'}}
        return {'http_status': status, 'raw_body': json.dumps(response).encode(),
                'request_id': 'SIMULATED', 'retry_after': None, 'transport_error': None,
                'elapsed_seconds': 0.0}


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline_e0_fixture_', dir=e.EXP)
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.config = e.proposed_config('fixture')
        self.config.update(paper_id='SIMULATED_FIXTURE', model_snapshot='gpt-5.1-2025-11-13')
        self.config['budget'].update(currency='USD', hard_cap=10,
            input_per_million=1.25, cached_input_per_million=.125, output_per_million=10,
            pricing_source='SIMULATED test rates', verified_at_utc=e.now())
        self.config['authorization'] = {'user_instruction': 'SIMULATED engineering fixture only', 'recorded_at_utc': e.now()}
        e.put(self.run / 'config.json', self.config)
        e.put(self.run / 'planned_slots.json', e.schedule())
        e.safe_write_text(self.run / 'inputs/manuscript.txt', 'SIMULATED manuscript for offline engineering tests only.')
        e.put(self.run / 'inputs/paper_source.json', {'source_url_or_path': 'SIMULATED fixture'})
        self.frozen = e.freeze(self.run, self.config)
        self.origin = patch.dict(e.BASE, fixture=True, illustrative=True, data_origin='fixture',
                                 label_source='SIMULATED_offline_test_not_model')
        self.origin.start(); self.addCleanup(self.origin.stop)
        self.sleep = patch.object(e.time, 'sleep'); self.sleep.start(); self.addCleanup(self.sleep.stop)

    def invoke(self, provider, limit=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return e.generate(self.run, self.config, provider, self.frozen, limit)

    def test_full_15_slots_lineage_blinding_and_resume(self):
        p = FakeProvider(); rows = self.invoke(p)
        self.assertEqual(len(rows), 15)
        self.assertEqual(len(p.requests), 30)  # 15 generation + 15 status
        source_id, registry = e.base_registry(self.run, self.config, rows)
        for row in rows:
            e.assert_generation_lineage(row, registry)
            request_path = self.run / 'attempts' / row['generation_attempt_id'] / 'request.body.json'
            start = e.read(request_path.with_name('started.json'))
            self.assertEqual(start['provenance']['parent_record_ids'], row['parent_record_ids'])
            user = json.loads(request_path.read_bytes())['messages'][1]['content']
            self.assertNotIn('A_LOOP', user); self.assertNotIn('A_INDEPENDENT', user)
            self.assertEqual(row['input_manuscript_record_id'], source_id)
            if row['condition'] == 'A_INDEPENDENT' or row['round'] == 0:
                self.assertIn('<prior_review>\nNONE\n</prior_review>', user)
                self.assertIsNone(row['input_review_record_id'])
            else:
                parent = registry[row['input_review_record_id']]
                self.assertEqual(parent['trajectory_id'], row['trajectory_id'])
                self.assertEqual(parent['round'], row['round']-1)
                self.assertIn(parent['raw_text'], user)
        self.invoke(p); self.assertEqual(len(p.requests), 30)
        e.annotate(self.run, self.config, p, self.frozen)
        self.assertEqual(len(p.requests), 45)
        e.annotate(self.run, self.config, p, self.frozen)
        self.assertEqual(len(p.requests), 45)
        metric = e.analysis(self.run)
        self.assertTrue(all(x['measurement_floor'] for x in metric['curves']))
        self.assertTrue(all(x['D_loop'] == 0 and x['delta_C'] == 0 for x in metric['curves']))
        summary = e.report(self.run)
        self.assertEqual(summary['actual_api_attempts'], 45)
        self.assertEqual(summary['status'], 'e0_development_finished')

    def test_first_real_slot_limit_then_resume(self):
        p = FakeProvider(); self.assertEqual(len(self.invoke(p, 1)), 1)
        self.assertEqual(len(p.requests), 2)
        self.assertEqual(len(self.invoke(p)), 15)
        self.assertEqual(len(p.requests), 30)

    def test_transient_same_payload_maximum_three_attempts(self):
        p = FakeProvider([(503, '', 'stop')]*3)
        request = e.payload(self.config, 'system', 'SIMULATED test')
        result = e.call_job(self.run, self.config, p, 'retry', request, 'generation', self.frozen)
        self.assertEqual(result['status'], 'transient_api_error')
        self.assertEqual(len(p.requests), 3)
        self.assertTrue(all(x == p.requests[0] for x in p.requests))
        e.call_job(self.run, self.config, p, 'retry', request, 'generation', self.frozen)
        self.assertEqual(len(p.requests), 3)
        self.assertGreater(e.committed(self.run), 0)
        self.assertTrue(all(e.read(x)['usage']['cost_amount'] is None for x in (self.run / 'attempts').glob('*/completed.json')))

    def test_terminal_seed_truncation_blocks_both_branches(self):
        p = FakeProvider([(200, 'SIMULATED incomplete output', 'length')])
        rows = self.invoke(p)
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[0]['status'], 'truncated')
        self.assertEqual(sum(x['trajectory_id'] == 1 for x in rows), 1)
        self.assertEqual(sum(e.read(x)['status'] == 'not_attempted' for x in (self.run / 'slots').glob('*.json')), 4)
        self.assertTrue(all(x['D_loop'] is None for x in e.analysis(self.run)['curves']))

    def test_budget_is_checked_before_dispatch(self):
        p = FakeProvider(); self.config['budget']['hard_cap'] = .00001
        with self.assertRaises(e.BudgetStop):
            e.call_job(self.run, self.config, p, 'budget', e.payload(self.config, 's', 'u'), 'generation', self.frozen)
        self.assertEqual(p.requests, [])
        self.assertFalse((self.run / 'attempts').exists())

    def test_frozen_input_and_missing_authorization_rejected(self):
        self.config['budget']['hard_cap'] = None
        with self.assertRaises(ValueError):
            e.validate_config(self.config, self.run)
        self.config['budget']['hard_cap'] = 10
        e.safe_write_text(self.run / 'inputs/manuscript.txt', 'changed')
        with self.assertRaisesRegex(ValueError, 'Frozen run content changed'):
            e.freeze(self.run, self.config)

    def test_saved_response_crash_recovery_never_resends(self):
        p = FakeProvider(); request = e.payload(self.config, 'system', 'SIMULATED')
        with patch.object(e, 'finish_attempt', side_effect=RuntimeError('simulated crash')):
            with self.assertRaises(RuntimeError):
                e.call_job(self.run, self.config, p, 'crash', request, 'generation', self.frozen)
        self.assertEqual(len(p.requests), 1)
        result = e.call_job(self.run, self.config, p, 'crash', request, 'generation', self.frozen)
        self.assertEqual(len(p.requests), 1)
        self.assertTrue(result['recovered_from_saved_response'])

    def test_inflight_ambiguity_does_not_resend(self):
        p = FakeProvider(); request = e.payload(self.config, 'system', 'SIMULATED')
        with patch.object(p, 'send', side_effect=RuntimeError('simulated process death')):
            with self.assertRaises(RuntimeError):
                e.call_job(self.run, self.config, p, 'inflight', request, 'generation', self.frozen)
        with self.assertRaisesRegex(ValueError, 'Unresolved in-flight'):
            e.call_job(self.run, self.config, p, 'inflight', request, 'generation', self.frozen)
        self.assertEqual(len(p.requests), 0)
        self.assertGreater(e.committed(self.run), 0)

    def test_invalid_annotation_preserves_missing_endpoint(self):
        p = FakeProvider(); self.invoke(p, 1)
        broken = FakeProvider([(200, '{}', 'stop'), (200, '{}', 'stop')])
        e.annotate(self.run, self.config, broken, self.frozen)
        self.assertEqual(len(broken.requests), 2)
        self.assertEqual(broken.requests[0], broken.requests[1])
        row = e.read(next((self.run / 'annotations').glob('*.json')))
        self.assertIsNone(row['sequence'])
        self.assertEqual(row['status'], 'annotation_validation_error')

    def test_credentials_redacted_and_nonretryable_quota(self):
        with patch.dict(os.environ, TEST_API_KEY='SIMULATED_SECRET_KEY_123'):
            self.assertEqual(redact(b'x SIMULATED_SECRET_KEY_123 x'), b'x [REDACTED] x')
        result = {'http_status': 429, 'raw_body': b'{"error":{"code":"insufficient_quota"}}', 'transport_error': None}
        self.assertEqual(classify_http(result), 'provider_terminal_error')

    def test_metrics_numerical_contrast_and_no_denominator_shrink(self):
        # Prescribed symbolic sequences: three distinct seeds, loop all equal,
        # independent identical to baseline. Expected D0=2/3, C_loop=2/3.
        rows = []
        seed = [['S', 'N', 'A'], ['S', 'P', 'V'], ['S', 'Q', 'M']]
        for slot in e.schedule():
            rows.append(dict(slot, status='success'))
            seq = seed[slot['trajectory_id']-1] if slot['round'] == 0 or slot['condition'] == 'A_INDEPENDENT' else ['S', 'N', 'A']
            e.put(self.run / 'annotations' / (slot['slot_id'] + '.json'), {'status': 'success', 'sequence': seq})
        for row in rows:
            e.journal(self.run / 'records.jsonl', row)
        metrics = e.analysis(self.run)['curves']
        self.assertAlmostEqual(metrics[0]['D_loop'], 2/3)
        self.assertAlmostEqual(metrics[2]['C_loop'], 2/3)
        self.assertAlmostEqual(metrics[2]['C_independent'], 0)
        self.assertAlmostEqual(metrics[2]['delta_C'], 2/3)
        e.put(self.run / 'annotations/A_LOOP_k1_t2.json', {'status': 'success', 'sequence': None})
        last = e.analysis(self.run)['curves'][2]
        self.assertIsNone(last['D_loop']); self.assertIsNone(last['delta_C'])
        self.assertEqual(last['available_loop'], 2)

    def test_os_lock_rejects_second_coordinator(self):
        with e.locked(self.run):
            with self.assertRaises(ValueError):
                with e.locked(self.run):
                    pass

    def test_requested_defaults_omit_sampling_and_reasoning_overrides(self):
        c = dict(self.config, model_snapshot='gpt-6.1-sol', inference_profile='provider_default_v1',
            model_revision_precision='published_alias_immutable_revision_not_exposed',
            default_settings_source='https://developers.openai.com/api/docs/models/gpt-6.1-sol',
            sampling={'max_completion_tokens': 32768, 'stream': False},
            evaluation_sampling={'max_completion_tokens': 32768, 'stream': False})
        e.validate_config(c, self.run)
        for evaluation in (False, True):
            request = e.payload(c, 'system', 'SIMULATED', evaluation)
            self.assertNotIn('temperature', request)
            self.assertNotIn('top_p', request)
            self.assertNotIn('reasoning_effort', request)
            self.assertEqual(request['model'], 'gpt-6.1-sol')
        c['sampling'] = dict(c['sampling'], reasoning_effort='none')
        with self.assertRaisesRegex(ValueError, 'omit temperature'):
            e.validate_config(c, self.run)

    def test_openrouter_kimi_uses_existing_key_route_without_hidden_fallbacks(self):
        c = dict(self.config, provider='openrouter', model_snapshot='moonshotai/kimi-k3.1-pro',
            inference_profile='provider_default_v1', endpoint=e.PROVIDER_ENDPOINTS['openrouter'],
            model_revision_precision='published_alias_immutable_revision_not_exposed',
            default_settings_source='https://openrouter.ai/moonshotai/kimi-k3.1-pro',
            sampling={'max_completion_tokens': 32768, 'stream': False},
            evaluation_sampling={'max_completion_tokens': 32768, 'stream': False})
        e.validate_config(c, self.run)
        request = e.payload(c, 'system', 'SIMULATED')
        self.assertIs(request['provider']['allow_fallbacks'], False)
        self.assertNotIn('reasoning_effort', request)

    def test_sibling_run_consumes_the_same_total_budget(self):
        with patch.object(e, 'RUNS', self.run / 'pair_runs'):
            a, b = e.run_path('a'), e.run_path('b')
            e.put(a / 'attempts/prior/started.json', {'reserved_cost_usd': .49})
            c = dict(self.config, run_id='b', budget=dict(self.config['budget'], hard_cap=.5),
                budget_group={'batch_id': 'pair', 'run_ids': ['a', 'b'], 'hard_cap': .5})
            self.assertAlmostEqual(e.budget_committed(b, c), .49)
            provider = FakeProvider()
            with self.assertRaises(e.BudgetStop):
                e.call_job(b, c, provider, 'shared_cap', e.payload(c, 's', 'u'), 'generation', 'fixture')
            self.assertEqual(provider.requests, [])

    def test_gateway_mapping_requires_actual_catalog_evidence(self):
        c = dict(self.config, provider='modelhub_cn', model_snapshot='gpt-6.1-sol',
            inference_profile='provider_default_v1', endpoint=e.PROVIDER_ENDPOINTS['modelhub_cn'],
            model_revision_precision='published_alias_immutable_revision_not_exposed',
            default_settings_source='account catalog required',
            sampling={'max_completion_tokens': 32768, 'stream': False},
            evaluation_sampling={'max_completion_tokens': 32768, 'stream': False})
        with self.assertRaisesRegex(ValueError, 'actual account model catalog'):
            e.validate_config(c, self.run)
        e.put(self.run / 'inputs/provider_catalog.json', {'data': [{'id': 'gpt-6.1-sol'}]})
        e.validate_config(c, self.run)


if __name__ == '__main__':
    unittest.main(verbosity=2)
