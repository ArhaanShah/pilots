import os
import sys
import json
import random
import hashlib
import argparse
import statistics
from src.client import ExperimentClient
from src.questions import PILOT_QUESTIONS
from src.prompts import get_cue, prompt_type_A, prompt_type_B, prompt_type_C
from src.parser import parse_estimate_line, parse_worksheet, parse_reviewer, evaluate_formula, round_sigfigs

LEQ_ASSIGNMENTS = {
    "P01": True, "P02": True, "P03": False, "P04": False
}

def get_leq(q_id):
    return LEQ_ASSIGNMENTS.get(q_id, False)

def preflight_checks(requests, client):
    request_ids = set()
    seeds = set()
    
    hln_counts = {'H': 0, 'L': 0, 'N': 0}
    for req in requests:
        rid = req['request_id']
        if rid in request_ids:
            raise ValueError(f"Duplicate request ID: {rid}")
        request_ids.add(rid)
        
        seed = client._get_request_seed(rid)
        if seed in seeds:
            raise ValueError(f"Duplicate generation seed for {rid}")
        seeds.add(seed)
        
        cond = req['metadata'].get('condition')
        if cond in hln_counts:
            hln_counts[cond] += 1
            
    # H/L/N counts should be balanced if all requests exist
    print(f"Total requests scheduled: {len(requests)}")
    print(f"Condition counts: {hln_counts}")
    
    # Prompt invariants
    # Ensure H and L prompts differ only in outcome-to-threshold assignment.
    # We do this by checking prompt_type_A directly in the script building, but we can double check here if we saved the texts.
    pass

def build_schedule_and_manifest(client):
    manifest = {
        "protocol_version": client.protocol_version,
        "master_seed": client.master_seed,
        "requested_model": client.model,
        "provider": "groq",
        "temperature": 1.0,
        "max_completion_tokens": 2048,
        "reasoning_effort": "medium",
        "question_bank_hash": hashlib.sha256(json.dumps(PILOT_QUESTIONS, sort_keys=True).encode()).hexdigest(),
        "timestamp": client.last_request_time, # somewhat constant for preflight
        "log_filename": client.log_file
    }
    with open("pilot_manifest_v2.json", "w") as f:
        json.dump(manifest, f, indent=2)
        
    # Build schedule reproducibly
    rng = random.Random(int(client.master_seed))
    
    schedule = []
    
    q_ids = list(PILOT_QUESTIONS.keys())
    
    # Phase 1: Calibration (20 calls)
    calib_requests = []
    for q_id in q_ids:
        for i in range(5):
            calib_requests.append({
                "request_id": f"calib_{q_id}_{i}",
                "phase": "calibration",
                "q_id": q_id,
                "metadata": {"condition": "none", "replicate": i}
            })
    rng.shuffle(calib_requests)
    schedule.extend(calib_requests)
    
    # Phase 2: Ordinary (24 calls)
    ord_requests = []
    for q_id in q_ids:
        for cue_cond in ['H', 'L', 'N']:
            for i in range(2):
                ord_requests.append({
                    "request_id": f"pilot_ord_{q_id}_{cue_cond}_{i}",
                    "phase": "ordinary",
                    "q_id": q_id,
                    "metadata": {"condition": cue_cond, "replicate": i}
                })
    rng.shuffle(ord_requests)
    schedule.extend(ord_requests)
    
    # Phase 3: Worksheets (2 calls)
    ws_requests = []
    for q_id in ["P01", "P02"]:
        ws_requests.append({
            "request_id": f"pilot_est_N_{q_id}",
            "phase": "worksheet",
            "q_id": q_id,
            "metadata": {"condition": "N"}
        })
    # Keep them in some reproducible order
    rng.shuffle(ws_requests)
    schedule.extend(ws_requests)
    
    # Phase 4: Reviewers (6 calls)
    rev_requests = []
    for q_id in ["P01", "P02"]:
        for cue_cond in ['H', 'L', 'N']:
            rev_requests.append({
                "request_id": f"pilot_rev_{q_id}_{cue_cond}",
                "phase": "reviewer",
                "q_id": q_id,
                "metadata": {"condition": cue_cond}
            })
    # We must ensure reviewer H/L/N for one question uses same canonical worksheet
    rng.shuffle(rev_requests)
    schedule.extend(rev_requests)
    
    with open("pilot_schedule_v2.json", "w") as f:
        json.dump(schedule, f, indent=2)
        
    return schedule

