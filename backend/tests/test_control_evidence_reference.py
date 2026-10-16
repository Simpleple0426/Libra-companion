import unittest
from life_prototype.event_assimilation import control_factual_output


class ControlEvidenceTests(unittest.TestCase):
    def test_verified_receipt_owns_reference_optional_model_output_is_preserved(self):
        payload={'observation':{'id':'obs:verified'},'control_event_evidence':
            {'kind':'work','operation':'interrupt','source_event':'verified'}}
        original={'evidence_ids':['obs:typo'],'summary':'optional prose','importance':3}
        result=control_factual_output(payload,original)
        self.assertEqual(result['evidence_ids'],['obs:verified'])
        self.assertEqual(original['evidence_ids'],['obs:typo'])
        self.assertEqual(result['importance'],original['importance'])
