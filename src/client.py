import os
import time
import json
import hashlib
from groq import Groq, InternalServerError, APIConnectionError, RateLimitError
from src.config import RunConfig

class ExperimentClient:
    def __init__(self, config: RunConfig, require_api_key=False):
        key = os.getenv("GROQ_API_KEY")
        if not key and require_api_key:
            raise ValueError("GROQ_API_KEY is required for --execute")
        if not key:
            key = "mock_key"
        self.client = Groq(api_key=key)
        self.config = config
        self.sleep_time = 60.0 / self.config.requests_per_minute
        self.last_request_time = 0
        
        self.completed_requests = {}
        if os.path.exists(self.config.log_path):
            with open(self.config.log_path, "r") as f:
                for line_idx, line in enumerate(f):
                    try:
                        record = json.loads(line)
                        if 'request_id' in record:
                            req_id = record['request_id']
                            
                            # If it's a success record
                            if record.get('transport_status') == 'success':
                                if req_id in self.completed_requests:
                                    if self.completed_requests[req_id].get('transport_status') == 'success':
                                        raise ValueError(f"Conflicting successful records for {req_id} at line {line_idx+1}")
                                self.completed_requests[req_id] = record
                            else:
                                # It's a transport error record. 
                                # Only store it if we don't already have a success record
                                if req_id not in self.completed_requests or self.completed_requests[req_id].get('transport_status') != 'success':
                                    self.completed_requests[req_id] = record
                    except json.JSONDecodeError:
                        raise ValueError(f"Malformed JSONL record at line {line_idx+1}")

    def _enforce_rate_limit(self, retry_after=None):
        if retry_after is not None:
            print(f"Waiting {retry_after}s for Retry-After...")
            time.sleep(retry_after)
            self.last_request_time = time.time()
            return
            
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.sleep_time:
            time.sleep(self.sleep_time - elapsed)
        self.last_request_time = time.time()
        
    def log_result(self, record):
        # We need atomic appending or just standard file append
        with open(self.config.log_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def record_unavailable(self, request_id, metadata, reason, dependency=None):
        existing = self.completed_requests.get(request_id)
        if existing and existing.get("transport_status") in {"success", "unavailable"}:
            return existing
        record = {
            "request_id": request_id,
            "protocol_version": self.config.protocol_version,
            "phase": metadata.get("phase"),
            "q_id": metadata.get("q_id"),
            "condition": metadata.get("condition"),
            "replicate": metadata.get("replicate"),
            "requested_model": self.config.requested_model,
            "timestamp": time.time(),
            "transport_status": "unavailable",
            "unavailable_reason": reason,
            "dependency": dependency or {},
            "metadata": metadata,
        }
        self.log_result(record)
        self.completed_requests[request_id] = record
        return record
            
    def _hash_str(self, text):
        return hashlib.sha256(text.encode()).hexdigest()
        
    def _hash_dict(self, d):
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()

    def _get_request_seed(self, request_id):
        seed_hash = hashlib.sha256(f"{self.config.protocol_version}:{request_id}:{self.config.master_seed}".encode()).digest()
        return int.from_bytes(seed_hash[:4], "big") & 0x7FFFFFFF

    def generate(self, request_id, prompt, metadata=None, execute=False):
        prompt_hash = self._hash_str(prompt)
        req_seed = self._get_request_seed(request_id)
        
        gen_settings = {
            "temperature": self.config.temperature,
            "max_completion_tokens": self.config.max_completion_tokens,
            "seed": req_seed,
            "reasoning_effort": self.config.reasoning_effort
        }
        settings_hash = self._hash_dict(gen_settings)
        
        if request_id in self.completed_requests:
            rec = self.completed_requests[request_id]
            if rec.get('protocol_version') != self.config.protocol_version:
                raise ValueError(f"Version mismatch for {request_id}")
            if rec.get('prompt_sha256') != prompt_hash:
                raise ValueError(f"Prompt mismatch for {request_id}")
            if rec.get('requested_model') != self.config.requested_model:
                raise ValueError(f"Model mismatch for {request_id}")
            if rec.get('settings_hash') != settings_hash:
                raise ValueError(f"Settings mismatch for {request_id}")
                
            if rec.get('transport_status') == 'success':
                return rec
                
        if not execute:
            return None # Preflight only
            
        kwargs = {
            "model": self.config.requested_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
            "max_completion_tokens": self.config.max_completion_tokens,
            "seed": req_seed
        }
        
        if "gpt" in self.config.requested_model.lower() or "o1" in self.config.requested_model.lower():
            kwargs["extra_body"] = {"reasoning_effort": self.config.reasoning_effort}
            
        transport_retries = 0
        max_transport_retries = 2
        
        while True:
            self._enforce_rate_limit()
            try:
                print(f"Executing {request_id} (Transport Attempt {transport_retries+1})")
                response = self.client.chat.completions.create(**kwargs)
                
                output = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                usage = response.usage
                
                record = {
                    "request_id": request_id,
                    "protocol_version": self.config.protocol_version,
                    "phase": metadata.get('phase') if metadata else None,
                    "q_id": metadata.get('q_id') if metadata else None,
                    "condition": metadata.get('condition') if metadata else None,
                    "replicate": metadata.get('replicate') if metadata else None,
                    "prompt": prompt,
                    "prompt_sha256": prompt_hash,
                    "request_seed": req_seed,
                    "requested_model": self.config.requested_model,
                    "returned_model": response.model,
                    "system_fingerprint": getattr(response, 'system_fingerprint', None),
                    "settings": gen_settings,
                    "settings_hash": settings_hash,
                    "timestamp": time.time(),
                    "output": output,
                    "finish_reason": finish_reason,
                    "usage": {
                        "prompt_tokens": usage.prompt_tokens if usage else 0,
                        "completion_tokens": usage.completion_tokens if usage else 0,
                        "total_tokens": usage.total_tokens if usage else 0
                    },
                    "transport_status": "success",
                    "metadata": metadata or {}
                }
                self.log_result(record)
                self.completed_requests[request_id] = record
                return record
                
            except RateLimitError as e:
                # Does not consume a transport retry
                if self._is_daily_quota_error(e):
                    print("Daily quota exhaustion detected. Stopping cleanly.")
                    self._record_quota_exhaustion(
                        request_id, prompt_hash, settings_hash, str(e)
                    )
                    raise SystemExit(0)
                print(f"Rate limited. Waiting. {e}")
                retry_after = None
                if hasattr(e, 'response') and hasattr(e.response, 'headers'):
                    retry_after = e.response.headers.get('Retry-After')
                    if retry_after:
                        retry_after = int(retry_after)
                self._enforce_rate_limit(retry_after=retry_after or 60)
            except (InternalServerError, APIConnectionError) as e:
                print(f"Transport error: {e}")
                err_record = {
                    "request_id": request_id,
                    "protocol_version": self.config.protocol_version,
                    "prompt_sha256": prompt_hash,
                    "requested_model": self.config.requested_model,
                    "settings_hash": settings_hash,
                    "timestamp": time.time(),
                    "transport_status": "error",
                    "error_category": type(e).__name__,
                    "error_msg": str(e),
                    "attempt_number": transport_retries + 1
                }
                self.log_result(err_record)
                
                if transport_retries >= max_transport_retries:
                    print(f"Max transport retries reached for {request_id}")
                    self.completed_requests[request_id] = err_record
                    return err_record
                    
                transport_retries += 1
                time.sleep(10 * transport_retries)
            except Exception as e:
                if "quota" in str(e).lower():
                    print("Quota exhaustion detected. Stopping cleanly.")
                    self._record_quota_exhaustion(
                        request_id, prompt_hash, settings_hash, str(e)
                    )
                    raise SystemExit(0)
                print(f"Fatal error: {e}")
                raise e

    @staticmethod
    def _is_daily_quota_error(error):
        message = str(error).lower()
        daily_markers = ("daily", "per day", "tokens per day", "requests per day", "tpd", "rpd")
        return any(marker in message for marker in daily_markers)

    def _record_quota_exhaustion(self, request_id, prompt_hash, settings_hash, message):
        err_record = {
            "request_id": request_id,
            "protocol_version": self.config.protocol_version,
            "prompt_sha256": prompt_hash,
            "requested_model": self.config.requested_model,
            "settings_hash": settings_hash,
            "timestamp": time.time(),
            "transport_status": "pending_quota",
            "error_category": "daily_quota",
            "error_msg": message,
        }
        self.log_result(err_record)
        self.completed_requests[request_id] = err_record
