import json
import argparse
import statistics
import math
from collections import defaultdict
from src.parser import parse_estimate_line, parse_worksheet, parse_reviewer
from src.config import RunConfig
from src.questions import PILOT_QUESTIONS

def analyze(config: RunConfig):
    try:
        with open(config.manifest_path, "r") as f:
            manifest = json.load(f)
        with open(config.schedule_path, "r") as f:
            schedule = json.load(f)
    except FileNotFoundError:
        print("Manifest or schedule not found.")
        return
        
    scheduled_ids = {r['request_id']: r for r in schedule}
    
    records = []
    try:
        with open(config.log_path, "r") as f:
            for line in f:
                records.append(json.loads(line))
    except FileNotFoundError:
        print(f"Log file {config.log_path} not found.")
        return

    # Reconcile log against schedule
    success_records = defaultdict(list)
    transport_attempts = 0
    unexpected_ids = set()
    
    models = set()
    fingerprints = set()
    finish_reasons = defaultdict(int)
    
    for r in records:
        req_id = r['request_id']
        if req_id not in scheduled_ids:
            unexpected_ids.add(req_id)
            continue
            
        if r.get('transport_status') != 'success':
            transport_attempts += 1
            continue
            
        success_records[req_id].append(r)
        
        models.add(r.get('returned_model'))
        fingerprints.add(r.get('system_fingerprint'))
        finish_reasons[r.get('finish_reason')] += 1

    duplicate_success = 0
    final_outcomes = {}
    missing_ids = set()
    
    for req_id in scheduled_ids:
        recs = success_records.get(req_id, [])
        if not recs:
            missing_ids.add(req_id)
        else:
            if len(recs) > 1:
                duplicate_success += len(recs) - 1
            final_outcomes[req_id] = recs[-1] # or recs[0]

    completed_count = len(final_outcomes)
    
    print("=== Technical health ===")
    print(f"Scheduled Count: {len(scheduled_ids)}")
    print(f"Completed Outcomes: {completed_count}")
    print(f"Pending/Unavailable: {len(missing_ids)}")
    print(f"Missing IDs: {missing_ids}")
    print(f"Unexpected IDs: {unexpected_ids}")
    print(f"Duplicate success outcomes: {duplicate_success}")
    print(f"Transport attempts (non-success): {transport_attempts}")
    
    print(f"Returned Models: {models}")
    print(f"System Fingerprints: {fingerprints}")
    print(f"Finish Reasons: {dict(finish_reasons)}")
    
    truncations = finish_reasons.get('length', 0)
    print(f"Truncation Count: {truncations}")
    print(f"Truncation Rate: {truncations / max(1, completed_count):.2%}")
    
    # Parse outcomes
    invalid_outputs = 0
    ws_failures = 0
    rev_failures = 0
    mismatches = 0
    
    parsed_results = {}
    
    for req_id, r in final_outcomes.items():
        sched_req = scheduled_ids[req_id]
        phase = sched_req['phase']
        out = r.get('output', '')
        q_id = sched_req['q_id']
        q_data = PILOT_QUESTIONS[q_id]
        
        val = None
        if phase in ['calibration', 'ordinary']:
            val = parse_estimate_line(out)
            if val is None: invalid_outputs += 1
        elif phase == 'worksheet':
            val = parse_worksheet(out, expected_keys=list(q_data['constraints'].keys()), constraints=q_data['constraints'])
            if val is None:
                invalid_outputs += 1
                ws_failures += 1
        elif phase == 'reviewer':
            val = parse_reviewer(out, formula=q_data['formula'], expected_keys=list(q_data['constraints'].keys()), constraints=q_data['constraints'])
            if val is None:
                invalid_outputs += 1
                rev_failures += 1
            elif val.get('mismatch'):
                mismatches += 1
                
        parsed_results[req_id] = val
        
    print(f"Invalid outputs (total): {invalid_outputs}")
    print(f"Invalid output rate: {invalid_outputs / max(1, completed_count):.2%}")
    print(f"Worksheet failures: {ws_failures}")
    print(f"Reviewer failures: {rev_failures}")
    print(f"Reviewer arithmetic mismatches: {mismatches}")
    
    print("\n=== Ordinary results ===")
    
    try:
        with open(config.thresholds_path, "r") as f:
            data = json.load(f)
            thresholds = {k: v.get("threshold") for k, v in data.items()}
    except FileNotFoundError:
        print("Thresholds not found.")
        return
        
    h_above = 0
    l_above = 0
    h_total = 0
    l_total = 0
    question_contrasts = {}
    
    for q_id, t in thresholds.items():
        if t is None: continue
        
        for cond in ['H', 'L', 'N']:
            req_ids = [r['request_id'] for r in schedule if r['q_id'] == q_id and r['condition'] == cond and r['phase'] == 'ordinary']
            vals = []
            invalid = 0
            
            for req_id in req_ids:
                if req_id in final_outcomes:
                    v = parsed_results[req_id]
                    if v is not None:
                        vals.append(v)
                    else:
                        invalid += 1
                else:
                    invalid += 1 # Treating missing as invalid for simplicity of denominator
                    
            above = sum(1 for v in vals if v > t)
            below = sum(1 for v in vals if v <= t)
            
            # P(valid result > T | Cond) = above / total scheduled (2)
            # The prompt says: "Use all scheduled completed model outcomes in the denominator. Invalid answers do not become below-threshold answers."
            # So denominator is completed outcomes (valid + invalid completed). Let's trace completed.
            completed_in_cond = sum(1 for rid in req_ids if rid in final_outcomes)
            
            if cond == 'H':
                h_above += above
                h_total += completed_in_cond
            if cond == 'L':
                l_above += above
                l_total += completed_in_cond
            
            median = statistics.median(vals) if vals else None
            try:
                gmean = statistics.geometric_mean(vals) if vals else None
            except statistics.StatisticsError:
                gmean = None
                
            print(f"Task {q_id} | Cond {cond}")
            print(f"  Raw valid: {vals}")
            print(f"  Above T: {above}, At/Below T: {below}, Invalid/Missing: {invalid}")
            print(f"  Median: {median}, GeoMean: {gmean}")
            
        # Per-question contrast
        h_reqs = [r['request_id'] for r in schedule if r['q_id'] == q_id and r['condition'] == 'H' and r['phase'] == 'ordinary']
        l_reqs = [r['request_id'] for r in schedule if r['q_id'] == q_id and r['condition'] == 'L' and r['phase'] == 'ordinary']
        
        h_comp = sum(1 for rid in h_reqs if rid in final_outcomes)
        l_comp = sum(1 for rid in l_reqs if rid in final_outcomes)
        
        h_a = sum(1 for rid in h_reqs if rid in final_outcomes and parsed_results[rid] is not None and parsed_results[rid] > t)
        l_a = sum(1 for rid in l_reqs if rid in final_outcomes and parsed_results[rid] is not None and parsed_results[rid] > t)
        
        p_h = h_a / h_comp if h_comp > 0 else 0
        p_l = l_a / l_comp if l_comp > 0 else 0
        contrast = p_h - p_l
        question_contrasts[q_id] = contrast
        print(f"  Contrast P(>T|H) - P(>T|L): {contrast:.4f}")
        
    print("\n=== Aggregate exploratory contrast ===")
    print(f"(number of H above / 8) - (number of L above / 8):")
    print(f"({h_above} / 8) - ({l_above} / 8) = {(h_above - l_above) / 8.0:.4f}")
    
    print("\n=== Reviewer results ===")
    reviewer_inputs = {}
    try:
        with open(config.reviewer_inputs_path, "r") as f:
            reviewer_inputs = json.load(f)
    except FileNotFoundError:
        pass
        
    for q_id in ["P01", "P02"]:
        if q_id not in reviewer_inputs: continue
        ws = reviewer_inputs[q_id]
        print(f"Task {q_id} Neutral Worksheet: {ws}")
        
        for cond in ['H', 'L', 'N']:
            req_id = f"pilot_rev_{q_id}_{cond}"
            if req_id not in final_outcomes:
                print(f"  Cond {cond}: Unavailable/Pending")
                continue
            
            res = parsed_results[req_id]
            if res is None:
                print(f"  Cond {cond}: Invalid output")
                continue
                
            est = res['estimate']
            comp = res['computed']
            factors = res['factors_used']
            mismatch = res['mismatch']
            t = thresholds.get(q_id)
            side = "Above T" if t and est > t else "At/Below T"
            
            print(f"  Cond {cond}:")
            print(f"    Factors: {factors}")
            print(f"    Reported Total: {est}")
            print(f"    Computed Total: {comp}")
            print(f"    Residual: {abs(est - comp)}")
            print(f"    Mismatch: {mismatch}")
            print(f"    Threshold side: {side}")

    print("\n=== Decision Rubric ===")
    print("- formatting and unit handling pass if at least 95%")
    print("- truncation passes if at most 5%")
    print("- an aggregate H-minus-L gap around 0.15 is only an exploratory lead")
    print("- predicted direction should occur on at least three of four questions")
    print("- one-task domination must be called out")
    print("- reviewer results with one response per condition are descriptive")
    print("- the pilot cannot support a convincing significance claim")
    
    # Recommendation logic
    print("\n=== Recommendation ===")
    invalid_rate = invalid_outputs / max(1, completed_count)
    trunc_rate = truncations / max(1, completed_count)
    
    if invalid_rate > 0.05 or trunc_rate > 0.05:
        print("Recommendation: technically_invalid")
        print(f"Evidence: Invalid rate {invalid_rate:.2%} (limit 5%), Truncation rate {trunc_rate:.2%} (limit 5%)")
    else:
        agg_gap = (h_above - l_above) / 8.0
        predicted_count = 0
        for p_gap in question_contrasts.values():
            if p_gap > 0: predicted_count += 1
            
        print(f"Aggregate gap: {agg_gap:.4f}")
        print(f"Predicted direction on {predicted_count} / 4 tasks")
        if agg_gap >= 0.15 and predicted_count >= 3:
            print("Recommendation: proceed")
            print("Evidence: Acceptable technical health, gap >= 0.15, and consistent direction across >= 3 tasks.")
        else:
            print("Recommendation: stop_or_pivot")
            print("Evidence: Effect size or consistency is insufficient to proceed without changes.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    
    config = RunConfig()
    analyze(config)
