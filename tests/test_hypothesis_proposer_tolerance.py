import unittest

from core.hypothesis_proposer_llm import ProposedHypothesis, _prune_malformed_evidence_items


class HypothesisProposerToleranceTest(unittest.TestCase):
    def test_payload_fixer_drops_evidence_without_description(self) -> None:
        payload = {
            "statement": "补充假设",
            "evidence_items": [
                {"evidence_type": "physical_reasoning"},
                {"description": "   ", "evidence_type": "literature"},
                {"description": "有效证据", "evidence_type": "physical_prior"},
                "not-a-dict",
            ],
        }
        cleaned = _prune_malformed_evidence_items(payload)
        self.assertEqual(len(cleaned["evidence_items"]), 1)
        self.assertEqual(cleaned["evidence_items"][0]["description"], "有效证据")

    def test_supplement_model_accepts_cleaned_payload_with_empty_evidence(self) -> None:
        payload = {
            "statement": "补充假设",
            "predictions": [],
            "falsification_conditions": [],
            "alternative_explanations": [],
            "evidence_items": [
                {"evidence_type": "physical_reasoning"},
                {"evidence_type": "literature"},
            ],
        }
        proposal = ProposedHypothesis.model_validate(
            _prune_malformed_evidence_items(payload)
        )
        self.assertEqual(proposal.evidence_items, [])


if __name__ == "__main__":
    unittest.main()
