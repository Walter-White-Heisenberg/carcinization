"""Simulated E1 engineering checks; never experimental observations."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import development_e0 as base
import development_e1 as e1
from test_development_e0 import FakeProvider


class MatchingFakeProvider(FakeProvider):
    def send(self, raw):
        response = super().send(raw)
        body = json.loads(response['raw_body'])
        if response['http_status'] == 200:
            body['model'] = json.loads(raw)['model']
            response['raw_body'] = json.dumps(body).encode()
        return response


class E1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline_e1_fixture_', dir=base.EXP)
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.config = base.proposed_config('SIMULATED_E1_FIXTURE')
        self.config.update(stage='E1', profile=e1.PROFILE, paper_id='SIMULATED_MANUSCRIPT',
            updates=10, planned_generation_slots=63, model_snapshot='gpt-6.1-sol',
            inference_profile='provider_default_v1',
            model_revision_precision='published_alias_immutable_revision_not_exposed',
            default_settings_source='SIMULATED fixture default profile',
            historical_budget_run_ids=e1.HISTORICAL_RUNS, evidence_policy=e1.POLICY,
            sampling={'max_completion_tokens': 32768, 'stream': False},
            evaluation_sampling={'max_completion_tokens': 32768, 'stream': False})
        self.config['budget'].update(currency='USD', hard_cap=100,
            input_per_million=2, cached_input_per_million=.1, output_per_million=10,
            pricing_source='SIMULATED test rates', verified_at_utc=base.now(),
            source_verified_on_utc_date=base.now()[:10])
        self.config['authorization'] = {'user_instruction': 'SIMULATED fixture only',
            'recorded_at_utc': base.now(), 'budget_instruction': 'SIMULATED test budget only'}
        manuscript = b'SIMULATED offline manuscript. No scientific observations.'
        self.config['manuscript_sha256'] = base.digest(manuscript)
        base.put(self.run / 'config.json', self.config)
        base.put(self.run / 'planned_slots.json', e1.schedule())
        base.safe_write_bytes(self.run / 'inputs/manuscript.txt', manuscript)
        base.put(self.run / 'inputs/paper_source.json', {'source_url_or_path': 'SIMULATED fixture'})
        self.core = e1.engine()
        self.core.BASE.update(fixture=True, illustrative=True, data_origin='fixture',
                              label_source='SIMULATED_not_model_observations')
        self.frozen = self.core.freeze(self.run, self.config)

    def generate(self, provider, limit=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.core.generate(self.run, self.config, provider, self.frozen, limit)

    def test_full_ten_updates_lineage_blinding_resume_and_curves(self):
        provider = MatchingFakeProvider()
        rows = self.generate(provider, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(provider.requests), 2)
        rows = self.generate(provider)
        self.assertEqual(len(rows), 63)
        self.assertEqual(len(provider.requests), 126)
        _, registry = self.core.base_registry(self.run, self.config, rows)
        for row in rows:
            self.core.assert_generation_lineage(row, registry)
            request = base.read(self.run / 'attempts' / row['generation_attempt_id'] / 'request.body.json')
            user = request['messages'][1]['content']
            self.assertNotIn('A_LOOP', user)
            self.assertNotIn('A_INDEPENDENT', user)
            if row['round'] and row['condition'] == 'A_LOOP':
                parent = registry[row['input_review_record_id']]
                self.assertEqual(parent['round'], row['round'] - 1)
                self.assertEqual(parent['trajectory_id'], row['trajectory_id'])
                self.assertEqual(parent['paper_id'], row['paper_id'])
                self.assertIn(parent['raw_text'], user)
            else:
                self.assertIsNone(row['input_review_record_id'])
        self.generate(provider)
        self.assertEqual(len(provider.requests), 126)
        self.core.annotate(self.run, self.config, provider, self.frozen)
        self.assertEqual(len(provider.requests), 189)
        self.core.annotate(self.run, self.config, provider, self.frozen)
        self.assertEqual(len(provider.requests), 189)
        metrics = e1.analysis(self.run)
        self.assertEqual([p['round'] for p in metrics['curves']], list(range(11)))
        self.assertTrue(all(p['D_loop'] == 0 and p['delta_C'] == 0 for p in metrics['curves']))
        summary = e1.report(self.run)
        self.assertEqual(summary['status'], 'e1_development_finished')
        self.assertEqual(summary['actual_api_attempts'], 189)
        self.assertEqual(summary['human_annotations'], 0)

    def test_failed_seed_stops_all_twenty_descendants_and_keeps_missing(self):
        rows = self.generate(MatchingFakeProvider([(200, 'SIMULATED truncated', 'length')]))
        self.assertEqual(len(rows), 43)
        self.assertEqual(sum(r['trajectory_id'] == 1 for r in rows), 1)
        self.assertEqual(sum(base.read(p)['status'] == 'not_attempted' for p in (self.run / 'slots').glob('*.json')), 20)
        metrics = e1.analysis(self.run)
        self.assertEqual(len(metrics['curves']), 11)
        self.assertTrue(all(p['D_loop'] is None and p['delta_C'] is None for p in metrics['curves']))

    def test_missing_budget_and_stale_price_rejected_before_freezing(self):
        bad = dict(self.config, authorization={**self.config['authorization'], 'budget_instruction': None})
        with self.assertRaisesRegex(ValueError, 'explicit budget instruction'):
            e1.validate_config(bad, self.run)
        with tempfile.TemporaryDirectory(prefix='offline_e1_unfrozen_', dir=base.EXP) as other:
            stale = dict(self.config, budget={**self.config['budget'], 'source_verified_on_utc_date': '2000-01-01'})
            with self.assertRaisesRegex(ValueError, 'Recheck official prices'):
                e1.validate_config(stale, Path(other))

    def test_historical_reservation_can_stop_first_dispatch(self):
        provider = MatchingFakeProvider()
        with patch.object(e1, 'historical_cost', return_value=100):
            with self.assertRaises(self.core.BudgetStop):
                self.generate(provider)
        self.assertFalse(provider.requests)
        self.assertFalse((self.run / 'attempts').exists())

    def test_engine_hooks_do_not_mutate_old_e0_runtime(self):
        self.assertEqual(base.schedule(), e1.schedule()[:15])
        self.assertEqual(len(base.schedule()), 15)
        self.assertEqual(len(self.core.schedule()), 63)
        self.assertIsNot(base.validate_config, self.core.validate_config)
        self.assertNotIn('development_e1.py', base.FREEZE_CODE)
        self.assertIn('development_e1.py', self.core.FREEZE_CODE)


if __name__ == '__main__':
    unittest.main()
