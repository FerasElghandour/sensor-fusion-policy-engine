import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from fusion_compliance_loop.audit_log_exporter import export_audit_log
from fusion_compliance_loop.scenarios import SCENARIOS

st.set_page_config(page_title="Fusion Compliance Loop", layout="wide")
st.title("Fusion Compliance Loop — Operator Dashboard")
st.caption("Synthetic data only. No real sensors, classified systems, weapons, or operational data.")

scenario_names = [fn.__name__.replace("scenario_", "") for fn in SCENARIOS]
selected = st.selectbox("Scenario", scenario_names, index=0)
scenario_fn = SCENARIOS[scenario_names.index(selected)]
name, engine_or_planner, camera, result_or_outcomes = scenario_fn()

if name == "repeated_evidence_seeking_loop":
    st.subheader("Repeated evidence-seeking loop")
    st.write(f"Configured limit: **{engine_or_planner.max_requests}** requests")
    st.write(f"Requests actually made: **{engine_or_planner.requests_made}**")
    st.write("Request log:")
    for line in engine_or_planner.request_log:
        st.text(line)
else:
    result = result_or_outcomes
    engine = engine_or_planner

    st.subheader("Original observations")
    st.json(camera.model_dump(mode="json"))

    st.subheader("Camera compliance disposition (Fusion Compliance Engine)")
    cam_col1, cam_col2, cam_col3 = st.columns(3)
    cam_col1.metric("Approved", "Yes" if result.camera_approved else "No")
    cam_col2.metric("Rule", result.camera_policy_rule or "(none)")
    cam_col3.metric("AI compliance-risk score", f"{result.camera_ai_risk_probability:.0%}")
    if result.camera_blocked_fields:
        st.write("Camera fields blocked:", result.camera_blocked_fields)
    if not result.camera_approved:
        st.error("Camera detection was blocked before it could reach the fusion pipeline.")

    st.subheader("Radar candidate dispositions (every candidate, not just the winner)")
    if result.radar_dispositions:
        st.table(result.radar_dispositions)
    else:
        st.write("No radar candidates were requested for this scenario.")

    st.subheader("Matching candidates")
    if result.candidates_considered:
        st.table([c.model_dump() for c in result.candidates_considered])
    else:
        st.write("No radar candidates were requested for this scenario.")

    col1, col2 = st.columns(2)
    col1.metric("Confidence before fusion", f"{result.confidence_before:.0%}")
    col2.metric("Confidence after fusion", f"{result.confidence_after:.0%}")

    st.subheader("Requested evidence")
    for line in result.requested_evidence or ["(none requested — no missing fields)"]:
        st.text(line)

    st.subheader("Blocked information")
    st.write(result.blocked_fields or "(nothing blocked)")

    st.subheader("Applied policy rule(s)")
    st.write(result.applied_policy_rules or "(no rule triggered — nothing to fuse)")

    st.subheader("Final conclusion")
    st.success(result.explanation)

    st.subheader("Provenance chain")
    st.write(engine.provenance.trace_to_inputs(result.conclusion_id))

    st.subheader("Exportable audit log")
    log_json = export_audit_log(engine.provenance.conn, as_format="json")
    st.download_button("Download audit log (JSON)", data=log_json, file_name=f"{name}_audit_log.json")
    st.code(log_json, language="json")
