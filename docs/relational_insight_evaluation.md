# Relational insight evaluation

The new output must help a counselor inspect a session, separate observation from interpretation, and formulate better supervision questions. A valid citation or a plausible hypothesis does not establish clinical accuracy. This protocol separates software contracts from clinician judgment and from the existing session-summary repair.

## Run the fixed-case evaluation

The harness contains five fictional Korean cases, created independently of the user's supplied counseling material, plus the supplied A-case evaluation fixture. The fictional cases cover multiple relationship episodes and a here-and-now interaction, sparse unrelated information, a single episode with contrary evidence, and an identical conversation with versus without an explicit counselor reflection. The last pair checks whether the model invents the counselor's inner experience when the note omits it.

The `memo_only_a` case reads `backend/evaluation_cases/relational_memo_a.txt` verbatim. The entire A-0/A-1/A-2 material goes into `counselor_memo`; `transcript_text` is the empty string. The harness does not split headings or distribute passages across fields. The application may derive separate sanitized sources during its normal input processing, while the report preserves the original submitted fields and the fixture hash. The relational processing follows the automatic application default; the harness does not set an insight lens.

From the repository's `backend` directory, using its existing Python environment:

```powershell
.\.venv\Scripts\python.exe evaluate_relational_insights.py --help
.\.venv\Scripts\python.exe evaluate_relational_insights.py
```

Without `--live`, the script loads local fixture files and lists the planned cases with field lengths. It does not load app settings, generate model output, write a report, or assign scores. The developer has not run the live evaluation as part of adding this harness. The supplied memo-only path can be checked without printing its contents:

```powershell
.\.venv\Scripts\python.exe evaluate_relational_insights.py --case memo_only_a
```

When ready to run actual generation, configure `OPENAI_API_KEY`, the intended `OPENAI_MODEL`, and `USE_STUB=0` using the application's normal environment configuration. Never put a key in this document, a command argument, or a committed result. Then choose the full suite or the memo-only run:

```powershell
.\.venv\Scripts\python.exe evaluate_relational_insights.py --live --output ..\.codex\relational-candidate.json
.\.venv\Scripts\python.exe evaluate_relational_insights.py --live --case memo_only_a --output ..\.codex\relational-memo-a-candidate.json
```

This command incurs real model requests. Each pipeline run can make several calls, including summary generation and repair. The script checks for a nonempty key and refuses stub mode before calling the pipeline; provider authentication still determines whether the configured key is valid. It does not replace failed live output with a demo. Use `--case pattern_and_here_now` to narrow the first trial. Once the candidate is stable, `--repeat 3` records variation across three runs of each selected case; this increases cost.

Live mode sets `enable_rag`, `enable_persistence`, `enable_case_memory`, `enable_dense_retrieval`, and `enable_raw_region_grounding` to false before importing the pipeline. Each `SessionInput` uses `persist=False`. This excludes remote case memory, embeddings, and database persistence; local retrieval of the curated theory cards remains active. Only the selected fixed evaluation inputs are sent to the configured model service. No accounts or remote records are created, so there is no database cleanup step.

The default report is `.codex/relational-evaluation.json` at the repository root. `--output` chooses another local path and replaces an existing report at that path. Use different paths for baseline and candidate. The report contains the evaluation inputs, sanitized inputs, summary and internal insight outputs, source IDs, configured model, commit and working-tree state, relevant file hashes, timing, mechanical checks, and blank clinician score sheets. Console output is limited to case IDs, statuses, counts, and check names; it omits source/model text and exception details.

Exit code 0 means the mechanical checks completed successfully. Exit code 1 means at least one run failed a mechanical check or the pipeline raised an error. Exit code 2 means configuration or local execution prevented evaluation. None of these codes is clinical approval. A partial JSON report is saved after each completed run so an interrupted run can be inspected without claiming the full suite finished.

## Inspect the application

Use the original application workflow. Paste the complete A fixture into the existing counselor-memo field, leave the transcript field empty, and generate the ordinary session summary. Relational analysis runs automatically and its clinician-facing content appears in the existing supervision-memo section. Check the summary and that section for grounded observations, tentative relational understanding, alternatives, missing or contrary evidence, and usable supervision questions. Review current-session evidence and theory-source IDs in the local evaluation report as needed. For sparse input, check that the section refrains from unsupported interpretation. If the insight service is unavailable, check that the ordinary summary remains usable.

For `memo_only_a`, the reviewer must explicitly verify all of the following:

- The other person's disappointment is not presented as an observed fact when it was not directly expressed; the client's expectation or perception remains attributed to the client.
- Each relationship described in the material remains distinct, including the counselor–client relationship. Similarities are explored as hypotheses rather than merging people or events.
- Lingering guilt and unresolved difficulty remain visible; speaking more openly does not become a claim of recovery or resolution.
- No behavioral assignment, homework, or agreed plan is added unless it appears in the supplied material.
- Developmental history, psychological-test findings, and diagnoses absent from the material are not invented.
- The counselor's reported urge to reassure and explain the silence is attributed to the counselor's note, while its possible significance remains open to reflection.
- The material is handled through the existing summary and supervision-memo workflow.

This visual walkthrough checks presentation and workflow. The CLI report checks the backend generation path. Neither substitutes for the other. Do not import evaluation output into an actual client's record or approve it as a confirmed clinical note.

## Blind baseline and candidate comparison

