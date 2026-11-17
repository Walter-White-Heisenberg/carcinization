"""Offline recovery tests. No real API requests or scientific output."""
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
import resume_e0_network_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def test_proxy_provider_keeps_runtime_proxy_and_sends_once(self):
        class Response:
            status = 200
            headers = {'x-request-id': 'FIXTURE'}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"fixture":true}'

        class Opener:
            requests = []
            def open(self, request, timeout):
                self.requests.append(request)
                return Response()

        opener = Opener()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'FIXTURE_SECRET_VALUE'}), \
                patch.object(recovery.urllib.request, 'build_opener', return_value=opener) as build:
            provider = recovery.ConfiguredProxyProvider()
            result = provider.send(b'{"fixture":"unchanged payload"}')
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.requests[0].data, b'{"fixture":"unchanged payload"}')
        self.assertEqual(opener.requests[0].full_url, 'https://api.openai.com/v1/chat/completions')
        self.assertFalse(any(isinstance(x, recovery.urllib.request.ProxyHandler) for x in build.call_args.args))
        self.assertEqual(result['transport_profile'], recovery.REVISION)
        self.assertEqual(result['http_status'], 200)

    def test_response_loss_never_resends_or_fabricates_response_and_keeps_reservation(self):
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_lost_response_fixture_') as directory:
            run = Path(directory)
            folder = run / 'attempts/fixture'
            e.put(folder / 'started.json', {'attempt_id': 'fixture', 'kind': 'generation',
                'job_id': 'fixture_seed', 'retry_index': 0, 'reserved_cost_usd': .5})
            config = {'provider': 'openai', 'budget': {'rate_semantics': 'public_tariff_upper_bound_not_invoice'}}
            out = recovery.close_lost_response(run, config, 'fixture')
            self.assertEqual(out['status'], 'unresolved_status')
            self.assertTrue(out['provider_outcome_unknown'])
            self.assertIsNone(out['usage']['cost_amount'])
            self.assertEqual(e.committed(run), .5)
            self.assertFalse((folder / 'response.body.txt').exists())
            self.assertFalse((folder / 'response.meta.json').exists())
            self.assertEqual(recovery.close_lost_response(run, config, 'fixture'), out)

    def test_existing_raw_response_cannot_be_declared_lost(self):
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_saved_response_fixture_') as directory:
            run = Path(directory)
            folder = run / 'attempts/fixture'
            e.put(folder / 'started.json', {'kind': 'generation'})
            e.safe_write_bytes(folder / 'response.body.txt', b'FIXTURE raw response')
            with self.assertRaisesRegex(ValueError, 'Saved response evidence exists'):
                recovery.close_lost_response(run, {}, 'fixture')
            self.assertFalse((folder / 'completed.json').exists())


if __name__ == '__main__':
    unittest.main()
