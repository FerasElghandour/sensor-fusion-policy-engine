"""Synthetic demonstration API with durable, revisioned policy state."""
from contextlib import contextmanager
import hmac
import json
import logging
from pathlib import Path
import sqlite3
import sys
from threading import BoundedSemaphore, Lock
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from api.config import Settings
from api.protection import BodyLimitMiddleware
from benchmarks import run_all as benchmark_run_all
from benchmarks.approaches import run_approach_a_batch, run_approach_b_batch, run_approach_c_batch
from benchmarks.metrics import compute_metrics
from fusion_compliance_loop.adversarial_generator import ADVERSARIAL_CONDITIONS, generate_missions
from fusion_compliance_loop.audit_log_exporter import export_audit_log
from fusion_compliance_loop.fusion_engine import FusionEngine
from fusion_compliance_loop.policy_engine import PolicyLoadError, load_policy_text
from fusion_compliance_loop.scenarios import SCENARIOS
from fusion_compliance_loop.service_state import RevisionConflict, ServiceState

logger = logging.getLogger("fusion.api")
security = HTTPBearer(auto_error=False)
SCENARIO_INDEX = {fn.__name__.replace("scenario_", ""): fn for fn in SCENARIOS}


class PolicyTextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=60000)


class PolicyReloadPayload(PolicyTextPayload):
    expected_revision: int = Field(ge=1, strict=True)


class BenchmarkRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_count: int = Field(default=200, ge=1, le=500, strict=True)
    seed: int = Field(default=7, ge=0, le=2**32 - 1, strict=True)
    write_reports: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = FastAPI(title="Fusion Compliance Engine", version="0.4.0",
                      docs_url=None, redoc_url=None, openapi_url=None)
    service.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    service.state.settings, service.state.store = settings, None
    initialization_lock = Lock()
    work_slots = BoundedSemaphore(settings.max_parallel_jobs)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> str:
        if not settings.reader_token or not settings.admin_token:
            raise HTTPException(503, "service credentials are not configured")
        token = credentials.credentials if credentials else ""
        if hmac.compare_digest(token.encode(), settings.admin_token.encode()):
            return "admin"
        if hmac.compare_digest(token.encode(), settings.reader_token.encode()):
            return "reader"
        raise HTTPException(401, "valid bearer credentials required", headers={"WWW-Authenticate": "Bearer"})

    def admin(role: str = Depends(authorize)):
        if role != "admin":
            raise HTTPException(403, "admin role required")

    def state() -> ServiceState:
        with initialization_lock:
            if service.state.store is None:
                service.state.store = ServiceState(settings.state_path, settings.decision_limit)
        return service.state.store

    def snapshot():
        try:
            return state().current_policy()
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(503, "policy state unavailable") from None

    @contextmanager
    def admission():
        if not work_slots.acquire(blocking=False):
            raise HTTPException(429, "worker capacity reached; retry later", headers={"Retry-After": "1"})
        try:
            yield
        finally:
            work_slots.release()

    @service.exception_handler(sqlite3.Error)
    @service.exception_handler(OSError)
    async def storage_failure(_request, _exception):
        return JSONResponse({"detail": "service storage unavailable"}, status_code=503)

    @service.middleware("http")
    async def request_metrics(request: Request, call_next):
        request_id, started = str(uuid4()), time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("request_failed id=%s type=%s", request_id, type(exc).__name__)
            response = JSONResponse({"detail": "request failed"}, status_code=500)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        logger.info("request id=%s method=%s route=%s status=%d duration_ms=%.3f",
                    request_id, request.method, getattr(route, "path", "unmatched"),
                    response.status_code, 1000 * (time.perf_counter() - started))
        return response

    @service.get("/health")
    def health():
        return {"status": "alive"}

    @service.get("/ready", dependencies=[Depends(authorize)])
    def ready():
        return {"status": "ready", "policy": snapshot().public(), "scope": "single-host shared SQLite"}

    @service.get("/policy/version", dependencies=[Depends(authorize)])
    def policy_version():
        return snapshot().public()

    @service.get("/policy/history", dependencies=[Depends(admin)])
    def policy_history(limit: int = Query(default=100, ge=1, le=1000)):
        return {"changes": state().policy_history(limit)}

    @service.post("/policy/validate", dependencies=[Depends(admin)])
    def policy_validate(payload: PolicyTextPayload):
        if not payload.text.strip():
            raise HTTPException(400, "policy text must not be empty")
        try:
            candidate = load_policy_text(payload.text)
        except PolicyLoadError as exc:
            return {"valid": False, "error": str(exc)}
        return {"valid": True, "policy_id": candidate.policy_id,
                "policy_version": candidate.policy_version, "rule_count": len(candidate.rules)}

    @service.post("/policy/reload", dependencies=[Depends(admin)])
    def policy_reload(payload: PolicyReloadPayload):
        if not payload.text.strip():
            raise HTTPException(400, "policy text must not be empty")
        try:
            updated = state().replace_policy(payload.text, payload.expected_revision)
        except PolicyLoadError as exc:
            raise HTTPException(422, f"policy rejected: {exc}") from None
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc)) from None
        return {"reloaded": True, **updated.public()}

    def retain(engine, result, source, pinned):
        chain = engine.provenance.trace_to_inputs(result.conclusion_id)
        nodes = [{"id": row[0], "kind": row[1], "payload": json.loads(row[2])}
                 for row in engine.provenance.conn.execute("SELECT id, kind, payload FROM provenance ORDER BY id")]
        state().remember_decision(result.conclusion_id, {
            "provenance_chain": chain, "explanation": result.explanation,
            "source": source, "policy_revision": pinned.revision, "policy_sha256": pinned.sha256,
            "policy_version": result.camera_policy_version,
            "provenance_nodes": nodes,
            "audit_log": json.loads(export_audit_log(engine.provenance.conn)),
        })

    @service.get("/scenarios", dependencies=[Depends(authorize)])
    def list_scenarios():
        return {"scenarios": list(SCENARIO_INDEX)}

    @service.get("/scenarios/{name}", dependencies=[Depends(authorize)])
    def run_scenario(name: str):
        if name not in SCENARIO_INDEX:
            raise HTTPException(404, "unknown scenario")
        with admission():
            pinned = snapshot()
            scenario_name, engine, camera, result = SCENARIO_INDEX[name](policy_engine=pinned.engine())
            if camera is None:
                return {"name": scenario_name, "requests_made": engine.requests_made,
                        "max_requests": engine.max_requests, "request_log": engine.request_log,
                        "outcomes": [o.value if o else None for o in result]}
            try:
                retain(engine, result, f"scenario:{name}", pinned)
                return {"name": scenario_name, **result.model_dump(mode="json"), "policy": pinned.public(),
                        "camera_observation": {"id": camera.id, "sensor_source": camera.sensor_source.value}}
            finally:
                engine.provenance.conn.close()

    @service.get("/scenarios/{name}/audit-log", dependencies=[Depends(authorize)])
    def scenario_audit_log(name: str, fmt: str = "json"):
        if name not in SCENARIO_INDEX:
            raise HTTPException(404, "unknown scenario")
        if fmt not in ("json", "csv"):
            raise HTTPException(400, "fmt must be json or csv")
        with admission():
            _, engine, camera, _ = SCENARIO_INDEX[name](policy_engine=snapshot().engine())
            if camera is None:
                raise HTTPException(400, "scenario has no audit connection")
            try:
                return {"log": export_audit_log(engine.provenance.conn, as_format=fmt)}
            finally:
                engine.provenance.conn.close()

    @service.get("/adversarial/conditions", dependencies=[Depends(authorize)])
    def adversarial_conditions():
        return {"conditions": ADVERSARIAL_CONDITIONS, "count": len(ADVERSARIAL_CONDITIONS)}

    @service.get("/adversarial/run-one", dependencies=[Depends(authorize)])
    def adversarial_run_one(seed: int = Query(7, ge=0, le=2**32 - 1),
                            index: int = Query(0, ge=0, le=499), use_ai: bool = False):
        with admission():
            pinned = snapshot()
            mission = generate_missions(n=max(index + 1, 20), seed=seed)[index]
            engine = FusionEngine(network_domain=mission.network_domain,
                                  max_sensor_requests=mission.max_sensor_requests, policy_engine=pinned.engine())
            try:
                result = engine.run(mission.camera, lambda: list(mission.radar_pool), use_ai_association=use_ai)
                retain(engine, result, f"adversarial:{mission.mission_id}", pinned)
                return {"mission_id": mission.mission_id, "tags": mission.tags, "ground_truth": mission.ground_truth,
                        **result.model_dump(mode="json"), "policy": pinned.public()}
            finally:
                engine.provenance.conn.close()

    @service.post("/benchmark/run", dependencies=[Depends(admin)])
    def benchmark_run(payload: BenchmarkRunRequest):
        if payload.write_reports:
            raise HTTPException(422, "HTTP report writes are disabled; use the offline benchmark command")
        with admission():
            missions = generate_missions(n=payload.mission_count, seed=payload.seed)
            metrics = {name: compute_metrics(missions, runner(missions)) for name, runner in {
                "A_static_threshold_no_compliance": run_approach_a_batch,
                "B_deterministic_plus_compliance": run_approach_b_batch,
                "C_ai_assisted_plus_compliance": run_approach_c_batch,
            }.items()}
            return {"wrote_reports": False, "metrics": metrics,
                    "scope": "isolated synthetic reference benchmark; does not change the active policy"}

    @service.get("/benchmark/results", dependencies=[Depends(authorize)])
    def benchmark_results():
        path = benchmark_run_all.REPORTS_DIR / "benchmark_results.json"
        if not path.exists():
            raise HTTPException(404, "no historical benchmark report available")
        return {**json.loads(path.read_text()), "result_origin": "historical report; see metric-version migration notes"}

    def find_decision(conclusion_id):
        entry = state().decision(conclusion_id)
        if entry is None:
            raise HTTPException(404, "decision not found or outside the configured retention window")
        return {"conclusion_id": conclusion_id, **entry}

    @service.get("/decisions/{conclusion_id}/provenance", dependencies=[Depends(authorize)])
    def decision_provenance(conclusion_id: str):
        return find_decision(conclusion_id)

    @service.get("/decisions/{conclusion_id}/explanation", dependencies=[Depends(authorize)])
    def decision_explanation(conclusion_id: str):
        return find_decision(conclusion_id)

    @service.get("/decisions/{conclusion_id}/audit-log", dependencies=[Depends(authorize)])
    def decision_audit_log(conclusion_id: str):
        entry = find_decision(conclusion_id)
        return {"conclusion_id": conclusion_id, "policy_revision": entry["policy_revision"],
                "policy_sha256": entry["policy_sha256"], "log": entry["audit_log"]}

    return service


app = create_app()
