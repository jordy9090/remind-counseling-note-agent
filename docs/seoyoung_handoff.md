# Seoyoung handoff: session-summary release and counselor interview follow-up

Verified on 2026-10-12 (Asia/Seoul). This is the starting point for development after the demo/interview with counselor Noh Eun-jeong (노은정). It distinguishes released behavior, implementation decisions, and feedback that still needs a source.

## 1. Which version is live?

| Item | Verified state |
| --- | --- |
| Production site | <https://remind.ai.kr> |
| Deployed source commit | [`f2e74b71a406a6a69acbbe062bf8dddeef16c8db`](https://github.com/jordy9090/remind-counseling-note-agent/commit/f2e74b71a406a6a69acbbe062bf8dddeef16c8db) |
| Source branch | `codex/fix-session-summary-quality` |
| Vercel production deployment | `dpl_8p59zhFZ7eEtnDh2AxBn46nBaK7J`, `READY`; provider confirms the `remind.ai.kr` alias |
| Immutable deployment URL | <https://remind-counseling-note-agent-hntva113j-jordys-projects-654150f2.vercel.app> |
| Current `origin/main` | `e30fe3d58354b47d22b59f59a3003795e120edb6` |
| Integration PR | [PR #36](https://github.com/jordy9090/remind-counseling-note-agent/pull/36), open and not merged at verification |
| Previous healthy production | `dpl_5etEtvqpTGPnYW4jRGrkay8Nrviv`, source `e30fe3d`; retained as the release's rollback reference |

**Production currently contains changes that are not in `main`.** The October 2 release promoted the work branch. A fresh release from the old `main` can replace these features. Review and reconcile PR #36 before the next release from `main`.

This handoff adds documentation after the deployed commit. A newer branch HEAD or automatically built Preview is not evidence that Production changed. Use the pinned commit and deployment above to reproduce the demo release, and inspect the provider again before a later release.

## 2. How far does it differ from main?

The deployed commit is **6 commits ahead, 0 behind** the verified main: **49 files changed, 3,151 lines added and 110 removed**. These counts exclude subsequent handoff documentation.

| Change group | Files | Added / removed lines |
| --- | ---: | ---: |
| Runtime and configuration | 28 | 1,193 / 103 |
| Tests, evaluation, CI and DEV fixtures | 19 | 1,841 / 7 |
| Documentation | 2 | 117 / 0 |

The change is primarily generation quality, provenance, and evaluation work. It is not a new application layout. There are no new dependency versions or database migrations in this release.

| Area | Main baseline | Deployed behavior |
| --- | --- | --- |
| Summary prose | Could copy/concatenate utterances into summary fields | Third-person Korean record style, section-length targets, role/event attribution rules and one bounded quality rewrite |
| Mixed input | Memo-contained transcript could be treated as undifferentiated notes | Derives transcript and memo sources from explicit headings/speaker labels; preserves the original submitted input |
| Failed generation | Could fall back to sample output after a real generation failed | Returns an error; does not silently replace real output with a demo or save a failed generation |
| Supervision memo | Fixed placeholder | Up to two compact relational/reflection paragraphs in the existing memo section, with provisional wording |
| References | No new relational corpus | Four curated domestic references; current-session evidence remains separate from theory |
| Source presentation | Coarse/incorrect associations and a hardcoded absence-of-risk message | Uses final-summary source metadata; missing references require review; risk information comes from the response |
| Evidence validation | Low text overlap could attach unrelated turns or promote verifier warnings to grounded claims | Preserves valid supplied references, uses explicit canonical IDs, and retains verifier concerns |
| Save/reopen | Existing save/confirm workflow | Preserves new draft metadata and the counselor's edited text; AI metadata does not become the confirmed clinical body |
| Model/runtime | Earlier smaller-model defaults and shorter request budget | GPT-5.4 with low reasoning by default; 60-second provider calls, no automatic provider retries, 300-second generation function and 310-second client request timeout |

The user explicitly rejected a lens selector, additional analysis panels, repeated observation/hypothesis/alternative headings, long quotations, and bibliographies in the note body. Preserve the original UI structure. Existing source badges and their accuracy were corrected; “UI unchanged” does not mean the screen's data-mapping code is byte-identical to main.

## 3. Start work from the right source

For a fresh checkout:

```powershell
git clone https://github.com/jordy9090/remind-counseling-note-agent.git
Set-Location remind-counseling-note-agent
git fetch origin
git switch --create codex/post-interview-feedback origin/codex/fix-session-summary-quality
git log -1 --oneline
git diff --name-only f2e74b71a406a6a69acbbe062bf8dddeef16c8db HEAD
```

At this handoff, differences after the pinned deployed commit should be documentation only. Inspect any additional changes before assuming the working branch is the demo version. If PR #36 has since merged, fetch and inspect the integration result before choosing a new base. Do not reset an existing checkout with uncommitted work.

Prerequisites: Python 3.11+, uv, Node.js and pnpm. CI uses Python 3.11, Node.js 22 and pnpm 10. The October 2 Vercel build used Python 3.12.

Backend terminal, from the repository root:

```powershell
Set-Location backend
uv sync --link-mode=copy
$env:RUNTIME_ENVIRONMENT = "development"
$env:ENABLE_REAL_USER_AUTH = "1"
$env:USE_STUB = "1"
$env:ENABLE_PERSISTENCE = "0"
$env:ENABLE_RAG = "0"
$env:ENABLE_CASE_MEMORY = "0"
uv run uvicorn app.main:app --reload --host 127.0.0.1
```

Frontend terminal, from the repository root:

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

Use the existing authorized project configuration: backend values in `backend/.env`, frontend values in `frontend/.env.local`. The ordinary UI requires the frontend and backend to use the same authentication project. `USE_STUB=1` avoids model calls; it does not bypass login or validate model quality. The setup above intentionally does not exercise persistence.

For real generation, configure `OPENAI_API_KEY` securely, change `USE_STUB=0`, and use `OPENAI_MODEL=gpt-5.4`, `OPENAI_REASONING_EFFORT=low`. Never copy credentials from chat history or put server secrets in `VITE_` variables. Reuse neither another developer's ignored files nor a running local demo as an onboarding dependency.

## 4. What the AI references, and why

The active corpus is [`backend/app/data/relational_theory.json`](../backend/app/data/relational_theory.json). It contains short Korean paraphrases with source URLs, locators and limitations:

1. [한국상담학회 윤리강령](https://www.counselors.or.kr/portal/service/kca_ethic_rule), effective 2024-10-26.
2. [한국상담심리학회 상담심리사 윤리강령](https://krcpa.or.kr/user/sub02_9.asp), official web version checked for this release.
3. [소수연·장성숙 (2014), 숙련된 수퍼바이저의 수퍼비전 수행에 관한 질적 연구](https://www.accesson.kr/kcpa/assets/pdf/20772/journal-26-2-193.pdf).
4. [조은실·이지영·차윤지·백인규·양은주 (2022), 한국 상담자의 발달과 관련된 수퍼비전 요소에 대한 질적 메타요약](https://www.accesson.kr/kcpa/assets/pdf/17212/journal-34-2-259.pdf).

See [source inventory and precise locators](domestic_supervision_sources.md). The first two are ethical standards; the latter two are research findings. The concise format, interpretation boundaries and psychodynamic/relational lens are product choices, not a Korean association-mandated AI protocol or endorsement.

The current theory retrieval is a bounded local keyword/concept selection over four curated entries. It is **not** a full-text document library, vector search, or fine-tuning. It also operates separately from the optional historical-case/embedding RAG flags. Current transcript/memo content supports case observations; documents suggest what to examine and constrain overinterpretation. Nationality alone must not supply family, hierarchy, or cultural assumptions.

Counselor-facing explanation:

> 회기에서 실제로 다룬 내용과 남은 어려움을 짧게 정리하고, 관계와 상담자 반응을 돌아볼 수 있는 잠정적 이해를 덧붙였습니다. 사례의 근거는 축어록과 메모이고, 문헌은 무엇을 살펴볼지 정하는 참고입니다. 해석을 확정하거나 수퍼비전을 대신하려는 기능은 아닙니다.

## 5. What was actually validated?

The October 2 final local run submitted the complete fictional A-0/A-1/A-2 fixture to `counselor_memo`, with `transcript_text=""`. Normal parsing derived separate analysis sources. This was a real GPT-5.4 low-reasoning request through the frontend's local API proxy, with no stub or remote persistence.

- HTTP 200 in **99.406 seconds**; one final reviewed case, not a latency guarantee.
- **1,044 displayed characters**, including a **361-character, two-paragraph** supervision memo.
- Two accepted insight cards; all seven summary fields had canonical source references; all insight quotes matched their named current source; all four domestic references were linked.
- Content review preserved the differences between relationships, unconfirmed colleague disappointment, unresolved guilt, and the distinction between the counselor's reaction urge and actual intervention. It did not add homework or a claim of recovery.
- [Product CI run 36968737485](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/36968737485) passed backend regressions, Linux PDF export, frontend workflow checks and build at `f2e74b7`.
- Production release checks confirmed homepage/health HTTP 200 and application-level HTTP 401 for unauthenticated generation. A fresh logged-in Production generation/save/reopen flow was **not** completed in that release check.

The earlier failed/partial model runs informed fixes and must not be presented as successful final results. Internal verifier warnings remained available. Input-level references are not sentence-level proof; matching quote strings cannot validate their interpretation. No documented clinician approval or broad clinical-quality claim follows from these checks.

Local `.codex/` reports, screenshots and `frontend/src/fixtures/dev/local-live-result.json` are ignored and will not appear in a fresh clone. The browser demo displayed saved actual output, while the final generation used the same local API proxy after the browser confirmation dialog became unresponsive. Do not describe that final check as a complete button-to-response browser E2E. The DEV route/fixture is excluded from production builds.

## 6. Reproduce and evaluate the next candidate

The tracked input is [`backend/evaluation_cases/relational_memo_a.txt`](../backend/evaluation_cases/relational_memo_a.txt). This is a single-session excerpt from ongoing fictional counseling, used for the release; earlier session records are not provided. A later proposed first-session variant with family history and PHQ-9/GAD-7 information was **not added or evaluated**. Treat it as a separate version; do not append it to the earlier, incompatible session history.

From `backend`, inspect the plan without a paid request:

```powershell
uv run python evaluate_relational_insights.py --case memo_only_a
```

After deliberately configuring real model access, run a new candidate into a distinct ignored output file:

```powershell
uv run python evaluate_relational_insights.py --live --case memo_only_a --output ../.codex/post-interview-a-candidate.json
```

Live evaluation disables remote case retrieval, embeddings and persistence, while retaining the local theory corpus. Omit `--case` for the six-case suite; use `--repeat 3` only when assessing variation is needed and the additional model cost is intended. See [the evaluation protocol](relational_insight_evaluation.md) for clinician scoring and comparison limits.

Run affected checks after a relevant code change:

```powershell
# From backend
uv run python -m unittest test_summary_quality test_source_refs test_summary_generation_routes test_session_materials test_relational_insights test_relational_integration test_llm_model_settings test_revision_routing
```

```powershell
# From frontend
pnpm verify:summary-evidence
pnpm verify:relational-insights
pnpm verify:persistence-workflow
pnpm build
```

Save/confirm changes also require the persistence/transcript regressions in [Product CI](../.github/workflows/backend-smoke.yml). Reuse unchanged passing results; do not rerun paid generation because a documentation-only handoff changed HEAD. Record commit, model/settings, corpus version, fixed input, output path, failure details, reviewer and cleanup status for new experiments.

## 7. Interview evidence and assigned next work

The user identified Notion as the source. Both pages below were read on October 12:

- [24회차 회의록](https://app.notion.com/p/3f715f09df5a80ed9606f16441c0d299): October 12 team assignments, implementation proposals, and an embedded interview summary.
- [Re:mind | 노은정 10/2 시연·2차 인터뷰 분석](https://app.notion.com/p/3f215f09df5a81ef8a79e1992f69f5f3): October 2 interview, organized October 8, with S1/S2 timestamps and line references.

These are team-maintained notes, not a new review of the original audio or the S1/S2 files. The analysis page separates reported statements from team interpretation and identifies uncertain speaker attribution. Preserve those distinctions. Its references to a ChatGPT ZIP are not proof that the original files were reviewed for this handoff. Only product-feedback summaries are copied here; private interview details remain in the source workspace.

### Counselor feedback relevant to the product

| Reported observation | Source locator in the interview analysis | Consequence for follow-up |
| --- | --- | --- |
| Intervention summary, client response and next plan were useful | 2-4; S1 17:58, L229–232 | Preserve these outputs; measure whether they help recall a session |
| It was unclear whether the supervision memo was AI-written or counselor-written, and whose expectation a sentence described | 2-5 to 2-7; S1 16:13–16:59 and 19:12–20:42 | Make authorship and client/counselor subjects clear; do not treat the memo as clinically approved |
| AI could be a reference; concentrating sensitive records was a concern when considering a main tool | 2-8 and 5-1 to 5-13; S1 20:54 onward | Minimize identifying data and explain verified storage/access boundaries |
| A tool that helps recall a session could be useful when notes are delayed; phone-to-PC transfer should be easy | 3-6 and 3-10 to 3-11; S1 50:52 and 52:45–54:12 | Evaluate the entire upload, wait, review, edit and save flow, not generation time alone |
| Period summaries and longitudinal changes could help with long cases; the counselor may consider different details important | 4-11 to 4-14; S1 38:26–40:50 | A later feature should retain source sessions and allow counselor selection/correction |
| She preferred to shorten the final report herself | 4-5; S1 48:43–48:59 | This is a report-editing preference, not a request to remove all session summaries; the team explicitly retained optional summarization as a candidate |
| The synthetic excerpt was much shorter than a full session | 2-1; S1 05:08–06:53 | Do not present the demo as a full 50-minute-session quality evaluation |

The interview does not establish overall accuracy, a purchase commitment, measured time savings, or endorsement of the four selected domestic references. No new named reference recommendation was identified in these notes. Follow up on preferred manuals, association/institution criteria, chapters and pages before replacing the corpus again. A colleague's reported use of academic files and AI dialogue does not identify a specific RAG or fine-tuning implementation.

### Assignments recorded in the 24th meeting

| Owner named in the minutes | Recorded work | Boundary/status at this handoff |
| --- | --- | --- |
| Seoyoung (서영) | Deidentify important information before database storage | Next implementation task; the current release is not certified to remove every identifying detail |
| Seoyoung (서영) | Revise initial client-information entry; check the Figma connection/work | Next design/implementation task; no new Figma design or form change was made in this handoff |
| Rami | Determine who can access records, STT and audio, including whether operators/developers can be prevented from reading them | Architecture/access investigation; masking or user-scoped access alone does not establish operator blindness |
| Suyeon (수연) | Try summarization without login; lower-priority transcript correction; introduction post | Coordinate interfaces; the existing authenticated production API still rejects anonymous generation |

The remaining meeting sections discuss mobile upload, period summaries, AI/human memo separation, onboarding preferences, and transcript timing. Treat their technical prescriptions as proposals to check against code and requirements, not evidence of shipped functionality. In particular, do not simply enable historical retrieval flags or promise deletion/access guarantees based on those notes.

### Current implementation facts for those assignments

This is a focused source map at the deployed commit, not a remote database inspection or complete security assessment:

- `sanitize_input()` in `backend/app/graph/nodes.py` applies the regex-based `deidentify_sources()` to six narrative fields. This does not cover every metadata/profile field or every narrative name, age and occupation.
- `SAVE_ORIGINAL_INPUT` defaults to **true** in `backend/app/core/config.py`. `_session_raw_input()` in `backend/app/services/supabase_storage.py` gives it precedence and uses the original submitted material for `sessions.raw_input_text`; sanitized input is stored separately. The meeting's statement that `SAVE_RAW_INPUT=false` means originals are off is incomplete. Actual Production flag values and stored rows were not inspected in this handoff.
- Turning off original-input storage alone does not apply one policy to all persistence: `draft_store.py` uses `temporary_draft_payload()` to project temporary-draft fields, and case profiles have their own create/update paths. An allowlist is not deidentification. Include these paths in the policy and tests.
- `ClientFormModal.tsx` currently requires alias/name, gender, age, occupation, marital status, family composition and phone. Backend `ClientProfileFields` already makes the eight profile attributes optional; case creation requires `case_alias`. Start collection reduction with frontend validation/layout and the agreed field policy rather than assuming a new schema is necessary.

Original-input reopening is existing behavior. Changing retention affects both future writes and existing records; plan the treatment of each explicitly. This handoff changes neither settings nor stored data.

### Suggested first work package for Seoyoung

1. Start from the branch in section 3. Inspect PR #36 and the deployed baseline before another main-based release. The current task does not merge or redeploy it.
2. Map identifying data from client fields, memo/transcript, generated fields and temporary drafts to each actual write/read path. Agree the treatment of names, contact details, ages, jobs, originals and re-identification mappings. Define what remains useful to the counselor before changing storage.
3. Implement the agreed policy using synthetic fixtures. Proposed acceptance examples: direct identifiers and narrative names are handled before each in-scope persistent write; age/job generalization follows an explicit policy; edit/save/confirm/reopen does not restore excluded raw values; display and export use the same intended data. Include clinician-relevant meaning preservation in review. These are proposed checks, not assertions that the current release passes them.
4. Reduce initial client-information collection according to the agreed design and verify the Figma target with the team. Ensure a minimal authorized case can generate, edit, save and reopen without requiring unnecessary contact information. Coordinate with Suyeon's separate anonymous-tryout work instead of removing production authentication incidentally.
5. Coordinate storage/access promises with Rami. Record which actor can read which data, including privileged backend/provider access and backups; do not label the service anonymous, end-to-end encrypted, or inaccessible to operators without implementing and verifying that property.

Preserve the original demo UI while this is a documentation handoff. The meeting's future form/onboarding/memo proposals are recorded for subsequent design work; they have not been applied here. Keep the earlier compact-note requirement distinct from a future optional report-shortening control.

After these changes, close the authenticated generation/edit/save/reopen validation gap from section 5. If summary behavior changes, compare the fixed A fixture and relevant evaluation cases with unchanged model/corpus settings; use repeated live calls only when needed. The first-session/family-history/test-results variant is separate, untested work and must not be mixed into the older A fixture.

For each accepted item, record its Notion section/date, observation, team decision, acceptable-output example, owner, affected files and validation. The source notes' institutional requirements and legal opinions have not been independently established by this handoff.

Known engineering limits: synchronous generation can be slow; per-call limits do not guarantee an overall duration below 300 seconds when repair is needed; insight validation may abstain; exact quote/source checks do not establish semantic fidelity; one synthetic run is insufficient to choose a general clinical strategy.

## 8. File map for follow-up

| Task | Start here |
| --- | --- |
| Summary wording, length, attribution, canonical IDs | `backend/app/graph/nodes.py`, `backend/app/services/summary_quality.py`, `backend/app/schemas/note.py` |
| Relational interpretation and compact memo | `backend/app/services/relational_insights.py`, `backend/app/schemas/insight.py` |
| Domestic references and limits | `backend/app/data/relational_theory.json`, `docs/domestic_supervision_sources.md` |
| Memo/transcript parsing | `backend/app/services/session_materials.py`, `backend/app/services/transcript_storage.py` |
| Existing UI rendering and evidence badges | `frontend/src/lib/relationalInsights.ts`, `frontend/src/lib/summaryEvidence.ts`, `frontend/src/pages/SessionDraftPage.tsx` |
| Save, confirm and reopen | `frontend/src/lib/persistenceWorkflow.ts`, `frontend/src/lib/temporaryDraft.ts`, `backend/app/services/temporary_draft_payload.py`, `backend/app/services/supabase_storage.py` |
| Pre-storage deidentification and original-input policy | `backend/app/services/deidentification.py`, `backend/app/graph/nodes.py`, `backend/app/core/config.py`, `backend/app/services/draft_store.py`, `backend/app/services/supabase_storage.py` |
| Initial client information | `frontend/src/components/clients/ClientFormModal.tsx`, `frontend/src/pages/SessionDraftPage.tsx`, `frontend/src/api/client.ts`, `backend/app/schemas/note.py`, `backend/app/api/routes/cases.py` |
| Model/timeouts | `backend/app/core/config.py`, `backend/app/services/llm.py`, `frontend/src/api/client.ts`, `vercel.json` |
| Evaluation and required checks | `backend/evaluate_relational_insights.py`, `backend/evaluation_cases/`, `.github/workflows/backend-smoke.yml` |

Deployment caution: promoting a Preview rebuilds with Production environment variables. For a future release, stage the intended production build, verify it, then promote that build. No production environment changes, new release, database operations or merge are part of this documentation handoff.
