"""Offline check: a fresh pair must still debit old unknown request costs."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import development_e0 as e
import rerun_e0_after_key_refresh as rerun


class RerunBudgetTests(unittest.TestCase):
    def test_old_unknown_reservation_can_stop_new_paid_request(self):
        with tempfile.TemporaryDirectory(dir=e.EXP, prefix='offline_rerun_budget_fixture_') as directory:
            with patch.object(e, 'RUNS', Path(directory)):
                old = e.run_path(rerun.PRIOR_IDS[0])
                e.put(old / 'attempts/fixture/started.json', {'reserved_cost_usd': 4.99})
                run = e.run_path(rerun.GPT_ID)
                config = e.proposed_config(rerun.GPT_ID)
                config.update(model_snapshot='gpt-6.1-sol', budget_group={
                    'batch_id':rerun.BATCH_ID, 'run_ids':rerun.BUDGET_IDS, 'hard_cap':5.0})
                config['budget'].update(currency='USD', hard_cap=5.0,
                    input_per_million=2.0, cached_input_per_million=.1, output_per_million=10.0)
                provider = Mock(endpoint=e.PROVIDER_ENDPOINTS['openai'])
                request = e.payload(config, 'SIMULATED system', 'SIMULATED user')
                self.assertEqual(rerun.all_budget_committed(run, config), 4.99)
                with patch.object(e, 'budget_committed', rerun.all_budget_committed):
                    with self.assertRaises(e.BudgetStop):
                        e.call_job(run,config,provider,'fixture_job',request,'generation','SIMULATED revision')
                provider.send.assert_not_called()
                self.assertEqual(list((run/'attempts').glob('*/started.json')), [])


if __name__ == '__main__':
    unittest.main()
