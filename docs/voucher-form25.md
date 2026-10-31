# Form 25 service-use contract

The voucher workspace supports manually entered Form 25 contracts before any
session note exists. Counselors enter the contract period, services, schedule,
price and subsidy/copayment split, additional costs, refund terms and optional
agreements. Names, addresses, contacts and signatures remain blank for the
institution to complete. Electronic signatures and electronic-voucher-system
registration are outside this feature.

The same immutable reviewed snapshot supplies the multi-page PDF preview and
PDF/HWPX downloads. Existing deidentification runs only during preparation;
the counselor must check the resulting terms, numbers and remaining identifying
information before marking review complete. Opening or exporting a saved
snapshot never calls a model. Editing creates a new candidate.

Form 25 uses its own manifest and fingerprint so adding it cannot invalidate
historical Form 10/26 snapshots. The renderer shares explicit line wrapping and
page breaks across PDF and HWPX, keeps all nine source clauses, escapes XML,
rejects unsupported glyphs/oversized fields and includes source attribution.
HWPX contains editable paragraphs, with no stale preview thumbnail.

Source: [Dobong's KOGL Type 1 guideline](https://welfare.dobong.go.kr/dobongBokji/bbs/BMSR00004/view.do?boardId=1771&menuNo=200113).
See [asset provenance](../backend/app/templates/vouchers/2026/source/form25-LICENSE.md)
for license terms, pinned source, blank-package license and typography changes.

Migration `20261101000100_voucher_form25.sql` adds `form25` to the existing
template constraint. It changes no grants, RLS, ownership, review trigger or
cascade behavior, and remains compatible with the preceding application.
Production rollback target for this release is deployment
`dpl_BK1iM9D3XtxYHBzWcSDBmbrPm1rw` at `4caa891`.

Validation is recorded in the task's local `tmp_ab/form25-validation-ledger.json`:
focused schema/render/review/compatibility tests, frontend build, original and
rendered PDF inspection, actual editor roundtrip, database constraint checks,
Preview/Production flows and disposable-data cleanup. No real counseling data
is used for validation.
