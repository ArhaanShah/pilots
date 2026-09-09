import os
import sys
import json
import random
import hashlib
import argparse
import statistics
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
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

def hash_text(text):
    return hashlib.sha256(text.encode()).hexdigest()

def hash_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def source_file_hashes():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    relative_paths = [
        "src/analyze.py",
        "src/client.py",
        "src/config.py",
        "src/experiment.py",
        "src/parser.py",
        "src/prompts.py",
        "src/questions.py",
    ]
    return {
        path: hash_file(os.path.join(project_root, *path.split("/")))
        for path in relative_paths
    }

def current_git_commit():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root, check=True,
            capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None

def get_manifest_dict(config: RunConfig, schedule):
    gen_settings = {
        "temperature": config.temperature,
        "max_completion_tokens": config.max_completion_tokens,
        "reasoning_effort": config.reasoning_effort
    }
    return {
        "protocol_version": config.protocol_version,
        "creation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git_commit": current_git_commit(),
        "master_schedule_seed": config.master_seed,
        "provider": config.provider,
        "requested_model": config.requested_model,
        "generation_settings": gen_settings,
        "generation_settings_sha256": hash_dict(gen_settings),
        "question_bank_sha256": hash_dict(PILOT_QUESTIONS),
        "prompt_template_sha256": source_file_hashes()["src/prompts.py"],
        "source_file_sha256": source_file_hashes(),
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
    current_sources = source_file_hashes()
    if manifest.get("prompt_template_sha256") != current_sources["src/prompts.py"]:
        raise PreflightError("Prompt template hash mismatch")
    if manifest.get("source_file_sha256") != current_sources:
        raise PreflightError("Source file hash mismatch")
    if manifest["schedule_sha256"] != hash_dict(schedule):
        raise PreflightError("Schedule hash mismatch")
        
    if manifest["requested_model"] != config.requested_model:
        raise PreflightError("Requested model mismatch")

    if manifest.get("protocol_version") != config.protocol_version:
        raise PreflightError("Protocol version mismatch")
    if manifest.get("master_schedule_seed") != config.master_seed:
        raise PreflightError("Master schedule seed mismatch")
    if manifest.get("provider") != config.provider:
        raise PreflightError("Provider mismatch")
    expected_filenames = {
        "manifest": config.manifest_path,
        "schedule": config.schedule_path,
        "thresholds": config.thresholds_path,
        "reviewer_inputs": config.reviewer_inputs_path,
        "log": config.log_path,
        "analysis": config.analysis_path,
    }
    if manifest.get("output_filenames") != expected_filenames:
        raise PreflightError("Output filename manifest mismatch")

    validate_schedule(schedule, config)
    if schedule != build_schedule(config):
        raise PreflightError("Schedule does not match deterministic build")
        
    return schedule

def _successful_records(client):
    return {
        request_id: record
        for request_id, record in client.completed_requests.items()
        if record.get("transport_status") == "success"
    }

def _calibration_requests(schedule, q_id):
    return [
        req for req in schedule
        if req["phase"] == "calibration" and req["q_id"] == q_id
    ]

def build_threshold_artifact(q_id, schedule, success_records):
    requests = _calibration_requests(schedule, q_id)
    source_ids = [req["request_id"] for req in requests]
    raw_values = []
    output_hashes = {}
    for request_id in source_ids:
        record = success_records.get(request_id)
        if record is None:
            raw_values.append(None)
            continue
        output = record.get("output", "")
        output_hashes[request_id] = hash_text(output)
        raw_values.append(parse_estimate_line(output))

    valid_values = [value for value in raw_values if value is not None]
    median = statistics.median(valid_values) if len(valid_values) >= 4 else None
    threshold = round_sigfigs(median, 6) if median is not None else None
    return {
        "source_request_ids": source_ids,
        "source_output_sha256": output_hashes,
        "raw_values": raw_values,
        "valid_count": len(valid_values),
        "median": median,
        "threshold": threshold,
    }

def validate_threshold_artifacts(data, schedule, success_records):
    errors = []
    if not isinstance(data, dict):
        return ["threshold artifact is not an object"]
    expected_questions = set(PILOT_QUESTIONS)
    if set(data) != expected_questions:
        errors.append(
            f"threshold question IDs differ: expected {sorted(expected_questions)}, got {sorted(data)}"
        )
    for q_id in sorted(expected_questions & set(data)):
        expected = build_threshold_artifact(q_id, schedule, success_records)
        actual = data[q_id]
        if not isinstance(actual, dict):
            errors.append(f"{q_id}: threshold entry is not an object")
            continue
        for field in (
            "source_request_ids", "source_output_sha256", "raw_values",
            "valid_count", "median", "threshold"
        ):
            if actual.get(field) != expected[field]:
                errors.append(f"{q_id}: {field} does not match current calibration outputs")
    return errors

def _reviewer_prompts(q_id, factors, threshold):
    q_data = PILOT_QUESTIONS[q_id]
    prompts = {}
    for condition in ("H", "L", "N"):
        cue_text = get_cue(condition, threshold, get_leq(q_id))
        prompts[condition] = prompt_type_C(
            q_data["question"], q_data["formula"], q_data["fixed_definitions"],
            factors, cue_text
        )
    return prompts

def build_reviewer_input_artifact(q_id, source_record, threshold):
    q_data = PILOT_QUESTIONS[q_id]
    output = source_record.get("output", "")
    factors = parse_worksheet(
        output,
        expected_keys=list(q_data["constraints"].keys()),
        constraints=q_data["constraints"],
    )
    prompt_hashes = {condition: None for condition in ("H", "L", "N")}
    status = "invalid_source_worksheet"
    if factors is not None:
        status = "available"
        prompt_hashes = {
            condition: hash_text(prompt)
            for condition, prompt in _reviewer_prompts(q_id, factors, threshold).items()
        }
    return {
        "status": status,
        "source_request_id": source_record["request_id"],
        "source_output_sha256": hash_text(output),
        "canonical_factors": factors,
        "reviewer_prompt_sha256": prompt_hashes,
    }

def validate_reviewer_input_artifacts(data, schedule, success_records, thresholds, require_all=True):
    errors = []
    expected_questions = {"P01", "P02"}
    if not isinstance(data, dict):
        return ["reviewer-input artifact is not an object"]
    if not set(data).issubset(expected_questions):
        errors.append(f"unexpected reviewer-input question IDs: {sorted(set(data) - expected_questions)}")
    if require_all and set(data) != expected_questions:
        errors.append(f"reviewer-input question IDs differ: expected {sorted(expected_questions)}, got {sorted(data)}")
    worksheet_ids = {
        req["q_id"]: req["request_id"]
        for req in schedule if req["phase"] == "worksheet"
    }
    for q_id in sorted(expected_questions & set(data)):
        source_id = worksheet_ids.get(q_id)
        source_record = success_records.get(source_id)
        if source_record is None:
            errors.append(f"{q_id}: source worksheet {source_id} has no successful current-log outcome")
            continue
        expected = build_reviewer_input_artifact(q_id, source_record, thresholds.get(q_id))
        actual = data[q_id]
        if not isinstance(actual, dict):
            errors.append(f"{q_id}: reviewer-input entry is not an object")
            continue
        for field in (
            "status", "source_request_id", "source_output_sha256",
            "canonical_factors", "reviewer_prompt_sha256"
        ):
            if actual.get(field) != expected[field]:
                errors.append(f"{q_id}: {field} does not match the current worksheet output")
    return errors

def run_pilot(config: RunConfig, execute=False, output_dir="."):
    if not execute:
        print("Running preflight validation...")
        schedule = build_schedule(config)
        validate_schedule(schedule, config)

        manifest_path = os.path.join(output_dir, config.manifest_path)
        schedule_path = os.path.join(output_dir, config.schedule_path)
        log_path = os.path.join(output_dir, config.log_path)
        artifact_exists = [os.path.exists(manifest_path), os.path.exists(schedule_path)]
        if artifact_exists == [False, False]:
            if os.path.exists(log_path):
                raise PreflightError("Log exists but frozen preflight artifacts are missing")
            write_preflight_artifacts(schedule, config, output_dir)
            print("Wrote preflight artifacts.")
        elif artifact_exists[0] != artifact_exists[1]:
            raise PreflightError("Manifest and schedule must either both exist or both be absent")
        else:
            print("Keeping existing frozen preflight artifacts.")

        load_and_validate_preflight_artifacts(config, output_dir)
        print("Validated frozen artifacts.")
            
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

    if not os.getenv("GROQ_API_KEY"):
        raise PreflightError("GROQ_API_KEY is required for --execute")

    print("Executing schedule...")
    schedule = load_and_validate_preflight_artifacts(config, output_dir)
    runtime_config = replace(
        config, log_path=os.path.join(output_dir, config.log_path)
    )
    client = ExperimentClient(runtime_config, require_api_key=True)

    thresholds_path = os.path.join(output_dir, config.thresholds_path)
    calib_reqs = [r for r in schedule if r['phase'] == 'calibration']
    ord_reqs = [r for r in schedule if r['phase'] == 'ordinary']
    ws_reqs = [r for r in schedule if r['phase'] == 'worksheet']
    rev_reqs = [r for r in schedule if r['phase'] == 'reviewer']
    
    for req in calib_reqs:
        q_id = req['q_id']
        q_data = PILOT_QUESTIONS[q_id]
        prompt = prompt_type_A(q_data['question'], "its standard units", "")
        client.generate(req['request_id'], prompt, metadata=req, execute=True)

    success_records = _successful_records(client)
    if os.path.exists(thresholds_path):
        with open(thresholds_path, "r") as f:
            thresholds_output = json.load(f)
    else:
        thresholds_output = {
            q_id: build_threshold_artifact(q_id, schedule, success_records)
            for q_id in PILOT_QUESTIONS
        }
        atomic_write(thresholds_path, thresholds_output)

    threshold_errors = validate_threshold_artifacts(
        thresholds_output, schedule, success_records
    )
    if threshold_errors:
        raise PreflightError("Threshold source mismatch: " + "; ".join(threshold_errors))
    thresholds = {
        q_id: entry.get("threshold") for q_id, entry in thresholds_output.items()
    }
    if any(t is None for t in thresholds.values()):
        raise PreflightError("Not all tasks achieved >=4 valid calibrations")

    for req in ord_reqs:
        q_id = req['q_id']
        t = thresholds[q_id]
        cond = req['condition']
        q_data = PILOT_QUESTIONS[q_id]
        cue_text = get_cue(cond, t, get_leq(q_id))
        prompt = prompt_type_A(q_data['question'], "its standard units", cue_text)
        client.generate(req['request_id'], prompt, metadata=req, execute=True)

    reviewer_inputs = {}
    reviewer_inputs_path = os.path.join(output_dir, config.reviewer_inputs_path)
    if os.path.exists(reviewer_inputs_path):
        with open(reviewer_inputs_path, "r") as f:
            reviewer_inputs = json.load(f)
        reviewer_errors = validate_reviewer_input_artifacts(
            reviewer_inputs, schedule, _successful_records(client), thresholds,
            require_all=False
        )
        if reviewer_errors:
            raise PreflightError("Reviewer input source mismatch: " + "; ".join(reviewer_errors))

    for req in ws_reqs:
        q_id = req['q_id']
        if q_id in reviewer_inputs:
            continue

        t = thresholds[q_id]
        cond = req['condition']
        q_data = PILOT_QUESTIONS[q_id]
        cue_text = get_cue(cond, t, get_leq(q_id))
        prompt = prompt_type_B(q_data['question'], q_data['formula'], q_data['fixed_definitions'], cue_text)

        res = client.generate(req['request_id'], prompt, metadata=req, execute=True)
        if res and res.get('transport_status') == 'success':
            reviewer_inputs[q_id] = build_reviewer_input_artifact(q_id, res, t)
            if reviewer_inputs[q_id]["status"] != "available":
                print(f"Failed to parse worksheet for {q_id}")

    reviewer_errors = validate_reviewer_input_artifacts(
        reviewer_inputs, schedule, _successful_records(client), thresholds,
        require_all=True
    )
    if reviewer_errors:
        raise PreflightError("Reviewer input source mismatch: " + "; ".join(reviewer_errors))
    atomic_write(reviewer_inputs_path, reviewer_inputs)

    for req in rev_reqs:
        q_id = req['q_id']
        reviewer_input = reviewer_inputs[q_id]
        if reviewer_input["status"] != "available":
            print(f"Skipping {req['request_id']} due to invalid source worksheet.")
            client.record_unavailable(
                req["request_id"], req, "invalid_source_worksheet",
                dependency={
                    "source_request_id": reviewer_input["source_request_id"],
                    "source_output_sha256": reviewer_input["source_output_sha256"],
                },
            )
            continue

        ws = reviewer_input["canonical_factors"]
        t = thresholds[q_id]
        cond = req['condition']
        q_data = PILOT_QUESTIONS[q_id]
        cue_text = get_cue(cond, t, get_leq(q_id))
        prompt = prompt_type_C(q_data['question'], q_data['formula'], q_data['fixed_definitions'], ws, cue_text)
        if hash_text(prompt) != reviewer_input["reviewer_prompt_sha256"][cond]:
            raise PreflightError(f"Reviewer prompt hash mismatch for {req['request_id']}")
        client.generate(req['request_id'], prompt, metadata=req, execute=True)

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
