# PoC diagnostic privacy verification

## Boundary and correction

At base `d85a9a6039aa4097f000944337e83c072311b7fa`, `run_note_pipeline` and `run_supervision_report_pipeline` pass counseling state into LangChain graphs. Environment-enabled or ambient LangSmith tracing receives those inputs independently of model review approval. Explicit collectors and global debug output also capture state. Application exception sanitization does not control these library callbacks.

`private_ai_execution` suppresses ambient/environment LangSmith tracing before either graph sees its inputs. Explicit trace/run collectors, inherited callbacks, and global debug/verbose settings fail closed in PoC. The model factory also rejects an unprotected diagnostic context. The context is request-local and restored after failure; no process-wide settings are toggled. Explicit non-PoC behavior remains unchanged. This uses the [documented tracing context](https://kb.langchain.com/articles/2491399069-how-do-i-disable-or-toggle-langsmith-tracing-during-execution), plus guards for separately configured LangChain callback paths.

## Synthetic validation

Run from the repository root with the existing locked backend environment:

```text
python backend/tests/run_poc_review.py test_poc_tracing
python backend/tests/run_poc_review.py test_poc_reviewed_history test_poc_approval
python backend/tests/run_poc_review.py --legacy test_llm_model_settings test_summary_skill_pipeline test_supervision_form
```

The protected runner blocks network, DNS, subprocesses and credential/dotenv files before importing application settings. Real library callbacks target mocks; runtime metadata collection is replaced with an empty synthetic object. No provider, LangSmith account or credentials are used.

- Before correction: six negative test cases failed (seven assertion failures including explicit-collector variants); the non-PoC positive trace control passed. The earlier missing fixture field and blocked runtime-metadata subprocess were harness problems, corrected before this red baseline.
- After correction: 11 tracing cases passed, including actual stub graph execution, supervision graph, inherited callbacks, failure/context restoration, environment flags and the non-PoC positive control. The 15 approval/history and 19 affected model/summary/supervision checks passed at the same runtime boundary (2026-11-19 07:50 UTC checkpoint).
- Independent review found an additional callback-manager representation with empty direct handlers but nonempty inheritable handlers. A real stub graph reproduced child-state capture; the guard now checks both lists. This additional red-to-green correction was verified at 2026-11-19 07:57 UTC without repeating unrelated subsystems.
- Local supervision export tests use the existing fallback when native PDF libraries are absent; real PDF rendering is a separate Product CI check.
- Synthetic data is in memory or runner-owned scratch, which is removed on exit. No accounts, database rows or deployments are created by these tests.

## Limits and release requirements

This proves the tested application/library boundary, not that deployed observability is private. Proxy/APM instrumentation, exception collectors, process dumps, operator log levels, future manually configured callbacks and provider retention still require an authorized environment review. PoC operators must leave diagnostic payload capture disabled; do not resolve a fail-closed error by disabling PoC mode. The consent notice may describe this verified tracing suppression only for the deployed reviewed version, and must not claim that all infrastructure or vendor logs are free of counseling information.
