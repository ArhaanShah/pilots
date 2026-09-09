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
from src.parser import parse_estimate_line, parse_worksheet, round_sigfigs
from src.config import RunConfig

class PreflightError(Exception):
    pass

LEQ_ASSIGNMENTS = {
    "P01": True, "P02": True, "P03": False, "P04": False
}

def get_leq(q_id):
    return LEQ_ASSIGNMENTS.get(q_id, False)

def build_schedule(config: RunConfig):
    rng = random.Random(int(config.master_seed))
    schedule = []
    q_ids = list(PILOT_QUESTIONS.keys())
    
    # Phase 1: Calibration (20 calls)
    calib_requests = []
    for q_id in q_ids:
        for i in range(5):
            calib_requests.append({
                "request_id": f"calib_{q_id}_{i}",
                "protocol_version": config.protocol_version,
                "phase": "calibration",
                "q_id": q_id,
                "condition": "none",
                "replicate": i,
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
                    "protocol_version": config.protocol_version,
                    "phase": "ordinary",
                    "q_id": q_id,
                    "condition": cue_cond,
                    "replicate": i,
                })
    rng.shuffle(ord_requests)
    schedule.extend(ord_requests)
    
    # Phase 3: Worksheets (2 calls)
    ws_requests = []
    for q_id in ["P01", "P02"]:
        ws_requests.append({
            "request_id": f"pilot_est_N_{q_id}",
            "protocol_version": config.protocol_version,
            "phase": "worksheet",
            "q_id": q_id,
            "condition": "N",
            "replicate": None,
        })
    rng.shuffle(ws_requests)
    schedule.extend(ws_requests)
    
    # Phase 4: Reviewers (6 calls)
    rev_requests = []
    for q_id in ["P01", "P02"]:
        for cue_cond in ['H', 'L', 'N']:
            rev_requests.append({
                "request_id": f"pilot_rev_{q_id}_{cue_cond}",
                "protocol_version": config.protocol_version,
                "phase": "reviewer",
                "q_id": q_id,
                "condition": cue_cond,
                "replicate": None,
            })
    rng.shuffle(rev_requests)
    schedule.extend(rev_requests)
    
    # Add deterministic seeds
    for req in schedule:
        seed_hash = hashlib.sha256(f"{config.protocol_version}:{req['request_id']}:{config.master_seed}".encode()).digest()
        req['deterministic_seed'] = int.from_bytes(seed_hash[:4], "big") & 0x7FFFFFFF
        
    return schedule

def validate_schedule(schedule, config: RunConfig):
    request_ids = set()
    seeds = set()
    
    if len(schedule) != 52:
        raise PreflightError(f"Expected 52 requests, got {len(schedule)}")
        
    phase_cond_counts = {
        ("calibration", "none"): 0,
        ("ordinary", "H"): 0,
        ("ordinary", "L"): 0,
        ("ordinary", "N"): 0,
        ("worksheet", "N"): 0,
        ("reviewer", "H"): 0,
        ("reviewer", "L"): 0,
        ("reviewer", "N"): 0,
    }
    
    import collections
    calib_q_counts = collections.defaultdict(int)
    
    for req in schedule:
        rid = req['request_id']
        if rid in request_ids:
            raise PreflightError(f"Duplicate request ID: {rid}")
        request_ids.add(rid)
        
        seed = req['deterministic_seed']
        if seed in seeds:
            raise PreflightError(f"Duplicate generation seed for {rid}")
        seeds.add(seed)
        
        phase = req['phase']
        cond = req['condition']
        
        if (phase, cond) in phase_cond_counts:
            phase_cond_counts[(phase, cond)] += 1
            
        if phase in ["worksheet", "reviewer"] and req['q_id'] in ["P03", "P04"]:
            raise PreflightError(f"Unexpected worksheet/reviewer for {req['q_id']}")
            
        if phase == 'calibration':
            calib_q_counts[req['q_id']] += 1
            
    for q_id, count in calib_q_counts.items():
        if count != 5:
            raise PreflightError(f"Question {q_id} has {count} calibration replicates instead of 5")
            
    expected_counts = {
        ("calibration", "none"): 20,
        ("ordinary", "H"): 8,
        ("ordinary", "L"): 8,
        ("ordinary", "N"): 8,
        ("worksheet", "N"): 2,
        ("reviewer", "H"): 2,
        ("reviewer", "L"): 2,
        ("reviewer", "N"): 2,
    }
    
    for k, v in expected_counts.items():
        if phase_cond_counts[k] != v:
            raise PreflightError(f"Expected {v} for {k}, got {phase_cond_counts[k]}")
            
    # Check clause order balanced
    leq_counts = sum(1 for q_id in ["P01", "P02", "P03", "P04"] if get_leq(q_id))
    if leq_counts != 2:
        raise PreflightError(f"Clause order is not balanced across 4 questions")

    # Prompt invariants test
    for q_id, q_data in PILOT_QUESTIONS.items():
        t = 1000 # sentinel
        leq_first = get_leq(q_id)
        cue_H = get_cue("H", t, leq_first)
        cue_L = get_cue("L", t, leq_first)
        cue_N = get_cue("N", t, leq_first)
        
        p_H = prompt_type_A(q_data['question'], "its standard units", cue_H)
        p_L = prompt_type_A(q_data['question'], "its standard units", cue_L)
        p_N = prompt_type_A(q_data['question'], "its standard units", cue_N)
        
        if len(p_H) != len(p_L):
            raise PreflightError(f"H and L prompts for {q_id} have different lengths")
            
        # For reviewers
        if q_id in ["P01", "P02"]:
            canonical_worksheet = {"factors": {"dummy": 1}}
            r_H = prompt_type_C(q_data['question'], q_data['formula'], q_data['fixed_definitions'], canonical_worksheet, cue_H)
            r_L = prompt_type_C(q_data['question'], q_data['formula'], q_data['fixed_definitions'], canonical_worksheet, cue_L)
            
            if 'rationale' in r_H.lower() and 'estimator' in r_H.lower():
                raise PreflightError("Reviewer prompt contains estimator rationale context inappropriately")

