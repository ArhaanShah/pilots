import unittest
import math
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from src.parser import parse_estimate_line, parse_worksheet, parse_reviewer, round_sigfigs, evaluate_formula
from src.client import ExperimentClient
from src.experiment import build_schedule, validate_schedule, load_and_validate_preflight_artifacts, run_pilot, PreflightError, hash_dict, source_file_hashes
from src.config import RunConfig
from src.questions import PILOT_QUESTIONS

class TestParser(unittest.TestCase):
    def test_parse_estimate_line(self):
        self.assertEqual(parse_estimate_line("ESTIMATE: 123.45"), 123.45)
        self.assertEqual(parse_estimate_line("**ESTIMATE: 1,000**"), 1000.0)
        self.assertEqual(parse_estimate_line("_ESTIMATE: 1e6_"), 1000000.0)
        self.assertEqual(parse_estimate_line("ESTIMATE: +42"), 42.0)
        self.assertIsNone(parse_estimate_line("ESTIMATE: 1 million"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 2 x 10^6"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 10 / 20"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: -5"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 0"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: NaN"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: Infinity"))
        self.assertIsNone(parse_estimate_line("ESTIMATE: 10-20"))
        self.assertIsNone(parse_estimate_line("Blah\nESTIMATE: 5\nBlah")) 
        self.assertEqual(parse_estimate_line("Blah\nESTIMATE: 5\n   \n"), 5.0)

    def test_parse_worksheet_and_reviewer_json(self):
        text = '{"factors": {"a": 10, "b": 2.5}, "rationale": "ok"}'
        self.assertEqual(parse_worksheet(text, expected_keys=['a', 'b']), {'a': 10.0, 'b': 2.5})
        text2 = '{"factors": {"a": 10}, "rationale": "ok"}'
        self.assertIsNone(parse_worksheet(text2, expected_keys=['a', 'b']))
        text3 = '{"factors": {"a": 10, "b": 2.5, "c": 1}, "rationale": "ok"}'
        self.assertIsNone(parse_worksheet(text3, expected_keys=['a', 'b']))
        text4 = '{"factors": {"a": NaN, "b": 2.5}, "rationale": "ok"}'
        self.assertIsNone(parse_worksheet(text4, expected_keys=['a', 'b']))
        text5 = '{"factors": {"a": 10, "b": 2.5}, "rationale": "ok"}'
        c = {"a": {"min_exclusive": 10}}
        self.assertIsNone(parse_worksheet(text5, expected_keys=['a', 'b'], constraints=c))
        c2 = {"a": {"min_inclusive": 10}}
        self.assertEqual(parse_worksheet(text5, expected_keys=['a', 'b'], constraints=c2), {'a': 10.0, 'b': 2.5})

class TestPreflightRejection(unittest.TestCase):
    def setUp(self):
        self.config = RunConfig()
        self.schedule = build_schedule(self.config)
        
    def test_valid_schedule(self):
        validate_schedule(self.schedule, self.config) # Should not raise
        
    def test_51_requests(self):
        self.schedule.pop()
        with self.assertRaises(PreflightError):
            validate_schedule(self.schedule, self.config)
            
    def test_duplicate_request_id(self):
        self.schedule[1]['request_id'] = self.schedule[0]['request_id']
        with self.assertRaises(PreflightError):
            validate_schedule(self.schedule, self.config)
            
    def test_duplicate_seed(self):
        self.schedule[1]['deterministic_seed'] = self.schedule[0]['deterministic_seed']
        with self.assertRaises(PreflightError):
            validate_schedule(self.schedule, self.config)
            
    def test_missing_calibration_replicate(self):
        calib = [s for s in self.schedule if s['phase'] == 'calibration' and s['q_id'] == 'P01']
        self.schedule.remove(calib[0])
        self.schedule.append({"request_id": "dummy", "phase": "calibration", "condition": "none", "deterministic_seed": 123, "q_id": "P02", "replicate": 99})
        with self.assertRaises(PreflightError):
            validate_schedule(self.schedule, self.config)

    def test_prompt_source_change_blocks_execution_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RunConfig(
                manifest_path=os.path.join(temp_dir, "manifest.json"),
                schedule_path=os.path.join(temp_dir, "schedule.json"),
            )
            run_pilot(config, execute=False, output_dir=temp_dir)
            changed_hashes = source_file_hashes()
            changed_hashes["src/prompts.py"] = "changed"
            with patch("src.experiment.source_file_hashes", return_value=changed_hashes):
                with self.assertRaisesRegex(PreflightError, "Prompt template hash mismatch"):
                    load_and_validate_preflight_artifacts(config, temp_dir)

class TestClient(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.temp_dir, "test_log.jsonl")
        self.config = RunConfig(log_path=self.log_path)
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    def test_client_seeds_unique(self):
        client = ExperimentClient(self.config)
        seeds = set(client._get_request_seed(f"req{i}") for i in range(52))
        self.assertEqual(len(seeds), 52)
        
    def test_checkpoint_reuse(self):
        client = ExperimentClient(self.config)
        client.completed_requests["req1"] = {
            "request_id": "req1",
            "protocol_version": self.config.protocol_version,
            "prompt_sha256": client._hash_str("prompt"),
            "requested_model": self.config.requested_model,
            "settings_hash": client._hash_dict({
                "temperature": self.config.temperature,
                "max_completion_tokens": self.config.max_completion_tokens,
                "seed": client._get_request_seed("req1"),
                "reasoning_effort": self.config.reasoning_effort
            }),
            "transport_status": "success",
            "output": "mock"
        }
        res = client.generate("req1", "prompt", execute=False)
        self.assertEqual(res['output'], "mock")
        
        with self.assertRaises(ValueError):
            client.generate("req1", "prompt2", execute=False)

    def test_execute_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
                ExperimentClient(self.config, require_api_key=True)

if __name__ == "__main__":
    unittest.main()
