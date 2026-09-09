import json
import argparse
import statistics
import math
from collections import defaultdict

def round_sigfigs(value: float, digits: int = 6) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Expected a finite positive value")
    places = digits - 1 - math.floor(math.log10(abs(value)))
    return round(value, places)

def analyze(log_file):
    records = []
    try:
        with open(log_file, "r") as f:
            for line in f:
                records.append(json.loads(line))
    except FileNotFoundError:
        print(f"Log file {log_file} not found.")
        return

    # Technical audit
    print("=== Technical Audit ===")
    scheduled_count = 52
    completed_count = len(records)
    print(f"Scheduled Count: {scheduled_count}")
    print(f"Completed Count: {completed_count}")
    
    ids = [r['request_id'] for r in records]
    missing_ids = 52 - len(set(ids)) # Simple proxy for missing if we expect 52
    duplicate_ids = len(ids) - len(set(ids))
    print(f"Missing IDs: {missing_ids}")
    print(f"Duplicate IDs: {duplicate_ids}")
    
    models = set(r.get('returned_model') for r in records if 'returned_model' in r)
    fingerprints = set(r.get('system_fingerprint') for r in records if 'system_fingerprint' in r)
    print(f"Returned Models: {models}")
    print(f"System Fingerprints: {fingerprints}")
    
    finish_reasons = defaultdict(int)
    truncations = 0
    invalid_outputs = 0
    
    from src.parser import parse_estimate_line, parse_worksheet, parse_reviewer
    
    for r in records:
        fr = r.get('finish_reason')
        finish_reasons[fr] += 1
        if fr == 'length':
            truncations += 1
            
        req_id = r['request_id']
        out = r.get('output', '')
        
        is_invalid = False
        if 'calib' in req_id or 'ord' in req_id:
            val = parse_estimate_line(out)
            if val is None:
                is_invalid = True
        elif 'est' in req_id:
            val = parse_worksheet(out)
            if val is None:
                is_invalid = True
        elif 'rev' in req_id:
            # We don't have the constraints here but we can just do basic parse
            val = parse_reviewer(out)
            if val is None:
                is_invalid = True
                
        if is_invalid:
            invalid_outputs += 1
            
    print(f"Finish Reasons: {dict(finish_reasons)}")
    print(f"Invalid Outputs: {invalid_outputs}")
    print(f"Truncation Rate: {truncations / max(1, completed_count):.2%}")
    
    # Exact duplicate outputs
    outputs = [r.get('output') for r in records if r.get('output')]
    duplicate_outputs = len(outputs) - len(set(outputs))
    print(f"Exact Duplicate Output Count: {duplicate_outputs}")
    
    # Parser failures & arithmetic mismatches (Simplified for now)
    print("Parser Failures:", invalid_outputs)
    
    print("\n=== Descriptive Pilot Outcomes ===")
    
    # We will need the thresholds
    try:
        with open("pilot_thresholds_v2.json", "r") as f:
            data = json.load(f)
            thresholds = {k: v.get("threshold") for k, v in data.items()}
    except FileNotFoundError:
        print("pilot_thresholds_v2.json not found, skipping descriptive outcomes.")
        return
        
    ordinary_records = [r for r in records if 'ord' in r['request_id']]
    
    h_above = 0
    l_above = 0
    
    for q_id in thresholds.keys():
        t = thresholds[q_id]
        if t is None: continue
        
        q_records = [r for r in ordinary_records if f"_{q_id}_" in r['request_id']]
        
        for cond in ['H', 'L', 'N']:
            cond_records = [r for r in q_records if f"_{cond}_" in r['request_id']]
            vals = []
            invalid = 0
            for r in cond_records:
                val = parse_estimate_line(r.get('output', ''))
                if val is not None:
                    vals.append(val)
                else:
                    invalid += 1
            
            above = sum(1 for v in vals if v > t)
            below = sum(1 for v in vals if v <= t)
            
            if cond == 'H': h_above += above
            if cond == 'L': l_above += above
            
            median = statistics.median(vals) if vals else None
            try:
                gmean = statistics.geometric_mean(vals) if vals else None
            except statistics.StatisticsError:
                gmean = None
                
            print(f"Task {q_id} | Cond {cond}")
            print(f"  Raw: {vals}")
            print(f"  Above T: {above}, At/Below T: {below}, Invalid: {invalid}")
            print(f"  Median: {median}, GeoMean: {gmean}")
            
    print(f"\nPrimary exploratory contrast (H>T - L>T)/8:")
    print(f"  ({h_above} - {l_above}) / 8 = {(h_above - l_above) / 8.0}")

    print("\nDecision Rule Summary:")
    print(" - Formatting and unit handling must succeed on at least 95% of completed outputs")
    print(" - Truncation must be at most 5%")
    print(" - An aggregate H-minus-L above-threshold gap around 0.15 is only an exploratory lead")
    print(" - The effect should have the predicted direction on at least three of four questions")
    print(" - One extreme task must not be presented as a general result")
    print(" - Opposite effects, refusals, or unusually large neutral-condition effects should be described under their actual labels")
    print(" - This pilot is too small for a convincing statistical claim")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, help="Log file to analyze")
    args = parser.parse_args()
    
    analyze(args.log)
