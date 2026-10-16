import tempfile
import unittest
from life_prototype.operational_ledger import OperationalLedger
from life_prototype.model_client import ModelError


class OperationalRecoveryTests(unittest.TestCase):
    def test_transient_failure_allows_bounded_scheduler_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = OperationalLedger(directory)
            ledger.reserve('first')
            ledger.block('CLI turn failed')
            ledger.reserve('retry')
            self.assertEqual(ledger._read()['attempts'], 2)

    def test_provider_block_requires_review_and_preserves_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = OperationalLedger(directory)
            ledger.reserve('first')
            ledger.charge_call('call-1', 3)
            ledger.block('CLI HTTP 402')
            with self.assertRaises(ModelError):
                ledger.reserve('retry')
            with self.assertRaises(ValueError):
                ledger.resume_after_review('CLI turn failed', 'authorized review')
            ledger.resume_after_review('CLI HTTP 402', 'authorized review')
            ledger.reserve('resumed')
            value = ledger._read()
            self.assertEqual(value['wall_seconds'], 3)
            self.assertEqual(value['charged_calls'], ['call-1'])
            self.assertEqual(value['reviews'][0]['previous_block'], 'CLI HTTP 402')
