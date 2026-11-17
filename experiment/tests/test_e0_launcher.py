"""Tests for live-metadata bootstrap; all inputs here are explicit fixtures."""
import sys
import io
import contextlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import development_e0 as e
import launch_e0_pair as launcher
from launch_e0_pair import public_price_bound


class LauncherTests(unittest.TestCase):
    def metadata(self):
        pricing = {'success': True, 'group_ratio': {'default': 1, 'other': 3},
            'data': [{'model_name': 'kimi-k3.1-pro', 'quota_type': 0,
                'model_ratio': 2, 'completion_ratio': 3, 'cache_ratio': .1, 'create_cache_ratio': 2}]}
        return pricing, {'data': {'quota_per_unit': 500000}}

    def test_real_schema_rates_use_upper_bound_and_preserve_unknown_invoice(self):
        pricing, site = self.metadata()
        bound = public_price_bound(pricing, site, 'kimi-k3.1-pro')
        self.assertEqual(bound['input_per_million'], 12)
        self.assertEqual(bound['output_per_million'], 36)
        self.assertEqual(bound['cache_write_per_million'], 24)
        config = dict(provider='modelhub_cn', budget=bound)
        usage = e.token_cost(config, {'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})
        self.assertIsNone(usage['cost_amount'])
        self.assertAlmostEqual(usage['cost_upper_bound_amount'], .0042)
        self.assertIn('Actual gateway charge', usage['unknown_reason'])
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_launcher_fixture_') as directory:
            run = Path(directory)
            e.put(run / 'attempts/fixture/started.json', {'reserved_cost_usd': 1})
            e.put(run / 'attempts/fixture/completed.json', {'usage': usage})
            self.assertAlmostEqual(e.committed(run), .0042)

    def test_price_information_cannot_be_invented(self):
        pricing, site = self.metadata()
        with self.assertRaises(ValueError):
            public_price_bound(pricing, {}, 'kimi-k3.1-pro')
        with self.assertRaises(ValueError):
            public_price_bound(pricing, site, 'missing-model')
        pricing['data'][0]['billing_mode'] = 'tiered_expr'
        with self.assertRaisesRegex(ValueError, 'unsupported billing expression'):
            public_price_bound(pricing, site, 'kimi-k3.1-pro')

    def test_per_request_price_is_reserved_without_fake_token_charges(self):
        pricing, site = self.metadata()
        pricing['data'][0].update(quota_type=1, model_price=.02)
        bound = public_price_bound(pricing, site, 'kimi-k3.1-pro')
        self.assertAlmostEqual(bound['per_request_upper_bound_usd'], .06)
        body = e.dumps({'messages': [{'content': 'SIMULATED'}], 'max_completion_tokens': 32768}).encode()
        self.assertAlmostEqual(e.reserve_cost({'budget': bound}, body), .06)
        usage = e.token_cost({'provider': 'modelhub_cn', 'budget': bound}, {})
        self.assertIsNone(usage['cost_amount'])
        self.assertAlmostEqual(usage['cost_upper_bound_amount'], .06)

    def test_metadata_401_retries_with_existing_key_on_same_origin(self):
        error = launcher.BootstrapHTTPError(401, launcher.PRICING_URL, False, 'fixture_error.txt')
        with patch.object(launcher, 'fetch', side_effect=[error, b'{"success":true,"data":[]}']) as fetch:
            data = launcher.fetch_metadata(launcher.PRICING_URL, Path('fixture'), 'pricing.json')
        self.assertIs(data['success'], True)
        self.assertEqual([x.kwargs['authenticated'] for x in fetch.call_args_list], [False, True])
        self.assertTrue(all(x.args[0] == launcher.PRICING_URL for x in fetch.call_args_list))

    def test_metadata_permission_error_does_not_invalidate_working_model_key(self):
        errors = [launcher.BootstrapHTTPError(401, launcher.PRICING_URL, False, 'anonymous.txt'),
                  launcher.BootstrapHTTPError(401, launcher.PRICING_URL, True, 'authenticated.txt')]
        with patch.object(launcher, 'fetch', side_effect=errors):
            with self.assertRaisesRegex(ValueError, 'do not replace the working model key'):
                launcher.fetch_metadata(launcher.PRICING_URL, Path('fixture'), 'pricing.json')

    def test_metadata_auth_never_forwards_credentials_to_paper_source(self):
        with patch.object(launcher, 'fetch') as fetch:
            with self.assertRaises(ValueError):
                launcher.fetch_metadata(launcher.PAPER_URL, Path('fixture'), 'source.pdf')
        fetch.assert_not_called()

    def test_each_model_catalog_uses_only_its_matching_credential(self):
        requests = []
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return b'{"data":[]}'
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return Response()
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_credentials_fixture_') as directory:
            with patch.dict(launcher.os.environ, {'OPENAI_API_KEY': 'OPENAI_FIXTURE_SECRET',
                    'MODELHUB_CN_API_KEY': 'MODELHUB_FIXTURE_SECRET'}):
                with patch.object(launcher.urllib.request, 'build_opener', return_value=Opener()):
                    launcher.fetch(launcher.OPENAI_CATALOG_URL, Path(directory), 'openai.json', True)
                    launcher.fetch(launcher.CATALOG_URL, Path(directory), 'modelhub.json', True)
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer OPENAI_FIXTURE_SECRET')
        self.assertEqual(requests[1].get_header('Authorization'), 'Bearer MODELHUB_FIXTURE_SECRET')

    def test_gateway_price_failure_cannot_block_official_openai_run(self):
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_providers_fixture_') as directory:
            def fake_fetch(url, *args, **kwargs):
                model = 'gpt-6.1-sol' if url == launcher.OPENAI_CATALOG_URL else 'kimi-k3.1-pro'
                return json.dumps({'data': [{'id': model}]}).encode()
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(e, 'RUNS', Path(directory)))
                stack.enter_context(patch.object(launcher, 'load_missing_user_credentials'))
                stack.enter_context(patch.object(launcher, 'fetch', side_effect=fake_fetch))
                stack.enter_context(patch.object(launcher, 'official_openai_price_bound', return_value={'fixture': True}))
                stack.enter_context(patch.object(launcher, 'modelhub_price_bound', side_effect=ValueError('FIXTURE account tariff missing')))
                website_fetch = stack.enter_context(patch.object(launcher, 'fetch_metadata'))
                stack.enter_context(patch.object(launcher, 'materialize_paper', return_value=('FIXTURE',)*3))
                configure = stack.enter_context(patch.object(launcher, 'configure_run'))
                run = stack.enter_context(patch.object(e, 'run_e0', return_value={'status': 'FIXTURE_finished'}))
                stack.enter_context(patch.object(launcher, 'first_slot_check'))
                stack.enter_context(patch.object(e, 'report'))
                stack.enter_context(patch.object(e, 'lines', return_value=[{'fixture': True}]))
                update = stack.enter_context(patch.object(launcher, 'update_batch_state'))
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    launcher.launch()
            self.assertEqual(configure.call_count, 1)
            self.assertEqual(configure.call_args.args[-1], 'openai')
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].kwargs, {'limit': 1})
            result = update.call_args.args[1]
            self.assertEqual(result[launcher.RUN_IDS[1]]['status'], 'FIXTURE_finished')
            self.assertEqual(result[launcher.RUN_IDS[0]]['status'], 'stopped_with_preserved_evidence')
            website_fetch.assert_not_called()

    def test_account_tariff_is_persisted_and_resumed_without_reasking(self):
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_account_price_fixture_') as directory:
            root = Path(directory)
            with patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                    patch('builtins.input', side_effect=['2', '10', 'FIXTURE account tariff']):
                with contextlib.redirect_stdout(io.StringIO()):
                    price = launcher.modelhub_price_bound(root / 'run', root / 'batch')
            with patch('builtins.input', side_effect=AssertionError('must resume saved evidence')):
                self.assertEqual(launcher.modelhub_price_bound(root / 'run', root / 'batch'), price)
            self.assertEqual(price['cache_write_per_million'], 2)
            usage = e.token_cost({'provider': 'modelhub_cn', 'budget': price},
                {'usage': {'prompt_tokens': 1000, 'completion_tokens': 100}})
            self.assertIsNone(usage['cost_amount'])
            self.assertAlmostEqual(usage['cost_upper_bound_amount'], .003)

    def test_blank_account_tariff_cannot_dispatch_or_create_fake_prices(self):
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_missing_price_fixture_') as directory:
            root = Path(directory)
            with patch.object(launcher.sys.stdin, 'isatty', return_value=True), \
                    patch('builtins.input', return_value=''), \
                    patch.object(launcher, 'fetch') as fetch, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'no Kimi generation sent'):
                    launcher.modelhub_price_bound(root / 'run', root / 'batch')
            fetch.assert_not_called()
            self.assertFalse((root / 'batch/bootstrap/modelhub_account_price_bound.json').exists())

    def test_official_long_context_tariff_is_included_in_cost_upper_bound(self):
        budget = {'input_per_million': 2, 'cached_input_per_million': .1,
            'cache_write_per_million': 2.5, 'output_per_million': 10,
            'long_context_input_threshold_tokens': 272000, 'long_context_input_multiplier': 2,
            'long_context_output_multiplier': 1.5,
            'rate_semantics': 'public_tariff_upper_bound_not_invoice'}
        config = {'provider': 'openai', 'budget': budget}
        usage = e.token_cost(config, {'usage': {'prompt_tokens': 300000, 'completion_tokens': 1000}})
        self.assertIsNone(usage['cost_amount'])
        self.assertAlmostEqual(usage['cost_upper_bound_amount'], 1.515)


if __name__ == '__main__':
    unittest.main(verbosity=2)
