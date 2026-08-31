# Raw Evidence Experiments

This package preserves the architectures rejected before the product adopted raw transcript regions as evidence:

- global and scene-level evidence episode extraction;
- turn-function labeling and deterministic episode assembly;
- evidence episode dense retrieval;
- query-conditioned exact-span selection;
- controlled synthetic evaluation scripts and fixtures.

These modules may import production transcript/window primitives for comparison. Production code under `backend/app`, `api`, and `frontend/src` must never import this package. SQL in `supabase/` is archival research SQL and is not part of the production migration chain.

Run the archived tests from the repository root:

```bash
uv run --project backend python -m unittest discover -s research/raw_evidence_experiments/tests -p "test*.py"
```

Generated evaluation outputs belong under `results/debug/` and are ignored by Git.
