import unittest
import math
from src.parser import parse_estimate_line, parse_worksheet, parse_reviewer, round_sigfigs, evaluate_formula
from src.client import ExperimentClient
from src.experiment import build_schedule_and_manifest

class TestPilot(unittest.TestCase):
    def test_parse_estimate_line(self):
        self.assertEqual(parse_estimate_line("ESTIMATE: 123.45"), 123.45)
        self.assertEqual(parse_estimate_line("**ESTIMATE: 1,000**"), 1000.0)
        self.assertEqual(parse_estimate_line("_ESTIMATE: 1e6_"), 1000000.0)
        self.assertEqual(parse_estimate_line("ESTIMATE: +42"), 42.0)
        
        # Rejections
        self.assertIsNone(parse_estimate_line("ESTIMATE: 1 million"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 2 x 10^6"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 10 / 20"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: -5"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 0"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: NaN"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: Infinity"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 10-20"))
        self.assertIsNone(parse_estimate_line("Blah\nESTIMATE: 5\nBlah")) # Not on the final line
        
        # Valid if final nonempty line
        self.assertEqual(parse_estimate_line("Blah\nESTIMATE: 5\n   \n"), 5.0)

    def test_parse_worksheet_and_reviewer_json(self):
        # valid
        text = '{"factors": {"a": 10, "b": 2.5}, "rationale": "ok"}'
        self.assertEqual(parse_worksheet(text, expected_keys=['a', 'b']), {'a': 10.0, 'b': 2.5})
        
        # missing keys
        text2 = '{"factors": {"a": 10}, "rationale": "ok"}'
        self.assertIsNone(parse_worksheet(text2, expected_keys=['a', 'b']))
        
        # extra keys
        text3 = '{"factors": {"a": 10, "b": 2.5, "c": 1}, "rationale": "ok"}'
        self.assertIsNone(parse_worksheet(text3, expected_keys=['a', 'b']))
        
        # NaN / Inf
        text4 = '{"factors": {"a": NaN, "b": 2.5}, "rationale": "ok"}'
        self.assertIsNone(parse_worksheet(text4, expected_keys=['a', 'b']))
        
        text5 = '{"factors": {"a": 10, "b": 2.5}, "rationale": "ok"}'
        # constraints
        c = {"a": {"min_exclusive": 10}}
        self.assertIsNone(parse_worksheet(text5, expected_keys=['a', 'b'], constraints=c))
        c2 = {"a": {"min_inclusive": 10}}
        self.assertEqual(parse_worksheet(text5, expected_keys=['a', 'b'], constraints=c2), {'a': 10.0, 'b': 2.5})

    def test_round_sigfigs(self):
        self.assertEqual(round_sigfigs(1234567, 6), 1234570)
        self.assertEqual(round_sigfigs(0.001234567, 6), 0.00123457)

    def test_evaluate_formula(self):
        f = "living_giraffes * average_spots_per_giraffe"
        factors = {"living_giraffes": 100, "average_spots_per_giraffe": 50}
        self.assertEqual(evaluate_formula(f, factors), 5000)
        
    def test_client_seeds_and_checkpoints(self):
        client = ExperimentClient(log_file="test_log.jsonl")
        client.master_seed = "20260909"
        
        s1 = client._get_request_seed("req1")
        s2 = client._get_request_seed("req2")
        self.assertNotEqual(s1, s2)
        
        # mock complete
        client.completed_requests["req1"] = {
            "request_id": "req1",
            "protocol_version": "pilot-v2",
            "prompt_sha256": client._hash_str("prompt"),
            "requested_model": client.model,
            "settings_hash": client._hash_dict({"temperature": 1.0, "max_completion_tokens": 2048, "seed": s1, "reasoning_effort": "medium"}),
            "transport_status": "success",
            "output": "mock"
        }
        
        # should retrieve
        res = client.generate("req1", "prompt", execute=False)
        self.assertEqual(res['output'], "mock")
        
        # change prompt -> error
        with self.assertRaises(ValueError):
            client.generate("req1", "prompt2", execute=False)
            
    def test_schedule_building(self):
        client = ExperimentClient(log_file="test_log.jsonl")
        schedule = build_schedule_and_manifest(client)
        self.assertEqual(len(schedule), 52)
        
        ids = [s['request_id'] for s in schedule]
        self.assertEqual(len(set(ids)), 52)
        
        h_count = sum(1 for s in schedule if s['metadata'].get('condition') == 'H')
        l_count = sum(1 for s in schedule if s['metadata'].get('condition') == 'L')
        self.assertEqual(h_count, 10)
        self.assertEqual(l_count, 10)

if __name__ == "__main__":
    unittest.main()
