import unittest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from src.config import RunConfig
from src.experiment import run_pilot

class MockResponse:
    def __init__(self, content):
        self.choices = [MagicMock(message=MagicMock(content=content), finish_reason="stop")]
        self.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        self.model = "mock-model"
        self.system_fingerprint = "mock-fp"

class TestMockE2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = RunConfig(
            manifest_path=os.path.join(self.temp_dir, "manifest.json"),
            schedule_path=os.path.join(self.temp_dir, "schedule.json"),
            thresholds_path=os.path.join(self.temp_dir, "thresholds.json"),
            reviewer_inputs_path=os.path.join(self.temp_dir, "reviewer.json"),
            log_path=os.path.join(self.temp_dir, "log.jsonl")
        )
        
    def tearDown(self):
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
        analyze(self.config)

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

if __name__ == "__main__":
    unittest.main()
