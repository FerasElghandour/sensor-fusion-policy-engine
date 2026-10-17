import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
RESULTS_PATH = REPORTS_DIR / "benchmark_results.json"
FAILURE_ANALYSIS_PATH = REPORTS_DIR / "failure_analysis.md"

st.set_page_config(page_title="Adversarial Benchmark", layout="wide")
st.title("Adversarial Benchmark")
st.caption(
    "Every number on this page is read directly from reports/benchmark_results.json — "
    "produced by `python -m benchmarks.run_all`. Nothing here is hardcoded."
)

if not RESULTS_PATH.exists():
    st.error(
        "No benchmark results found at reports/benchmark_results.json. "
        "Run `python -m benchmarks.run_all` first, then reload this page."
    )
    st.stop()

data = json.loads(RESULTS_PATH.read_text())
metrics = data["metrics"]
APPROACH_A = "A_static_threshold_no_compliance"
APPROACH_B = "B_deterministic_plus_compliance"
APPROACH_C = "C_ai_assisted_plus_compliance"
a, b, c = metrics[APPROACH_A], metrics[APPROACH_B], metrics[APPROACH_C]

st.subheader("Run summary")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Missions tested", data["mission_count"])
col2.metric("Policy violations detected (B)", int(b["policy_violation_detection_rate"] * b["at_risk_mission_count"]))
col3.metric("Unauthorized leakage count (B)", b["unauthorized_leakage_count"])
col4.metric("Adversarial conditions combined", len(data["adversarial_conditions"]))
st.caption(f"Generated at {data['generated_at']} (seed={data['seed']})")

st.subheader("Matching precision, recall, F1 — deterministic + compliance (B)")
col1, col2, col3 = st.columns(3)
col1.metric("Precision", b["precision"])
col2.metric("Recall", b["recall"])
col3.metric("F1 score", b["f1_score"])

st.subheader("Latency — deterministic + compliance (B)")
col1, col2 = st.columns(2)
col1.metric("Average latency", f"{b['avg_latency_s'] * 1000:.3f} ms")
col2.metric("P95 latency", f"{b['p95_latency_s'] * 1000:.3f} ms")

st.subheader("Baseline comparison")
st.caption(
    "A = static threshold matching, no compliance engine. "
    "B = existing deterministic matching + compliance. "
    "C = model-based matching + the same compliance engine."
)
comparison_rows = [
    ("Precision", a["precision"], b["precision"], c["precision"]),
    ("Recall", a["recall"], b["recall"], c["recall"]),
    ("F1 score", a["f1_score"], b["f1_score"], c["f1_score"]),
    ("False fusion rate", a["false_fusion_rate"], b["false_fusion_rate"], c["false_fusion_rate"]),
    ("Missed fusion rate", a["missed_fusion_rate"], b["missed_fusion_rate"], c["missed_fusion_rate"]),
    ("Policy violation detection rate", a["policy_violation_detection_rate"], b["policy_violation_detection_rate"], c["policy_violation_detection_rate"]),
    ("Unauthorized leakage rate", a["unauthorized_leakage_rate"], b["unauthorized_leakage_rate"], c["unauthorized_leakage_rate"]),
    ("Unauthorized leakage count", a["unauthorized_leakage_count"], b["unauthorized_leakage_count"], c["unauthorized_leakage_count"]),
    ("Avg latency (s)", a["avg_latency_s"], b["avg_latency_s"], c["avg_latency_s"]),
    ("P95 latency (s)", a["p95_latency_s"], b["p95_latency_s"], c["p95_latency_s"]),
    ("Provenance completeness", a["provenance_completeness"], b["provenance_completeness"], c["provenance_completeness"]),
    ("Explanation coverage", a["explanation_coverage"], b["explanation_coverage"], c["explanation_coverage"]),
    ("Evidence-loop termination rate", a["evidence_loop_termination_rate"], b["evidence_loop_termination_rate"], c["evidence_loop_termination_rate"]),
]
st.table(
    {
        "Metric": [r[0] for r in comparison_rows],
        "A: static threshold, no compliance": [r[1] for r in comparison_rows],
        "B: deterministic + compliance": [r[2] for r in comparison_rows],
        "C: model-based + compliance": [r[3] for r in comparison_rows],
    }
)

