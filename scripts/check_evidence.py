"""Independently check saved matching results, case hashes and source hashes.

This standard-library verifier does not import models or run experiments.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(path, check_sources=True):
    record = json.loads(path.read_text())
    if record["metric_version"] != "2.0":
        raise ValueError("unsupported metric version")
    for relative, expected in record["source_sha256"].items():
        if check_sources and hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f"source changed since recorded evaluation: {relative}")
    checked = 0
    for run in record["runs"]:
        cases_path = path.parent / run["case_file"]
        if hashlib.sha256(cases_path.read_bytes()).hexdigest() != run["case_sha256"]:
            raise ValueError("saved cases or predictions changed")
        saved = json.loads(cases_path.read_text())
        cases = saved["cases"]
        if len(cases) != run["missions"]:
            raise ValueError("case count mismatch")
        for approach, outcomes in saved["outcomes"].items():
            if len(outcomes) != len(cases):
                raise ValueError("outcome count mismatch")
            correct = predicted = actual = leakage = errors = record_risk = record_leaks = 0
            for case, outcome in zip(cases, outcomes):
                if case["mission_id"] != outcome["mission_id"]:
                    raise ValueError("outcome order mismatch")
                truth = case["ground_truth"]["correct_match_radar_id"]
                prediction = outcome["predicted_match_radar_id"]
                actual += truth is not None
                predicted += prediction is not None
                correct += truth is not None and truth == prediction
                leakage += bool(set(case["ground_truth"]["fields_that_must_be_blocked"]) & set(outcome["fused_fields_present"]))
                errors += outcome["error"] is not None
                record_risk += bool(case["ground_truth"].get("expects_camera_rejected"))
                record_leaks += bool(case["ground_truth"].get("expects_camera_rejected")) and outcome["camera_approved"] is not False
            precision = correct / predicted if predicted else 0
            recall = correct / actual if actual else 0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
            expected = {"precision": round(precision, 4), "recall": round(recall, 4), "f1_score": round(f1, 4),
                        "ground_truth_match_count": actual, "unauthorized_leakage_count": leakage, "error_count": errors}
            expected["unauthorized_record_leakage_count"] = record_leaks
            if "camera_rejection_required_count" in run["metrics"][approach]:
                expected["camera_rejection_required_count"] = record_risk
            for key, value in expected.items():
                if run["metrics"][approach][key] != value:
                    raise ValueError(f"seed {run['seed']} {approach} {key}: mismatch")
            checked += 1
    return {"verified_comparisons": checked, "source_files": len(record["source_sha256"]),
            "current_source_checked": check_sources, "status": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--recorded-only", action="store_true", help="check archived cases without comparing against current source")
    args = parser.parse_args()
    print(json.dumps(verify(args.results, check_sources=not args.recorded_only), indent=2))
