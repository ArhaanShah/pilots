import os
import time
import json
from groq import Groq, InternalServerError, APIConnectionError, RateLimitError
from dotenv import load_dotenv

load_dotenv()

class ExperimentClient:
    def __init__(self, model="openai/gpt-oss-120b", log_file="experiment_log.jsonl"):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY", "test_key"))
        self.model = model
        self.log_file = log_file
        self.rpm_limit = 2
        self.sleep_time = 60.0 / self.rpm_limit
        self.last_request_time = 0
        self.seed = 20260909
        self.system_prompt_allowed = False # No system prompt per protocol
        
        # Load existing checkpoints
        self.completed_requests = set()
        if os.path.exists(self.log_file):
            with open(self.log_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if 'request_id' in record:
                            self.completed_requests.add(record['request_id'])
                    except:
                        pass
                        
    def _enforce_rate_limit(self):
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.sleep_time:
            time.sleep(self.sleep_time - elapsed)
        self.last_request_time = time.time()
        
    def log_result(self, record):
        with open(self.log_file, "a") as f:
            f.write(json.dumps(record) + "\n")
            
    def generate(self, request_id, prompt):
        if request_id in self.completed_requests:
            print(f"Skipping {request_id}, already completed.")
            # Read from log to return
            with open(self.log_file, "r") as f:
                for line in f:
                    record = json.loads(line)
                    if record.get('request_id') == request_id:
                        return record['output']
            return None

        self._enforce_rate_limit()
        
        # Settings per protocol
        kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 1.0,
            "max_completion_tokens": 2048,
            "seed": self.seed
        }
        
        # reasoning_effort is conditionally applied if it's the openai model
        if "gpt" in self.model.lower() or "o1" in self.model.lower():
            # Groq Python SDK might not officially support reasoning_effort on all models yet
            # but we pass it via extra_body if needed, or directly if supported.
            kwargs["extra_body"] = {"reasoning_effort": "medium"}
            
        retries = 2
        for attempt in range(retries + 1):
            try:
                print(f"Executing {request_id} (Attempt {attempt+1})")
                response = self.client.chat.completions.create(**kwargs)
                
                output = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                
                record = {
                    "request_id": request_id,
                    "prompt": prompt,
                    "output": output,
                    "finish_reason": finish_reason,
                    "model_used": response.model,
                    "timestamp": time.time()
                }
                self.log_result(record)
                self.completed_requests.add(request_id)
                return output
                
            except RateLimitError as e:
                print(f"Rate limited. Waiting 60 seconds. {e}")
                time.sleep(60)
                # Does not count as a transport error retry
            except (InternalServerError, APIConnectionError) as e:
                print(f"Transport error: {e}")
                if attempt == retries:
                    record = {"request_id": request_id, "prompt": prompt, "error": str(e), "timestamp": time.time()}
                    self.log_result(record)
                    self.completed_requests.add(request_id)
                    return None
                time.sleep(10 * (attempt + 1))
            except Exception as e:
                # Other errors (e.g., auth) fail immediately
                print(f"Fatal error: {e}")
                raise e