1. Freeze the evaluation cases, field placement, model identifier, generation settings, and theory corpus version. Record each compared commit or file hash and model. Compare the same inputs with the same case-memory settings. For A, both versions receive the entire fixture in the memo and an empty transcript. The initial baseline is the existing concise session summary and supervision-memo behavior; mark insight-only dimensions as not applicable when the baseline offers no interpretation. For later insight iterations, compare the prior implementation with the candidate.
2. Generate the baseline and candidate into separate local reports. A baseline commit without this harness or insight schema should be run through its original generation entry point with the identical evaluation inputs; do not alter it to make the candidate harness fit. Record the exact command and baseline limitations. Do not present a hand-written example as model output.
3. Have a coordinator assign anonymized A/B labels and shuffle display order, keeping the mapping separate. Give reviewers the source material and the same existing summary sections, but hide implementation names, model metadata, and timing during scoring. If one version visibly lacks interpretive content, blinding is necessarily partial; record this limitation.
4. Prefer two qualified counselors or supervisors, including someone familiar with relational or psychodynamic work. Each independently scores the anchored dimensions below and records supporting output excerpts or evidence references. Use `null` with a reason when a dimension is not applicable; do not convert unreviewed fields to zero or average them into a score.
5. Discuss disagreements only after independent ratings are saved. Compare evidence accuracy, unsupported claims, actionable questions, unnecessary interpretive burden, and review time. Track serious mistakes separately; a high average does not offset an invented diagnosis or attribution.
6. Run a stable candidate at least three times per case to inspect variability. Expand the synthetic case set before claiming broad performance, especially for cultural context, fragmented speaker labels, notes that disagree with transcripts, and nonrelational sessions. Changes to the prompt, model, retrieval corpus, or validation logic invalidate the matching prior results.

## Clinician rubric

The following anchors are product evaluation criteria, not a validated clinical instrument. Each dimension receives 0, 1, or 2; the default is blank until a human reviews the output.

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Evidence accuracy | Invents or contradicts events, speakers, or meaning; misuses a theory citation as case evidence. | Mostly faithful, but overstates an inference or uses an unclear reference. | Observations accurately reflect the current sources, roles, and qualifiers; references support the specific observation. |
| Relational sequence and roles | Confuses wish, perceived other response, and self response; declares recurrence from one episode. | Identifies part of the sequence, with weak differentiation or an unexamined connection to the session. | Differentiates the sequence and speaker perspectives, compares only supported episodes, and marks here-and-now links as hypotheses. |
| Alternatives and counterevidence | Gives no substantive alternative or ignores an explicit contradiction. | Includes a generic alternative or an unclear missing-information statement. | Gives a plausible competing explanation and identifies a specific contrary fact or explicitly missing evidence. |
| Appropriate abstention | Forces a relationship interpretation or causal claim from inadequate data. | Acknowledges uncertainty but still supplies unnecessary speculation. | Abstains when needed, limits the claim to available material, and identifies what additional evidence could distinguish interpretations. |
| Practical supervision questions | Gives a diagnosis, directive prescription, or vague stock advice. | Questions are relevant but broad or repeat the hypothesis. | Open questions point to a specific interaction, counselor reflection, or evidence that could support or weaken the hypothesis. |
| No diagnosis or invented therapist feelings | Invents a diagnosis, developmental cause, motive, or counselor emotion; treats it as fact. | Avoids explicit invention but uses language that obscures inference or whose perspective is represented. | Keeps diagnoses and unobserved causes out, attributes counselor self-report to the note, and leaves unknown inner states as questions. |

Before a clinician pilot, require no critical failures on the fixed set and documented reviewer agreement that the insights add practical value. Critical failures include invented evidence, unsupported diagnostic or developmental assertions, therapist feelings presented as fact without a self-report, and a speculative interpretation entering a confirmed record as an established fact. Scores and this release threshold do not demonstrate improved treatment outcomes or replacement of human supervision.

## Mechanical checks and their limits

The harness checks response availability, non-demo mode, internal status/card-count consistency, bounded and unique internal cards, review flags, source-ID membership, and whether evidence quotes occur in their named current sanitized source. For `memo_only_a`, it additionally verifies that the submitted memo equals the complete fixture and the submitted transcript is empty. Sanitized sources derived by the normal application parser are not treated as new user inputs. The harness also checks abstention on the sparse fixture and rejects a counselor-reflection card when its paired case contains no explicit self-report. Empty cards on other cases still require human review: mechanical validity alone can hide an unhelpfully silent system.

Substring citation checks cannot determine whether a passage entails the observation. A source ID can be real while its principle is misapplied. Schema checks cannot establish a relationship pattern, clinical effectiveness, or the absence of every invented feeling elsewhere in a card. These remain clinician review tasks.

## Separate validation of the summary repair

Review the ordinary summary for concise third-person record style, accurate speaker roles, factual fidelity, and preservation of unresolved difficulties. Compare it with the original summary behavior separately from evaluating theory-informed content in the existing supervision memo. Interpretive content must not excuse copied dialogue, speaker mixing, fabricated plans, or unsupported claims of improvement in the core summary.

The report stores `human_summary_review` separately from `human_insight_review`. Existing summary quality tests remain relevant software checks, but a successful test suite does not replace checking actual model-generated Korean summaries. The summary can remain valid when insight generation abstains or is unavailable; keep those outcomes distinct.

## Validation ledger

For each reviewed candidate, record commit/hash, model, environment, exact command, result, UTC timestamp, reviewer IDs, unresolved issues, and output location. For these isolated fixed-case CLI runs, record remote cleanup as not applicable. Keep source material and generated reports local and out of repository commits unless they have been intentionally reviewed for sharing.
