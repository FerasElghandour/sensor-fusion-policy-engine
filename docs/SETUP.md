# Setup

The recorded verification used Python 3.12 on macOS arm64 and existing cached packages. See the exact observed versions in the saved validation JSON. No new package download, GPU rental or external model API was used for that run.

For a new environment:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

`requirements.txt` pins the directly used runtime/scientific packages; `requirements-dev.txt` adds the tested pytest/HTTP client versions. This is not a complete transitive lockfile. Clean installation and the new Linux/Python 3.11/3.12 CI matrix remain unexecuted until independently checked.

The API setup and credential requirements are in the root README and [operations guide](OPERATIONS.md). No OpenAI, Tavily or other provider keys are needed.

The optional Streamlit dashboard requires `requirements-dashboard.txt`. Its presentation has not received the same fresh end-to-end verification as the API. It can show legacy reports from `reports/`; use the validation documentation for current metric-version-2 results.

To reproduce the current benchmark protocol into a new directory:

```sh
python scripts/evaluate_system.py --output validation/new-run --mission-count 1000 --seeds 7 19 42
python scripts/check_evidence.py validation/new-run/results.json
```

The evaluator fits the two existing small synthetic models locally, warms them before timed comparisons, runs the three reference approaches and records all cases/outcomes. It also probes two in-process API applications sharing a temporary database. It never starts a public server or changes an external account.
