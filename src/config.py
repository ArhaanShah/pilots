import os
from dataclasses import dataclass
from typing import Dict, Any

@dataclass(frozen=True)
class RunConfig:
    protocol_version: str = "pilot-v2"
    master_seed: str = "20260909"
    provider: str = "groq"
    requested_model: str = "openai/gpt-oss-120b"
    temperature: float = 1.0
    max_completion_tokens: int = 2048
    reasoning_effort: str = "medium"
    requests_per_minute: int = 2
    
    manifest_path: str = "pilot_manifest_v2.json"
    schedule_path: str = "pilot_schedule_v2.json"
    thresholds_path: str = "pilot_thresholds_v2.json"
    reviewer_inputs_path: str = "pilot_reviewer_inputs_v2.json"
    log_path: str = "pilot_log_v2.jsonl"
    analysis_path: str = "pilot_analysis_v2.json"
