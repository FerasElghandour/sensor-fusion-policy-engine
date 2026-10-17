"""Benchmark entrypoint: `python -m benchmarks.run_all`.

Generates the synthetic adversarial mission set, runs all three approaches,
computes metrics, and writes reports/ (raw results, CSV summary, markdown
report, and a failure analysis). Every number written comes from this run —
nothing here is pre-computed or invented.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from fusion_compliance_loop.adversarial_generator import ADVERSARIAL_CONDITIONS, generate_missions

from .approaches import run_approach_a_batch, run_approach_b_batch, run_approach_c_batch
from .failure_analysis import analyze_failures
from .metrics import compute_metrics

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
MISSION_COUNT = 1000
SEED = 7

APPROACHES = {
    "A_static_threshold_no_compliance": run_approach_a_batch,
    "B_deterministic_plus_compliance": run_approach_b_batch,
    "C_ai_assisted_plus_compliance": run_approach_c_batch,
}

# Grouped per application/MINIMUM_CODE_CHANGES.md's "clearly separate: entity-
# association / AI compliance-risk / deterministic enforcement" instruction.
# Every metric is still written to benchmark_summary.csv in this same order.
METRIC_GROUPS = [
    (
        "Entity-association performance (secondary — the reference fusion pipeline, not the FCE)",
        [
            ("precision", "Precision"),
            ("recall", "Recall"),
            ("f1_score", "F1 score"),
            ("false_fusion_rate", "False fusion rate"),
            ("missed_fusion_rate", "Missed fusion rate"),
        ],
    ),
    (
        "Compliance enforcement performance (primary — the Fusion Compliance Engine)",
        [
            ("policy_violation_detection_rate", "Policy violation detection rate"),
            ("unauthorized_leakage_rate", "Unauthorized field leakage rate"),
            ("unauthorized_leakage_count", "Unauthorized field leakage count"),
            ("unauthorized_record_leakage_rate", "Unauthorized record leakage rate"),
            ("unauthorized_record_leakage_count", "Unauthorized record leakage count"),
            ("missing_metadata_detection_rate", "Missing-metadata detection rate"),
            ("misclassification_detection_rate", "Misclassification detection rate"),
            ("cross_domain_violation_detection_rate", "Cross-domain violation detection rate"),
            ("protected_b_isolation_rate", "Protected B isolation rate"),
            ("false_compliance_alert_rate", "False compliance-alert rate"),
            ("audit_completeness", "Audit completeness"),
            ("provenance_completeness", "Provenance completeness"),
            ("explanation_coverage", "Explanation coverage"),
            ("evidence_loop_termination_rate", "Evidence-loop termination rate"),
            ("downstream_contamination_rate", "Downstream contamination rate"),
        ],
    ),
    (
        "Latency (compliance-enforcement path)",
        [
            ("avg_latency_s", "Avg latency (s)"),
            ("p95_latency_s", "P95 latency (s)"),
        ],
    ),
]
METRIC_ORDER = [kv for _group, kvs in METRIC_GROUPS for kv in kvs]


def main() -> dict:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()

    print(f"Generating {MISSION_COUNT} adversarial missions (seed={SEED})...")
    missions = generate_missions(n=MISSION_COUNT, seed=SEED)

    outcomes_by_approach = {}
    metrics_by_approach = {}
    for name, run_fn in APPROACHES.items():
        print(f"Running approach {name}...")
        outcomes = run_fn(missions)
        outcomes_by_approach[name] = outcomes
        metrics_by_approach[name] = compute_metrics(missions, outcomes)
        print(f"  f1={metrics_by_approach[name]['f1_score']} "
              f"leakage={metrics_by_approach[name]['unauthorized_leakage_count']} "
              f"avg_latency_s={metrics_by_approach[name]['avg_latency_s']}")

    failure_analysis = analyze_failures(missions, outcomes_by_approach)

    _write_results_json(timestamp, missions, metrics_by_approach, outcomes_by_approach)
    _write_summary_csv(metrics_by_approach)
    _write_report_md(timestamp, missions, metrics_by_approach)
    _write_failure_analysis_md(timestamp, failure_analysis)

    print(f"Reports written to {REPORTS_DIR}")
    return metrics_by_approach


def _write_results_json(timestamp, missions, metrics_by_approach, outcomes_by_approach) -> None:
    path = REPORTS_DIR / "benchmark_results.json"
    payload = {
        "generated_at": timestamp,
        "mission_count": len(missions),
        "seed": SEED,
        "adversarial_conditions": ADVERSARIAL_CONDITIONS,
        "metrics": metrics_by_approach,
        "sample_outcomes": {
            name: [
                {
                    "mission_id": o.mission_id,
                    "predicted_match_radar_id": o.predicted_match_radar_id,
                    "fused_fields_present": sorted(o.fused_fields_present),
                    "blocked_fields": o.blocked_fields,
                    "policy_action": o.policy_action,
                    "policy_id": o.policy_id,
                    "policy_version": o.policy_version,
                    "latency_s": o.latency_s,
                    "explanation": o.explanation,
                    "tags": o.tags,
                }
                for o in outcomes[:25]
            ]
            for name, outcomes in outcomes_by_approach.items()
        },
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {path}")


def _write_summary_csv(metrics_by_approach: dict) -> None:
    path = REPORTS_DIR / "benchmark_summary.csv"
    approach_names = list(metrics_by_approach.keys())
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric"] + approach_names)
        for key, _label in METRIC_ORDER:
            writer.writerow([key] + [metrics_by_approach[name][key] for name in approach_names])
    print(f"Wrote {path}")


def _write_report_md(timestamp, missions, metrics_by_approach: dict) -> None:
    a = metrics_by_approach["A_static_threshold_no_compliance"]
    b = metrics_by_approach["B_deterministic_plus_compliance"]
    c = metrics_by_approach["C_ai_assisted_plus_compliance"]

    lines = [
        "# Fusion Compliance Loop — Adversarial Benchmark Report",
        "",
        f"Generated: {timestamp}",
        f"Missions: {len(missions)} (seed={SEED}, {len(ADVERSARIAL_CONDITIONS)} adversarial conditions combined)",
        "",
        "All numbers below come from an actual run of `python -m benchmarks.run_all` "
        "against synthetic data only. See docs/BENCHMARK_METHOD.md for definitions.",
        "",
        "## Approach comparison",
        "",
    ]
    for group_name, kvs in METRIC_GROUPS:
        lines.append(f"### {group_name}")
        lines.append("")
        lines.append("| Metric | A: static threshold, no compliance | B: deterministic + compliance | C: model-based + compliance |")
        lines.append("|---|---|---|---|")
        for key, label in kvs:
            lines.append(f"| {label} | {a[key]} | {b[key]} | {c[key]} |")
        lines.append("")

    lines += [
        "",
        "## Key findings",
        "",
        f"- Approach A leaked restricted fields on {a['unauthorized_leakage_count']} of {a['mission_count']} missions; "
        f"B and C leaked on {b['unauthorized_leakage_count']} and {c['unauthorized_leakage_count']}.",
        f"- C (model-based) F1={c['f1_score']} vs A (static threshold) F1={a['f1_score']} — "
        f"{'beats' if c['f1_score'] > a['f1_score'] else 'does not beat'} the naive baseline (acceptance target 8).",
        f"- B (deterministic) F1={b['f1_score']}; C does {'not ' if c['f1_score'] <= b['f1_score'] else ''}"
        f"beat B's F1 on this run — see failure_analysis.md.",
        f"- Provenance completeness: A={a['provenance_completeness']}, B={b['provenance_completeness']}, C={c['provenance_completeness']}.",
        f"- Explanation coverage: A={a['explanation_coverage']}, B={b['explanation_coverage']}, C={c['explanation_coverage']}.",
        f"- Evidence-loop termination rate: A={a['evidence_loop_termination_rate']}, "
        f"B={b['evidence_loop_termination_rate']}, C={c['evidence_loop_termination_rate']}.",
        "",
        "See failure_analysis.md for per-condition breakdowns and remaining risks.",
    ]
    path = REPORTS_DIR / "benchmark_report.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")


def _write_failure_analysis_md(timestamp, analysis: dict) -> None:
    lines = ["# Failure Analysis", "", f"Generated: {timestamp}", ""]

    for approach, data in analysis.items():
        lines.append(f"## {approach}")
        lines.append("")
        lines.append("### Common false matches (by adversarial condition)")
        if data["common_false_matches_by_tag"]:
            lines += [f"- {tag}: {count}" for tag, count in data["common_false_matches_by_tag"]]
        else:
            lines.append("- none observed")
        lines.append("")

        lines.append("### Common missed matches (by adversarial condition)")
        if data["common_missed_matches_by_tag"]:
            lines += [f"- {tag}: {count}" for tag, count in data["common_missed_matches_by_tag"]]
        else:
            lines.append("- none observed")
        lines.append("")

        lines.append("### Latency bottleneck conditions (highest avg latency)")
        lines += [f"- {tag}: {avg * 1000:.3f} ms avg" for tag, avg in data["latency_bottleneck_tags"]]
        lines.append("")

        lines.append("### Execution errors")
        if data["error_count"]:
            lines.append(f"- {data['error_count']} error(s) observed")
            lines += [f"  - {e['mission_id']} (tags={e['tags']}): {e['error']}" for e in data["errors_sample"]]
        else:
            lines.append("- no execution errors observed")
        lines.append("")

        if data["ai_uncertain_cases"]:
            lines.append("### Scenarios where the AI model was uncertain (match probability 0.4-0.6)")
            lines += [f"- {c['mission_id']} (tags={c['tags']}): probability={c['score']}" for c in data["ai_uncertain_cases"]]
            lines.append("")

    lines += [
        "## Remaining technical risks",
        "",
        "- **Content-based disguise is only caught by field name, not field content.** The policy engine's "
        "`field_sensitivity_map` blocks by field *name*; `disguise_restricted_field` proves detection survives "
        "value obfuscation (base64) within the *same* tracked field, but relocating the payload into a field "
        "outside the map would not be caught by this mechanism. See docs/THREAT_MODEL.md.",
        "- **The model-based approach (C) does not strictly beat the deterministic baseline (B)** on every run — "
        "its synthetic training distribution differs from the mission generator's exact structure. It reliably "
        "clears the required bar (beating the static-threshold baseline A) but is not a guaranteed upgrade over B.",
        "- **Approach A has zero policy enforcement by design** — its leakage/violation numbers describe a system "
        "with no compliance controls at all, included only as a naive floor for comparison, never for real use.",
        "- **Missions are synthetic** and do not model real correlated sensor failures, timing attacks against the "
        "exact moment of a policy reload, or multi-object clutter scenes.",
        "- **Missing-metadata detection rate is not 1.0 for B/C.** The AI compliance-risk detector's escalation "
        "threshold (0.85) is not always crossed by the `missing_metadata_markings` condition alone — three of ten "
        "risk features move, but the other seven vary with the rest of the item's (otherwise normal) state. This is "
        "a real, measured gap, not rounded away — see docs/MODEL_CARD.md.",
        "- **Entity-association metrics (F1, recall) and compliance metrics must be read separately.** "
        "`camera_side_forbidden_domain` missions correctly block the camera before any radar match is attempted — "
        "correct compliance behavior — but this counts as a *missed* match under precision/recall, which is why "
        "this report groups entity-association and compliance metrics into separate tables rather than one score.",
    ]
    path = REPORTS_DIR / "failure_analysis.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
