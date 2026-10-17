"""Metric computation over (missions, outcomes) pairs. Every number here
comes from an actual run — see docs/BENCHMARK_METHOD.md for definitions."""

import math

from fusion_compliance_loop.adversarial_generator import Mission

from .approaches import MissionOutcome


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


_MISCLASSIFICATION_TAGS = {"missing_classifications", "incorrect_classifications"}
_CROSS_DOMAIN_TAGS = {"unauthorized_cross_domain_request", "camera_side_forbidden_domain", "protected_b_cross_domain"}


def compute_metrics(missions: list[Mission], outcomes: list[MissionOutcome]) -> dict:
    if len(missions) != len(outcomes):
        raise ValueError("missions and outcomes must be paired 1:1")
    ids = [mission.mission_id for mission in missions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate mission IDs would weight some cases more than once")
    for mission, outcome in zip(missions, outcomes):
        if mission.mission_id != outcome.mission_id:
            raise ValueError("outcomes must be in the same mission order")
        if not math.isfinite(outcome.latency_s) or outcome.latency_s < 0:
            raise ValueError("latency must be finite and nonnegative")

    tp = fp = fn = tn = wrong_match = 0
    at_risk = 0
    leaked = 0
    violation_detected = 0
    fused_mission_count = 0
    provenance_complete_count = 0
    explanation_ok = 0
    loop_ok = 0
    latencies = []
    errors = 0

    # Primary compliance metrics (v0.3 compliance-risk audit) — see
    # docs/BENCHMARK_METHOD.md and application/ for how each is used.
    record_at_risk = record_leaked = 0
    missing_metadata_total = missing_metadata_detected = 0
    misclass_total = misclass_detected = 0
    cross_domain_total = cross_domain_detected = 0
    protected_b_total = protected_b_isolated = 0
    clean_untagged_total = false_alerts = 0
    audit_eligible = audit_complete = 0
    contamination_count = 0

    for mission, outcome in zip(missions, outcomes):
        gt = mission.ground_truth
        true_match = gt["correct_match_radar_id"]
        predicted = outcome.predicted_match_radar_id

        if outcome.error:
            errors += 1

        if true_match is not None:
            if predicted == true_match:
                tp += 1
            elif predicted is not None:
                fp += 1
                # Wrong association invents one link AND misses the true link.
                # Unlike the historical metric, its recall denominator cannot
                # shrink when an approach makes more wrong non-null matches.
                fn += 1
                wrong_match += 1
            else:
                fn += 1
        else:
            if predicted is not None:
                fp += 1
            else:
                tn += 1

        must_block = gt["fields_that_must_be_blocked"]
        if must_block:
            at_risk += 1
            if any(f in outcome.fused_fields_present for f in must_block):
                leaked += 1
            else:
                violation_detected += 1

        if predicted and outcome.fused_fields_present:
            fused_mission_count += 1
            chain = set(outcome.provenance_chain)
            if mission.camera.id in chain and predicted in chain:
                provenance_complete_count += 1

        if outcome.explanation and outcome.explanation[0].isupper() and "." in outcome.explanation:
            explanation_ok += 1

        if outcome.evidence_loop_terminated:
            loop_ok += 1

        latencies.append(outcome.latency_s)

        # --- primary compliance metrics ---------------------------------
        if gt.get("expects_camera_rejected"):
            record_at_risk += 1
            if outcome.camera_approved is not False:
                record_leaked += 1

        if "missing_metadata_markings" in mission.tags:
            missing_metadata_total += 1
            if (outcome.policy_action and outcome.policy_action != "PERMIT") or outcome.ai_risk_categories:
                missing_metadata_detected += 1

        if set(mission.tags) & _MISCLASSIFICATION_TAGS:
            misclass_total += 1
            if must_block and not any(f in outcome.fused_fields_present for f in must_block):
                misclass_detected += 1
            elif not must_block:
                misclass_detected += 1

        if set(mission.tags) & _CROSS_DOMAIN_TAGS:
            cross_domain_total += 1
            record_ok = not gt.get("expects_camera_rejected") or outcome.camera_approved is False
            field_ok = not must_block or not any(f in outcome.fused_fields_present for f in must_block)
            if record_ok and field_ok:
                cross_domain_detected += 1

        if gt.get("is_protected_b"):
            protected_b_total += 1
            if not must_block or not any(f in outcome.fused_fields_present for f in must_block):
                protected_b_isolated += 1

        if not mission.tags:
            clean_untagged_total += 1
            if outcome.ai_risk_categories:
                false_alerts += 1

        if outcome.policy_action is not None:
            audit_eligible += 1
            if outcome.policy_id and outcome.policy_version and outcome.explanation:
                audit_complete += 1

        if set(outcome.blocked_fields) & outcome.fused_fields_present:
            contamination_count += 1

    n = len(missions)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "metric_version": "2.0",
        "wrong_match_count": wrong_match,
        "ground_truth_match_count": tp + fn,
        "approach": outcomes[0].approach if outcomes else "",
        "mission_count": n,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "false_fusion_rate": round(fp / n, 4) if n else 0.0,
        "missed_fusion_rate": round(fn / (tp + fn), 4) if (tp + fn) else 0.0,
        "at_risk_mission_count": at_risk,
        "policy_violation_detection_rate": round(violation_detected / at_risk, 4) if at_risk else 1.0,
        "unauthorized_leakage_rate": round(leaked / n, 4) if n else 0.0,
        "unauthorized_leakage_count": leaked,
        "avg_latency_s": round(sum(latencies) / len(latencies), 6) if latencies else 0.0,
        "p95_latency_s": round(_percentile(latencies, 95), 6),
        "provenance_completeness": round(provenance_complete_count / fused_mission_count, 4) if fused_mission_count else 1.0,
        "fused_mission_count": fused_mission_count,
        "explanation_coverage": round(explanation_ok / n, 4) if n else 0.0,
        "evidence_loop_termination_rate": round(loop_ok / n, 4) if n else 0.0,
        "error_count": errors,
        # --- primary compliance metrics (v0.3) --------------------------
        "unauthorized_record_leakage_rate": round(record_leaked / record_at_risk, 4) if record_at_risk else 1.0,
        "unauthorized_record_leakage_count": record_leaked,
        "camera_rejection_required_count": record_at_risk,
        "missing_metadata_detection_rate": round(missing_metadata_detected / missing_metadata_total, 4) if missing_metadata_total else 1.0,
        "misclassification_detection_rate": round(misclass_detected / misclass_total, 4) if misclass_total else 1.0,
        "cross_domain_violation_detection_rate": round(cross_domain_detected / cross_domain_total, 4) if cross_domain_total else 1.0,
        "protected_b_isolation_rate": round(protected_b_isolated / protected_b_total, 4) if protected_b_total else 1.0,
        "false_compliance_alert_rate": round(false_alerts / clean_untagged_total, 4) if clean_untagged_total else 0.0,
        "audit_completeness": round(audit_complete / audit_eligible, 4) if audit_eligible else 1.0,
        "downstream_contamination_rate": round(contamination_count / n, 4) if n else 0.0,
    }
