import json
import re
import math

NUMBER_PATTERN = r"[+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"

def parse_estimate_line(text):
    """Parses Request Type A for ESTIMATE: <number>."""
    lines = text.strip().split('\n')
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        # Allow markdown emphasis like **ESTIMATE: 100** or _ESTIMATE: 100_
        line = re.sub(r'^[*_]+', '', line)
        line = re.sub(r'[*_]+$', '', line)
        line = line.strip()
        
        if line.upper().startswith("ESTIMATE:"):
            # Use fullmatch on the rest
            val_str = line[len("ESTIMATE:"):].strip()
            if re.fullmatch(NUMBER_PATTERN, val_str):
                # parse float
                val_str = val_str.replace(",", "")
                try:
                    val = float(val_str)
                    if math.isfinite(val) and val > 0:
                        return val
                except ValueError:
                    pass
        return None # Must be exactly the last non-empty line
    return None

def extract_json(text):
    """Tries to find and parse EXACTLY ONE JSON object in the text."""
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        # Check if there are other objects outside (simple check, just grab the largest span)
        json_str = text[start:end+1]
        
        # reject NaN, Infinity, -Infinity
        if re.search(r'\b(NaN|Infinity|-Infinity)\b', json_str):
            return None
            
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    return None

def parse_worksheet(text, expected_keys=None, constraints=None):
    """Parses Request Type B for factors."""
    data = extract_json(text)
    if data and 'factors' in data and 'rationale' in data:
        factors = data['factors']
        if factors is None:
            return None
            
        if not isinstance(data['rationale'], str):
            return None
            
        if expected_keys:
            if set(factors.keys()) != set(expected_keys):
                return None
                
            for key in expected_keys:
                val = factors[key]
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    return None
                if not math.isfinite(val):
                    return None
                
                # Check constraints
                if constraints and key in constraints:
                    if 'min_exclusive' in constraints[key]:
                        if val <= constraints[key]['min_exclusive']:
                            return None
                    if 'min_inclusive' in constraints[key]:
                        if val < constraints[key]['min_inclusive']:
                            return None
                            
                factors[key] = float(val)
        return factors
    return None

def parse_reviewer(text, formula=None, expected_keys=None, constraints=None):
    """Parses Request Type C for factors_used and estimate."""
    data = extract_json(text)
    if data and 'factors_used' in data and 'estimate' in data and 'rationale' in data:
        if data['estimate'] is None or data['factors_used'] is None:
            return None
            
        if not isinstance(data['rationale'], str):
            return None
            
        est_val = data['estimate']
        if isinstance(est_val, bool) or not isinstance(est_val, (int, float)) or not math.isfinite(est_val) or est_val <= 0:
            return None
            
        factors = data['factors_used']
        if expected_keys:
            if set(factors.keys()) != set(expected_keys):
                return None
                
            for key in expected_keys:
                val = factors[key]
                if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                    return None
                    
                if constraints and key in constraints:
                    if 'min_exclusive' in constraints[key]:
                        if val <= constraints[key]['min_exclusive']:
                            return None
                    if 'min_inclusive' in constraints[key]:
                        if val < constraints[key]['min_inclusive']:
                            return None
                            
                factors[key] = float(val)
                
        # Check arithmetic mismatch
        computed_total = evaluate_formula(formula, factors)
        if computed_total is None:
            return None
            
        # Check floating-point tolerance
        if abs(computed_total - float(est_val)) / max(1e-9, abs(computed_total)) > 1e-4:
            # We flag this in analysis, maybe return a flag here?
            return {'factors_used': factors, 'estimate': float(est_val), 'mismatch': True, 'computed': computed_total}
            
        return {'factors_used': factors, 'estimate': float(est_val), 'mismatch': False, 'computed': computed_total}
    return None

def evaluate_formula(formula, factors):
    """Evaluates the fixed factorization formula securely."""
    if not formula:
        return None
    try:
        # Assuming all formulas are simple multiplications for the pilot
        # e.g., "living_giraffes * average_spots_per_giraffe"
        parts = [p.strip() for p in formula.split('*')]
        val = 1.0
        for p in parts:
            if p in factors:
                val *= factors[p]
            else:
                val *= float(p)
        if val > 0:
            return val
    except Exception:
        pass
    return None

def round_sigfigs(value: float, digits: int = 6) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Expected a finite positive value")
    places = digits - 1 - math.floor(math.log10(abs(value)))
    return round(value, places)
