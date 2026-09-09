import json
import re

def parse_estimate_line(text):
    """Parses Request Type A for ESTIMATE: <number>."""
    lines = text.strip().split('\n')
    for line in reversed(lines):
        if 'ESTIMATE:' in line.upper():
            try:
                # Extract the number part
                num_str = line.upper().split('ESTIMATE:')[1].strip()
                # Remove any stray markdown or commas
                num_str = re.sub(r'[^0-9.eE+-]', '', num_str)
                val = float(num_str)
                if val > 0:
                    return val
            except ValueError:
                pass
    return None

def extract_json(text):
    """Tries to find and parse a JSON object in the text."""
    # Find the first '{' and the last '}'
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end+1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    return None

def parse_worksheet(text, expected_keys=None):
    """Parses Request Type B for factors."""
    data = extract_json(text)
    if data and 'factors' in data:
        factors = data['factors']
        if factors is None:
            return None
        if expected_keys:
            # Validate that all expected keys are present and positive numbers
            for key in expected_keys:
                if key not in factors:
                    return None
                try:
                    val = float(factors[key])
                    if val <= 0:
                        return None
                    factors[key] = val
                except (ValueError, TypeError):
                    return None
        return factors
    return None

def parse_reviewer(text):
    """Parses Request Type C for factors_used and estimate."""
    data = extract_json(text)
    if data and 'factors_used' in data and 'estimate' in data:
        if data['estimate'] is None or data['factors_used'] is None:
            return None
        try:
            est = float(data['estimate'])
            factors = {k: float(v) for k, v in data['factors_used'].items()}
            return {'factors_used': factors, 'estimate': est}
        except (ValueError, TypeError):
            pass
    return None

def evaluate_formula(formula, factors):
    """Evaluates the fixed factorization formula securely."""
    # formula is e.g. "1000 * a * b"
    # replace variables with their numeric values
    expr = formula
    for k, v in factors.items():
        # use regex to replace whole word only
        expr = re.sub(rf'\b{k}\b', str(v), expr)
    
    # securely evaluate the math expression
    # only allow numbers, *, /, +, -, spaces, and parentheses
    if not re.match(r'^[0-9.eE+*/\-\s()]+$', expr):
        return None
    try:
        val = eval(expr)
        if val > 0:
            return val
    except Exception:
        pass
    return None