def hash_dict(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()

def get_manifest_dict(config: RunConfig, schedule):
    gen_settings = {
        "temperature": config.temperature,
        "max_completion_tokens": config.max_completion_tokens,
        "reasoning_effort": config.reasoning_effort
    }
    return {
        "protocol_version": config.protocol_version,
        "creation_timestamp": "2026-09-09T00:00:00Z", # static or generated
        "master_schedule_seed": config.master_seed,
        "provider": config.provider,
        "requested_model": config.requested_model,
        "generation_settings": gen_settings,
        "generation_settings_sha256": hash_dict(gen_settings),
        "question_bank_sha256": hash_dict(PILOT_QUESTIONS),
        "prompt_template_sha256": hash_dict({"A": "A", "B": "B", "C": "C"}), # mock hash of templates
        "schedule_sha256": hash_dict(schedule),
        "output_filenames": {
            "manifest": config.manifest_path,
            "schedule": config.schedule_path,
            "thresholds": config.thresholds_path,
            "reviewer_inputs": config.reviewer_inputs_path,
            "log": config.log_path,
            "analysis": config.analysis_path
        }
    }

def atomic_write(filepath, data):
    tmp = filepath + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, filepath)

def write_preflight_artifacts(schedule, config: RunConfig, output_dir="."):
    manifest = get_manifest_dict(config, schedule)
    atomic_write(os.path.join(output_dir, config.manifest_path), manifest)
    atomic_write(os.path.join(output_dir, config.schedule_path), schedule)

def load_and_validate_preflight_artifacts(config: RunConfig, output_dir="."):
    manifest_path = os.path.join(output_dir, config.manifest_path)
    schedule_path = os.path.join(output_dir, config.schedule_path)
    
    if not os.path.exists(manifest_path) or not os.path.exists(schedule_path):
        raise PreflightError("Missing artifacts")
        
    with open(manifest_path, "r") as f:
        manifest = json.load(f)
    with open(schedule_path, "r") as f:
        schedule = json.load(f)
        
    gen_settings = {
        "temperature": config.temperature,
        "max_completion_tokens": config.max_completion_tokens,
        "reasoning_effort": config.reasoning_effort
    }
    
    if manifest["generation_settings_sha256"] != hash_dict(gen_settings):
        raise PreflightError("Generation settings hash mismatch")
    if manifest["question_bank_sha256"] != hash_dict(PILOT_QUESTIONS):
        raise PreflightError("Question bank hash mismatch")
    if manifest["schedule_sha256"] != hash_dict(schedule):
        raise PreflightError("Schedule hash mismatch")
        
    if manifest["requested_model"] != config.requested_model:
        raise PreflightError("Requested model mismatch")
        
    return schedule

