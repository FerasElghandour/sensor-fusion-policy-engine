"""Record fresh synthetic benchmark and in-process API evidence.

Usage: python scripts/evaluate_system.py --output validation/local-run
Creates a new output directory; never replaces the historical reports.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import secrets
import statistics
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from api.config import Settings
from api.main import create_app
from benchmarks.approaches import run_approach_a_batch, run_approach_b_batch, run_approach_c_batch
from benchmarks.metrics import compute_metrics
from fusion_compliance_loop.adversarial_generator import generate_missions

RUNNERS = {"A_static_threshold_no_compliance": run_approach_a_batch,
           "B_deterministic_plus_compliance": run_approach_b_batch,
           "C_ai_assisted_plus_compliance": run_approach_c_batch}


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def api_probe():
    with TemporaryDirectory(prefix="fusion-evaluation-") as directory:
        settings = Settings(state_path=Path(directory) / "state.sqlite3",
                            reader_token=secrets.token_urlsafe(32), admin_token=secrets.token_urlsafe(32))
        auth = {"Authorization": "Bearer " + settings.reader_token}
        with ExitStack() as stack:
            clients = [stack.enter_context(TestClient(create_app(settings), headers=auth)) for _ in range(2)]
            assert clients[0].get("/scenarios/normal_matching").status_code == 200

            def request(index):
                started = time.perf_counter()
                response = clients[index % 2].get("/scenarios/normal_matching")
                return {"status": response.status_code, "milliseconds": 1000 * (time.perf_counter() - started),
                        "conclusion_id": response.json().get("conclusion_id"),
                        "revision": response.json().get("policy", {}).get("revision")}

            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=8) as pool:
                records = list(pool.map(request, range(80)))
            elapsed = time.perf_counter() - started
            status = dict(Counter(str(r["status"]) for r in records))
            successful = [r for r in records if r["status"] == 200]
            assert successful and set(status) <= {"200", "429"}, status
            assert all(r["revision"] == 1 for r in successful)
            retained = successful[-1]["conclusion_id"]
            # A decision created by either worker is readable from the other.
            assert all(c.get(f"/decisions/{retained}/provenance").status_code == 200 for c in clients)
        with TestClient(create_app(settings), headers=auth) as restarted:
            survives = restarted.get(f"/decisions/{retained}/explanation").status_code == 200
        return {"transport": "in-process ASGI TestClient; no TCP/TLS/proxy",
                "app_instances": 2, "concurrent_clients": 8, "requests": 80,
                "per_instance_work_slots": 2, "status_counts": status,
                "elapsed_seconds": elapsed, "accepted_requests_per_second": len(successful) / elapsed,
                "successful_latency_ms_median": statistics.median(r["milliseconds"] for r in successful),
                "successful_latency_ms_p95": percentile([r["milliseconds"] for r in successful], .95),
                "shared_decision_lookup_passed": True, "decision_survived_app_restart": survives,
                "raw_requests": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mission-count", type=int, default=1000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 19, 42])
    args = parser.parse_args()
    if not 1 <= args.mission_count <= 10000 or not args.seeds or any(s < 0 or s >= 2**32 for s in args.seeds):
        parser.error("mission count must be 1..10000 and seeds must be unsigned 32-bit integers")
    if len(args.seeds) != len(set(args.seeds)):
        parser.error("seeds must be distinct")
    args.output.mkdir(parents=True, exist_ok=False)
    # Initialize the two local synthetic models before timing warm runs.
    for runner in RUNNERS.values():
        runner(generate_missions(n=1, seed=0))
    runs = []
    for seed in args.seeds:
        missions = generate_missions(n=args.mission_count, seed=seed)
        outputs = {}
        metrics = {}
        for name, runner in RUNNERS.items():
            outcomes = runner(missions)
            metrics[name] = compute_metrics(missions, outcomes)
            outputs[name] = [{**asdict(o), "fused_fields_present": sorted(o.fused_fields_present)} for o in outcomes]
            print(f"seed={seed} {name} F1={metrics[name]['f1_score']} errors={metrics[name]['error_count']}", flush=True)
        case_path = args.output / f"cases-seed-{seed}.json"
        case_path.write_text(json.dumps({"seed": seed, "cases": [
            {"mission_id": m.mission_id, "camera_id": m.camera.id, "tags": m.tags, "ground_truth": m.ground_truth}
            for m in missions], "outcomes": outputs}, indent=2, allow_nan=False) + "\n")
        runs.append({"seed": seed, "missions": len(missions), "metrics": metrics,
                     "case_file": case_path.name, "case_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest()})
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for folder in ("api", "fusion_compliance_loop", "benchmarks", "scripts", "policies", "tests")
                     for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in (".py", ".yaml")}
    packages = {n: importlib.metadata.version(n) for n in
                ("fastapi", "starlette", "pydantic", "networkx", "PyYAML", "scikit-learn", "numpy", "scipy", "httpx", "pytest")}
    result = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), "metric_version": "2.0",
              "scope": "synthetic missions only; warm in-process matching latency; no operational accreditation",
              "environment": {"python": platform.python_version(), "system": platform.system(),
                              "machine": platform.machine(), "packages": packages},
              "source_sha256": source_hashes, "runs": runs, "api_probe": api_probe()}
    (args.output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Evidence saved to", args.output, flush=True)


if __name__ == "__main__":
    main()