st.subheader("Primary compliance metrics (Fusion Compliance Engine — v0.3)")
st.caption(
    "Entity-association F1/precision/recall above measure the *reference fusion pipeline*, "
    "not the compliance engine. These are the metrics that measure the FCE itself."
)
compliance_rows = [
    ("Unauthorized record leakage rate", a.get("unauthorized_record_leakage_rate"), b.get("unauthorized_record_leakage_rate"), c.get("unauthorized_record_leakage_rate")),
    ("Missing-metadata detection rate", a.get("missing_metadata_detection_rate"), b.get("missing_metadata_detection_rate"), c.get("missing_metadata_detection_rate")),
    ("Misclassification detection rate", a.get("misclassification_detection_rate"), b.get("misclassification_detection_rate"), c.get("misclassification_detection_rate")),
    ("Cross-domain violation detection rate", a.get("cross_domain_violation_detection_rate"), b.get("cross_domain_violation_detection_rate"), c.get("cross_domain_violation_detection_rate")),
    ("Protected B isolation rate", a.get("protected_b_isolation_rate"), b.get("protected_b_isolation_rate"), c.get("protected_b_isolation_rate")),
    ("False compliance-alert rate", a.get("false_compliance_alert_rate"), b.get("false_compliance_alert_rate"), c.get("false_compliance_alert_rate")),
    ("Audit completeness", a.get("audit_completeness"), b.get("audit_completeness"), c.get("audit_completeness")),
    ("Downstream contamination rate", a.get("downstream_contamination_rate"), b.get("downstream_contamination_rate"), c.get("downstream_contamination_rate")),
]
st.table(
    {
        "Metric": [r[0] for r in compliance_rows],
        "A: static threshold, no compliance": [r[1] for r in compliance_rows],
        "B: deterministic + compliance": [r[2] for r in compliance_rows],
        "C: model-based + compliance": [r[3] for r in compliance_rows],
    }
)

if c["f1_score"] > a["f1_score"]:
    st.success(f"model-based matching (F1={c['f1_score']}) beats the static-threshold baseline (F1={a['f1_score']}).")
else:
    st.warning(f"model-based matching (F1={c['f1_score']}) did NOT beat the static-threshold baseline (F1={a['f1_score']}) on this run.")

st.subheader("Most common failure categories")
if FAILURE_ANALYSIS_PATH.exists():
    with st.expander("Full failure_analysis.md", expanded=False):
        st.markdown(FAILURE_ANALYSIS_PATH.read_text())
else:
    st.info("No failure_analysis.md found yet.")

st.subheader("Example: blocked fusion attempt")
sample_outcomes = data.get("sample_outcomes", {}).get(APPROACH_B, [])
blocked_example = next((o for o in sample_outcomes if o["blocked_fields"]), None)
if blocked_example:
    st.json(blocked_example)
else:
    st.info("No blocked-field example in the saved sample (sample is a prefix of the full run).")

st.subheader("Example: provenance graph")
provenance_example = next((o for o in sample_outcomes if o.get("predicted_match_radar_id")), None)
if provenance_example:
    conclusion_label = provenance_example["mission_id"]
    camera_label = "camera_observation"
    radar_label = provenance_example["predicted_match_radar_id"][:8]
    dot = f"""
    digraph provenance {{
        rankdir=LR;
        node [shape=box, style=filled, fillcolor="#eef2ff"];
        "{camera_label}" -> "conclusion\\n({conclusion_label})";
        "radar\\n({radar_label})" -> "conclusion\\n({conclusion_label})";
    }}
    """
    st.graphviz_chart(dot)
    st.caption(f"Policy action applied: {provenance_example['policy_action']}")
else:
    st.info("No fused example available in the saved sample to draw a provenance graph from.")

st.subheader("Plain-English decision explanation (example)")
explained = next((o for o in sample_outcomes if o.get("explanation")), None)
if explained:
    st.success(explained["explanation"])
else:
    st.info("No explanation found in the saved sample.")
