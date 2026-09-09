import unittest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from src.config import RunConfig
from src.experiment import PreflightError, run_pilot

class MockResponse:
    def __init__(self, content):
        self.choices = [MagicMock(message=MagicMock(content=content), finish_reason="stop")]
        self.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        self.model = "openai/gpt-oss-120b"
        self.system_fingerprint = "mock-fp"

class TestMockE2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.env_patcher = patch.dict(os.environ, {"GROQ_API_KEY": "test-key"})
        self.env_patcher.start()
        self.config = RunConfig(
            manifest_path=os.path.join(self.temp_dir, "manifest.json"),
            schedule_path=os.path.join(self.temp_dir, "schedule.json"),
            thresholds_path=os.path.join(self.temp_dir, "thresholds.json"),
            reviewer_inputs_path=os.path.join(self.temp_dir, "reviewer.json"),
            log_path=os.path.join(self.temp_dir, "log.jsonl"),
            analysis_path=os.path.join(self.temp_dir, "analysis.json")
        )
        
    def tearDown(self):
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir)
        
    @patch('src.client.time.sleep')
    @patch('src.client.Groq')
    def test_end_to_end_mocked(self, mock_groq, mock_sleep):
        mock_client_instance = MagicMock()
        mock_groq.return_value = mock_client_instance
        
        # We need to provide valid formatted responses based on prompt.
        def side_effect(**kwargs):
            content = kwargs['messages'][0]['content']
            
            if "ESTIMATE:" in content:
                # calibration or ordinary
                return MockResponse("Blah\nESTIMATE: 100")
            elif "factors" in content and "rationale" in content and "factors_used" not in content:
                if "living_giraffes" in content:
                    return MockResponse('{"factors": {"living_giraffes": 10, "average_spots_per_giraffe": 10}, "rationale": "ok"}')
                elif "song_duration_seconds" in content:
                    return MockResponse('{"factors": {"song_duration_seconds": 10, "average_zill_strikes_per_second": 10}, "rationale": "ok"}')
                return MockResponse('{"factors": {"living_giraffes": 10, "average_spots_per_giraffe": 10}, "rationale": "ok"}')
            elif "factors_used" in content:
                if "living_giraffes" in content:
                    return MockResponse('{"factors_used": {"living_giraffes": 10, "average_spots_per_giraffe": 10}, "estimate": 100, "rationale": "ok"}')
                elif "song_duration_seconds" in content:
                    return MockResponse('{"factors_used": {"song_duration_seconds": 10, "average_zill_strikes_per_second": 10}, "estimate": 100, "rationale": "ok"}')
                return MockResponse('{"factors_used": {"living_giraffes": 10, "average_spots_per_giraffe": 10}, "estimate": 100, "rationale": "ok"}')
                
            return MockResponse("ESTIMATE: 100")
            
        mock_client_instance.chat.completions.create.side_effect = side_effect
        
        # Preflight
        run_pilot(self.config, execute=False, output_dir=self.temp_dir)
        
        # Execution
        run_pilot(self.config, execute=True, output_dir=self.temp_dir)
        
        # Check that 52 API calls were made
        self.assertEqual(mock_client_instance.chat.completions.create.call_count, 52)
        
        # Verify log has 52 successful outputs
        with open(self.config.log_path, "r") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 52)
            
        from src.analyze import analyze
        report = analyze(self.config)
        self.assertEqual(report["recommendation"]["decision"], "stop_or_pivot")
        self.assertTrue(os.path.exists(self.config.analysis_path))

        with open(self.config.thresholds_path, "r") as f:
            thresholds = json.load(f)
        self.assertEqual(len(thresholds["P01"]["source_request_ids"]), 5)
        self.assertEqual(len(thresholds["P01"]["source_output_sha256"]), 5)

        with open(self.config.reviewer_inputs_path, "r") as f:
            reviewer_inputs = json.load(f)
        self.assertEqual(set(reviewer_inputs["P01"]["reviewer_prompt_sha256"]), {"H", "L", "N"})

        original_threshold_hash = thresholds["P01"]["source_output_sha256"]["calib_P01_0"]
        thresholds["P01"]["source_output_sha256"]["calib_P01_0"] = "stale"
        with open(self.config.thresholds_path, "w") as f:
            json.dump(thresholds, f)
        with self.assertRaisesRegex(PreflightError, "Threshold source mismatch"):
            run_pilot(self.config, execute=True, output_dir=self.temp_dir)
        thresholds["P01"]["source_output_sha256"]["calib_P01_0"] = original_threshold_hash
        with open(self.config.thresholds_path, "w") as f:
            json.dump(thresholds, f)

        # Stale reviewer prompt provenance must also be rejected before reuse.
        original_prompt_hash = reviewer_inputs["P01"]["reviewer_prompt_sha256"]["H"]
        reviewer_inputs["P01"]["reviewer_prompt_sha256"]["H"] = "stale"
        with open(self.config.reviewer_inputs_path, "w") as f:
            json.dump(reviewer_inputs, f)
        with self.assertRaisesRegex(PreflightError, "Reviewer input source mismatch"):
            run_pilot(self.config, execute=True, output_dir=self.temp_dir)

        reviewer_inputs["P01"]["reviewer_prompt_sha256"]["H"] = original_prompt_hash
        with open(self.config.reviewer_inputs_path, "w") as f:
            json.dump(reviewer_inputs, f)
        self.assertEqual(mock_client_instance.chat.completions.create.call_count, 52)

        # A missing ordinary outcome must make the persisted recommendation invalid.
        with open(self.config.log_path, "r") as f:
            records = [json.loads(line) for line in f]
        records = [r for r in records if r["request_id"] != "pilot_ord_P01_H_0"]
        with open(self.config.log_path, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        report = analyze(self.config)
        self.assertEqual(report["recommendation"]["decision"], "technically_invalid")
        self.assertIn(
            "missing_calibration_or_ordinary_outcome",
            report["recommendation"]["technical_invalid_reasons"],
        )

    @patch('src.client.time.sleep')
    @patch('src.client.Groq')
    def test_end_to_end_mocked_invalid_worksheet(self, mock_groq, mock_sleep):
        mock_client_instance = MagicMock()
        mock_groq.return_value = mock_client_instance
        
        def side_effect(**kwargs):
            content = kwargs['messages'][0]['content']
            
            if "ESTIMATE:" in content:
                return MockResponse("Blah\nESTIMATE: 100")
            elif "factors" in content and "rationale" in content and "factors_used" not in content:
                # If P01, return valid. If P02, return invalid JSON
                if "song_duration_seconds" in content: # P02
                    return MockResponse('{"factors": {"invalid": 10}, "rationale": "ok"}')
                return MockResponse('{"factors": {"living_giraffes": 10, "average_spots_per_giraffe": 10}, "rationale": "ok"}')
            elif "factors_used" in content:
                return MockResponse('{"factors_used": {"living_giraffes": 10, "average_spots_per_giraffe": 10}, "estimate": 100, "rationale": "ok"}')
                
            return MockResponse("ESTIMATE: 100")
            
        mock_client_instance.chat.completions.create.side_effect = side_effect
        
        run_pilot(self.config, execute=False, output_dir=self.temp_dir)
        run_pilot(self.config, execute=True, output_dir=self.temp_dir)
        
        # P02 worksheet is invalid. So 3 P02 reviewers will be skipped.
        # So 52 - 3 = 49 API calls
        self.assertEqual(mock_client_instance.chat.completions.create.call_count, 49)
        with open(self.config.log_path, "r") as f:
            records = [json.loads(line) for line in f]
        unavailable = [r for r in records if r.get("transport_status") == "unavailable"]
        self.assertEqual(len(unavailable), 3)
        self.assertTrue(all(r["unavailable_reason"] == "invalid_source_worksheet" for r in unavailable))

if __name__ == "__main__":
    unittest.main()