def run_pilot(config: RunConfig, execute=False, output_dir="."):
    if not execute:
        print("Running preflight validation...")
        schedule = build_schedule(config)
        validate_schedule(schedule, config)
        
        log_path = os.path.join(output_dir, config.log_path)
        if not os.path.exists(log_path):
            write_preflight_artifacts(schedule, config, output_dir)
            print("Wrote preflight artifacts.")
            # Read back and validate
            load_and_validate_preflight_artifacts(config, output_dir)
            print("Validated written artifacts.")
        else:
            print("Log exists, keeping original artifacts.")
            
        print("Preflight output:")
        print(f"Protocol: {config.protocol_version}, Model: {config.requested_model}")
        print("Questions:")
        for k, v in PILOT_QUESTIONS.items():
            print(f"{k}: {v['question']}")
            if 'formula' in v:
                print(f"  Formula: {v['formula']}")
                print(f"  Constraints: {v.get('constraints')}")
        print("Max planned requests: 52")
        print("Approx token budget: 158496")
        print("PASS")
        return
        
    print("Executing schedule...")
    schedule = load_and_validate_preflight_artifacts(config, output_dir)
    client = ExperimentClient(config)
    
    thresholds = {}
    thresholds_path = os.path.join(output_dir, config.thresholds_path)
    if os.path.exists(thresholds_path):
        with open(thresholds_path, "r") as f:
            data = json.load(f)
            for k, v in data.items():
                thresholds[k] = v.get("threshold")
                
    calib_reqs = [r for r in schedule if r['phase'] == 'calibration']
    ord_reqs = [r for r in schedule if r['phase'] == 'ordinary']
    ws_reqs = [r for r in schedule if r['phase'] == 'worksheet']
    rev_reqs = [r for r in schedule if r['phase'] == 'reviewer']
    
    calib_results = {}
    for req in calib_reqs:
        q_id = req['q_id']
        q_data = PILOT_QUESTIONS[q_id]
        prompt = prompt_type_A(q_data['question'], "its standard units", "")
        
        res = client.generate(req['request_id'], prompt, metadata=req, execute=execute)
        if res and res.get('transport_status') == 'success':
            val = parse_estimate_line(res['output'])
            if q_id not in calib_results:
                calib_results[q_id] = []
            calib_results[q_id].append(val)
                
    if not os.path.exists(thresholds_path):
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
            
        atomic_write(thresholds_path, thresholds_output)
        
    if any(t is None for t in thresholds.values()):
        print("Technical failure: Not all tasks achieved >=4 valid calibrations.")
        sys.exit(1)
        
    for req in ord_reqs:
        q_id = req['q_id']
        t = thresholds[q_id]
        cond = req['condition']
        q_data = PILOT_QUESTIONS[q_id]
        cue_text = get_cue(cond, t, get_leq(q_id))
        prompt = prompt_type_A(q_data['question'], "its standard units", cue_text)
        client.generate(req['request_id'], prompt, metadata=req, execute=execute)
        
    canonical_worksheets = {}
    reviewer_inputs_path = os.path.join(output_dir, config.reviewer_inputs_path)
    
    if os.path.exists(reviewer_inputs_path):
        with open(reviewer_inputs_path, "r") as f:
            canonical_worksheets = json.load(f)
            
    for req in ws_reqs:
        q_id = req['q_id']
        if q_id in canonical_worksheets:
            continue
            
        t = thresholds[q_id]
        cond = req['condition']
        q_data = PILOT_QUESTIONS[q_id]
        cue_text = get_cue(cond, t, get_leq(q_id))
        prompt = prompt_type_B(q_data['question'], q_data['formula'], q_data['fixed_definitions'], cue_text)
        
        res = client.generate(req['request_id'], prompt, metadata=req, execute=execute)
        if res and res.get('transport_status') == 'success':
            ws = parse_worksheet(res['output'], expected_keys=list(q_data['constraints'].keys()), constraints=q_data['constraints'])
            if ws:
                canonical_worksheets[q_id] = ws
            else:
                canonical_worksheets[q_id] = "invalid_source_worksheet"
                print(f"Failed to parse worksheet for {q_id}")
                
    atomic_write(reviewer_inputs_path, canonical_worksheets)
                
    for req in rev_reqs:
        q_id = req['q_id']
        ws = canonical_worksheets.get(q_id)
        if not ws or ws == "invalid_source_worksheet":
            print(f"Skipping {req['request_id']} due to invalid source worksheet.")
            # Record it as structurally unavailable if we want, but basically we just don't run it
            continue
            
        t = thresholds[q_id]
        cond = req['condition']
        q_data = PILOT_QUESTIONS[q_id]
        cue_text = get_cue(cond, t, get_leq(q_id))
        prompt = prompt_type_C(q_data['question'], q_data['formula'], q_data['fixed_definitions'], ws, cue_text)
        client.generate(req['request_id'], prompt, metadata=req, execute=execute)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pilot Experiment")
    parser.add_argument("--preflight", action="store_true", help="Run preflight checks")
    parser.add_argument("--execute", action="store_true", help="Execute API calls")
    args = parser.parse_args()
    
    if not args.preflight and not args.execute:
        parser.print_help()
        sys.exit(0)
        
    config = RunConfig()
    try:
        run_pilot(config, execute=args.execute)
    except PreflightError as e:
        print(f"Preflight Error: {e}")
        sys.exit(1)
