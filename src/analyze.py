import argparse
import json
import os
import statistics
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone

from src.config import RunConfig
from src.experiment import (
    PreflightError,
    validate_reviewer_input_artifacts,
    validate_schedule,
    validate_threshold_artifacts,
)
from src.parser import parse_estimate_line, parse_reviewer, parse_worksheet
from src.questions import PILOT_QUESTIONS


def _read_json(path):
    with open(path, "r") as f:
        return json.load(f)


def _read_jsonl(path):
    records = []
    with open(path, "r") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSONL record at line {line_number}") from exc
    return records


def _atomic_write(path, data):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def analyze(config: RunConfig):
    manifest = _read_json(config.manifest_path)
    schedule = _read_json(config.schedule_path)
    records = _read_jsonl(config.log_path)

    schedule_errors = []
    try:
        validate_schedule(schedule, config)
    except PreflightError as exc:
        schedule_errors.append(str(exc))

    scheduled = {request["request_id"]: request for request in schedule}
    success_records = defaultdict(list)
    unexpected_ids = set()
    transport_attempts = 0
    unavailable_records = {}
    finish_reasons = defaultdict(int)

    for record in records:
        request_id = record.get("request_id")
        if request_id not in scheduled:
            unexpected_ids.add(request_id)
            continue
        status = record.get("transport_status")
        if status == "success":
            success_records[request_id].append(record)
            finish_reasons[str(record.get("finish_reason"))] += 1
        elif status == "unavailable":
            unavailable_records[request_id] = record
        else:
            transport_attempts += 1

    duplicate_success = sum(max(0, len(items) - 1) for items in success_records.values())
    final_outcomes = {request_id: items[-1] for request_id, items in success_records.items()}
    missing_ids = sorted(set(scheduled) - set(final_outcomes))
    critical_missing_ids = sorted(
        request_id for request_id in missing_ids
        if scheduled[request_id]["phase"] in {"calibration", "ordinary"}
    )

    expected_model = manifest.get("requested_model", config.requested_model)
    returned_models = sorted({
        str(record.get("returned_model")) for record in final_outcomes.values()
    })
    model_mismatch_ids = sorted(
        request_id for request_id, record in final_outcomes.items()
        if record.get("returned_model") != expected_model
    )
    fingerprints = sorted({
        str(record.get("system_fingerprint")) for record in final_outcomes.values()
    })

    parsed_results = {}
    invalid_outputs = 0
    worksheet_failures = 0
    reviewer_failures = 0
    reviewer_arithmetic_mismatches = 0
    for request_id, record in final_outcomes.items():
        request = scheduled[request_id]
        phase = request["phase"]
        q_data = PILOT_QUESTIONS[request["q_id"]]
        output = record.get("output", "")
        if phase in {"calibration", "ordinary"}:
            parsed = parse_estimate_line(output)
        elif phase == "worksheet":
            parsed = parse_worksheet(
                output,
                expected_keys=list(q_data["constraints"].keys()),
                constraints=q_data["constraints"],
            )
            if parsed is None:
                worksheet_failures += 1
        else:
            parsed = parse_reviewer(
                output,
                formula=q_data["formula"],
                expected_keys=list(q_data["constraints"].keys()),
                constraints=q_data["constraints"],
            )
            if parsed is None:
                reviewer_failures += 1
            elif parsed.get("mismatch"):
                reviewer_arithmetic_mismatches += 1
        if parsed is None:
            invalid_outputs += 1
        parsed_results[request_id] = parsed

    try:
        threshold_data = _read_json(config.thresholds_path)
    except FileNotFoundError:
        threshold_data = {}
    threshold_source_errors = validate_threshold_artifacts(
        threshold_data, schedule, final_outcomes
    )
    thresholds = {
        q_id: entry.get("threshold")
        for q_id, entry in threshold_data.items()
        if isinstance(entry, dict)
    }

    try:
        reviewer_input_data = _read_json(config.reviewer_inputs_path)
    except FileNotFoundError:
        reviewer_input_data = {}
    reviewer_input_source_errors = validate_reviewer_input_artifacts(
        reviewer_input_data, schedule, final_outcomes, thresholds, require_all=True
    )

    ordinary_results = {}
    question_contrasts = {}
    h_above = 0
    l_above = 0
    for q_id in PILOT_QUESTIONS:
        threshold = thresholds.get(q_id)
        ordinary_results[q_id] = {}
        for condition in ("H", "L", "N"):
            request_ids = [
                request["request_id"] for request in schedule
                if request["phase"] == "ordinary"
                and request["q_id"] == q_id
                and request["condition"] == condition
            ]
            values = [
                parsed_results[request_id] for request_id in request_ids
                if request_id in final_outcomes and parsed_results.get(request_id) is not None
            ]
            completed = sum(request_id in final_outcomes for request_id in request_ids)
            above = sum(
                value > threshold for value in values if threshold is not None
            )
            below = sum(
                value <= threshold for value in values if threshold is not None
            )
            if condition == "H":
                h_above += above
            elif condition == "L":
                l_above += above
            ordinary_results[q_id][condition] = {
                "request_ids": request_ids,
                "valid_values": values,
                "completed_count": completed,
                "invalid_or_missing_count": len(request_ids) - len(values),
                "above_threshold_count": above,
                "at_or_below_threshold_count": below,
                "median": statistics.median(values) if values else None,
                "geometric_mean": statistics.geometric_mean(values) if values else None,
            }

        h_result = ordinary_results[q_id]["H"]
        l_result = ordinary_results[q_id]["L"]
        h_rate = (
            h_result["above_threshold_count"] / h_result["completed_count"]
            if h_result["completed_count"] else 0
        )
        l_rate = (
            l_result["above_threshold_count"] / l_result["completed_count"]
            if l_result["completed_count"] else 0
        )
        question_contrasts[q_id] = h_rate - l_rate

    reviewer_results = {}
    for q_id in ("P01", "P02"):
        reviewer_results[q_id] = {
            "source": reviewer_input_data.get(q_id),
            "conditions": {},
        }
        for condition in ("H", "L", "N"):
            request_id = f"pilot_rev_{q_id}_{condition}"
            if request_id in final_outcomes:
                reviewer_results[q_id]["conditions"][condition] = {
                    "status": "valid" if parsed_results[request_id] is not None else "invalid",
                    "parsed": parsed_results[request_id],
                }
            elif request_id in unavailable_records:
                reviewer_results[q_id]["conditions"][condition] = {
                    "status": "unavailable",
                    "reason": unavailable_records[request_id].get("unavailable_reason"),
                    "dependency": unavailable_records[request_id].get("dependency", {}),
                }
            else:
                reviewer_results[q_id]["conditions"][condition] = {"status": "missing"}

    completed_count = len(final_outcomes)
    truncations = finish_reasons.get("length", 0)
    invalid_rate = invalid_outputs / max(1, completed_count)
    truncation_rate = truncations / max(1, completed_count)
    technical_invalid_reasons = []
    if schedule_errors:
        technical_invalid_reasons.append("invalid_schedule")
    if critical_missing_ids:
        technical_invalid_reasons.append("missing_calibration_or_ordinary_outcome")
    if unexpected_ids:
        technical_invalid_reasons.append("unexpected_request_id")
    if duplicate_success:
        technical_invalid_reasons.append("duplicate_successful_outcome")
    if threshold_source_errors:
        technical_invalid_reasons.append("threshold_source_mismatch")
    if reviewer_input_source_errors:
        technical_invalid_reasons.append("reviewer_input_source_mismatch")
    if model_mismatch_ids:
        technical_invalid_reasons.append("returned_model_mismatch")
    if invalid_rate > 0.05:
        technical_invalid_reasons.append("invalid_output_rate_above_5_percent")
    if truncation_rate > 0.05:
        technical_invalid_reasons.append("truncation_rate_above_5_percent")

    aggregate_gap = (h_above - l_above) / 8.0
    predicted_direction_count = sum(gap > 0 for gap in question_contrasts.values())
    if technical_invalid_reasons:
        decision = "technically_invalid"
        evidence = "One or more technical validity gates failed."
    elif aggregate_gap >= 0.15 and predicted_direction_count >= 3:
        decision = "proceed"
        evidence = "Technical health passed; gap >= 0.15 with predicted direction on at least 3 tasks."
    else:
        decision = "stop_or_pivot"
        evidence = "Effect size or consistency is insufficient to proceed without changes."

    report = {
        "protocol_version": manifest.get("protocol_version"),
        "analysis_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inputs": {
            "manifest": config.manifest_path,
            "schedule": config.schedule_path,
            "log": config.log_path,
            "thresholds": config.thresholds_path,
            "reviewer_inputs": config.reviewer_inputs_path,
        },
        "technical_health": {
            "scheduled_count": len(scheduled),
            "completed_success_count": completed_count,
            "unavailable_count": len(unavailable_records),
            "missing_ids": missing_ids,
            "missing_calibration_or_ordinary_ids": critical_missing_ids,
            "unexpected_ids": sorted(unexpected_ids, key=str),
            "duplicate_successful_outcomes": duplicate_success,
            "transport_attempts": transport_attempts,
            "returned_models": returned_models,
            "returned_model_mismatch_ids": model_mismatch_ids,
            "system_fingerprints": fingerprints,
            "finish_reasons": dict(finish_reasons),
            "truncation_count": truncations,
            "truncation_rate": truncation_rate,
            "invalid_output_count": invalid_outputs,
            "invalid_output_rate": invalid_rate,
            "worksheet_failure_count": worksheet_failures,
            "reviewer_failure_count": reviewer_failures,
            "reviewer_arithmetic_mismatch_count": reviewer_arithmetic_mismatches,
            "schedule_errors": schedule_errors,
            "threshold_source_errors": threshold_source_errors,
            "reviewer_input_source_errors": reviewer_input_source_errors,
        },
        "ordinary_results": ordinary_results,
        "aggregate_exploratory_contrast": aggregate_gap,
        "question_contrasts": question_contrasts,
        "predicted_direction_count": predicted_direction_count,
        "reviewer_results": reviewer_results,
        "recommendation": {
            "decision": decision,
            "technical_invalid_reasons": technical_invalid_reasons,
            "evidence": evidence,
        },
    }
    _atomic_write(config.analysis_path, report)

    print("=== Technical health ===")
    print(f"Scheduled: {len(scheduled)}; successful: {completed_count}; unavailable: {len(unavailable_records)}")
    print(f"Missing IDs: {missing_ids}")
    print(f"Unexpected IDs: {sorted(unexpected_ids, key=str)}")
    print(f"Duplicate successful outcomes: {duplicate_success}")
    print(f"Returned-model mismatches: {model_mismatch_ids}")
    print(f"Threshold-source errors: {threshold_source_errors}")
    print(f"Reviewer-input-source errors: {reviewer_input_source_errors}")
    print("\n=== Recommendation ===")
    print(f"Recommendation: {decision}")
    print(f"Evidence: {evidence}")
    if technical_invalid_reasons:
        print(f"Failed gates: {technical_invalid_reasons}")
    print(f"Wrote analysis: {config.analysis_path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a completed pilot run")
    parser.add_argument("--log", help="Path to the JSONL API-output log")
    parser.add_argument("--analysis", help="Path for the generated analysis JSON")
    args = parser.parse_args()

    config = RunConfig()
    if args.log:
        config = replace(config, log_path=args.log)
    if args.analysis:
        config = replace(config, analysis_path=args.analysis)
    try:
        analyze(config)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