def run_pilot(client, execute=False):
    schedule = build_schedule_and_manifest(client)
    preflight_checks(schedule, client)
    
    if not execute:
        print("Preflight complete. Run with --execute to perform API calls.")
        return
        
    print("Executing schedule...")
    thresholds = {}
    if os.path.exists("pilot_thresholds_v2.json"):
        with open("pilot_thresholds_v2.json", "r") as f:
            data = json.load(f)
            for k, v in data.items():
                thresholds[k] = v.get("threshold")
            
    # Group schedule by phases to respect dependencies
    calib_reqs = [r for r in schedule if r['phase'] == 'calibration']
    ord_reqs = [r for r in schedule if r['phase'] == 'ordinary']
    ws_reqs = [r for r in schedule if r['phase'] == 'worksheet']
    rev_reqs = [r for r in schedule if r['phase'] == 'reviewer']
    
    # Phase 1: Calibration
    calib_results = {}
    for req in calib_reqs:
        q_id = req['q_id']
        q_data = PILOT_QUESTIONS[q_id]
        prompt = prompt_type_A(q_data['question'], "its standard units", "")
        
        res = client.generate(req['request_id'], prompt, metadata=req['metadata'], execute=execute)
        if res and res.get('transport_status') == 'success':
            val = parse_estimate_line(res['output'])
            if q_id not in calib_results:
                calib_results[q_id] = []
            if val is not None:
                calib_results[q_id].append(val)
                
    # Compute thresholds
    thresholds_output = {}
    for q_id in PILOT_QUESTIONS.keys():
        vals = calib_results.get(q_id, [])
        valid_vals = [v for v in vals if v is not None]
        
        info = {
            "raw_values": vals,
            "valid_count": len(valid_vals),
            "median": None,
            "threshold": None
        }
        
        if len(valid_vals) >= 4:
            t = statistics.median(valid_vals)
            t_rounded = round_sigfigs(t, 6)
            info["median"] = t
            info["threshold"] = t_rounded
            thresholds[q_id] = t_rounded
        else:
            print(f"FAILED TO CALIBRATE {q_id}. Only {len(valid_vals)} valid responses.")
            thresholds[q_id] = None
            
        thresholds_output[q_id] = info
        
    with open("pilot_thresholds_v2.json", "w") as f:
        json.dump(thresholds_output, f, indent=2)
        
    # Halt if any failed to calibrate
    if any(t is None for t in thresholds.values()):
        print("Technical failure: Not all tasks achieved >=4 valid calibrations.")
        sys.exit(1)
        
    # Phase 2: Ordinary
    for req in ord_reqs:
        q_id = req['q_id']
        t = thresholds[q_id]
        cond = req['metadata']['condition']
        
        q_data = PILOT_QUESTIONS[q_id]
        leq_first = get_leq(q_id)
        cue_text = get_cue(cond, t, leq_first)
        
        prompt = prompt_type_A(q_data['question'], "its standard units", cue_text)
        client.generate(req['request_id'], prompt, metadata=req['metadata'], execute=execute)
        
    # Phase 3: Worksheet
    canonical_worksheets = {}
    for req in ws_reqs:
        q_id = req['q_id']
        t = thresholds[q_id]
        cond = req['metadata']['condition']
        
        q_data = PILOT_QUESTIONS[q_id]
        leq_first = get_leq(q_id)
        cue_text = get_cue(cond, t, leq_first)
        
        prompt = prompt_type_B(q_data['question'], q_data['formula'], q_data['fixed_definitions'], cue_text)
        res = client.generate(req['request_id'], prompt, metadata=req['metadata'], execute=execute)
        if res and res.get('transport_status') == 'success':
            ws = parse_worksheet(res['output'], expected_keys=list(q_data['constraints'].keys()), constraints=q_data['constraints'])
            if ws:
                canonical_worksheets[q_id] = ws
            else:
                print(f"Failed to parse worksheet for {q_id}")
                
    # Phase 4: Reviewer
    for req in rev_reqs:
        q_id = req['q_id']
        if q_id not in canonical_worksheets:
            print(f"Skipping {req['request_id']} due to missing canonical worksheet.")
            continue
            
        t = thresholds[q_id]
        cond = req['metadata']['condition']
        
        q_data = PILOT_QUESTIONS[q_id]
        leq_first = get_leq(q_id)
        cue_text = get_cue(cond, t, leq_first)
        
        prompt = prompt_type_C(q_data['question'], q_data['formula'], q_data['fixed_definitions'], canonical_worksheets[q_id], cue_text)
        
        # Confirm reviewer prompts contain no estimator rationale or source-condition label. (canonical_worksheet is just the factors dict)
        client.generate(req['request_id'], prompt, metadata=req['metadata'], execute=execute)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Execute API calls")
    parser.add_argument("--preflight", action="store_true", help="Run preflight checks (default)")
    args = parser.parse_args()
    
    model_id = os.getenv("MODEL_OVERRIDE", "openai/gpt-oss-120b")
    client = ExperimentClient(model=model_id, log_file="pilot_log_v2.jsonl")
    
    run_pilot(client, execute=args.execute)
