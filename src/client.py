import os
import time
import json
import hashlib
from groq import Groq, InternalServerError, APIConnectionError, RateLimitError
from dotenv import load_dotenv

load_dotenv()

class ExperimentClient:
    def __init__(self, model="openai/gpt-oss-120b", log_file="pilot_log_v2.jsonl"):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY", "test_key"))
        self.model = model
        self.log_file = log_file
        self.rpm_limit = 2
        self.sleep_time = 60.0 / self.rpm_limit
        self.last_request_time = 0
        self.protocol_version = "pilot-v2"
        self.master_seed = "20260909"
        
        self.completed_requests = {}
        if os.path.exists(self.log_file):
            with open(self.log_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if 'request_id' in record:
                            self.completed_requests[record['request_id']] = record
                    except:
                        pass

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
        with open(self.log_file, "a") as f:
            f.write(json.dumps(record) + "\n")
            
    def _hash_str(self, text):
        return hashlib.sha256(text.encode()).hexdigest()
        
    def _hash_dict(self, d):
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()

    def _get_request_seed(self, request_id):
        # Distinct deterministic seed derived from request ID
        seed_hash = hashlib.sha256(f"{self.protocol_version}:{request_id}:{self.master_seed}".encode()).digest()
        return int.from_bytes(seed_hash[:4], "big") & 0x7FFFFFFF

    def generate(self, request_id, prompt, metadata=None, execute=False):
        prompt_hash = self._hash_str(prompt)
        req_seed = self._get_request_seed(request_id)
        
        gen_settings = {
            "temperature": 1.0,
            "max_completion_tokens": 2048,
            "seed": req_seed,
            "reasoning_effort": "medium"
        }
        settings_hash = self._hash_dict(gen_settings)
        
        if request_id in self.completed_requests:
            rec = self.completed_requests[request_id]
            # Checkpoint safe checking
            if rec.get('protocol_version') != self.protocol_version:
                raise ValueError(f"Version mismatch for {request_id}")
            if rec.get('prompt_sha256') != prompt_hash:
                raise ValueError(f"Prompt mismatch for {request_id}")
            if rec.get('requested_model') != self.model:
                raise ValueError(f"Model mismatch for {request_id}")
            if rec.get('settings_hash') != settings_hash:
                raise ValueError(f"Settings mismatch for {request_id}")
                
            # Do not return incomplete transport failures as completed!
            if rec.get('transport_status') != 'success':
                pass # Need to retry
            else:
                return rec
                
        if not execute:
            return None # Preflight only

        self._enforce_rate_limit()
        
        kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 1.0,
            "max_completion_tokens": 2048,
            "seed": req_seed
        }
        
        if "gpt" in self.model.lower() or "o1" in self.model.lower():
            kwargs["extra_body"] = {"reasoning_effort": "medium"}
            
        retries = 2
        for attempt in range(retries + 1):
            try:
                print(f"Executing {request_id} (Attempt {attempt+1})")
                response = self.client.chat.completions.create(**kwargs)
                
                output = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                
                usage = response.usage
                
                record = {
                    "request_id": request_id,
                    "protocol_version": self.protocol_version,
                    "prompt": prompt,
                    "prompt_sha256": prompt_hash,
                    "request_seed": req_seed,
                    "requested_model": self.model,
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
                print(f"Rate limited. Waiting 60 seconds. {e}")
                retry_after = None
                if hasattr(e, 'response') and hasattr(e.response, 'headers'):
                    retry_after = e.response.headers.get('Retry-After')
                    if retry_after:
                        retry_after = int(retry_after)
                self._enforce_rate_limit(retry_after=retry_after or 60)
            except (InternalServerError, APIConnectionError) as e:
                print(f"Transport error: {e}")
                if attempt == retries:
                    record = {
                        "request_id": request_id,
                        "protocol_version": self.protocol_version,
                        "prompt": prompt,
                        "prompt_sha256": prompt_hash,
                        "request_seed": req_seed,
                        "requested_model": self.model,
                        "settings": gen_settings,
                        "settings_hash": settings_hash,
                        "timestamp": time.time(),
                        "transport_status": "error",
                        "error_category": type(e).__name__,
                        "error_msg": str(e),
                        "metadata": metadata or {}
                    }
                    self.log_result(record)
                    self.completed_requests[request_id] = record
                    return record
                time.sleep(10 * (attempt + 1))
            except Exception as e:
                if "quota" in str(e).lower():
                    print("Quota exhaustion detected. Stopping cleanly.")
                    exit(1)
                print(f"Fatal error: {e}")
                raise e
        return None
