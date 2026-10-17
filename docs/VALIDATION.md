# Validation record

Release review: 17 October 2026.

206 tests passed in the release environment. A fresh evaluation covers three seeds and 3,000 synthetic missions. Mean F1 is **0.9416** for deterministic association and **0.9298** for learned association; both governed approaches record zero unauthorized field and record leakage in these cases. The learned scorer does not outperform the deterministic method.

The listed fresh checks exercise the included public edition. Historical full experiments, representative replays, and synthetic fixtures are identified separately. Test success does not certify commercial deployment.

```sh
python -m pytest -q
```

Synthetic prototype. These results establish behavior on generated cases, not operational sensor accuracy, regulatory certification, or multi-host availability. Caller-supplied authorization markers are not verified human identity. Latency measurements are in-process probes. The optional dashboard has not received fresh visual verification.
