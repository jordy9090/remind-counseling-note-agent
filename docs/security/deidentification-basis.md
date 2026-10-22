# Document de-identification: what is replaced and why

Reviewed: 2026-10-22. Implementation: `backend/app/services/storage_deidentification.py` (with the contact patterns in `backend/app/services/deidentification.py`). Tests: `backend/test_storage_deidentification.py`.

## Scope

De-identification applies to **documents**: the session summary pipeline input (signed-in generation and the public quick summary), everything stored from it (stored input, sanitized copy, notes, evidence, transcript rows), counselor confirmations, temporary drafts, supervision reports saved through the FastAPI route, quick summaries saved to a client, and downloaded DOCX/PDF exports.

The **client profile** (`cases.case_alias`, `client_occupation`, `client_notes`, and the other profile columns) is the counselor's own management screen and keeps what the counselor entered. This is a product decision of 2026-10-22; profile values entered earlier while #52 was live may already be masked and are not restored.

## Rules and sources

| Item | Replacement | Example | Source |
| --- | --- | --- | --- |
| Personal names (client, family, third parties, counselor) | Keep first and last character, mask the middle with `O` | 홍길동 → 홍O동, 홍길동삼 → 홍OO삼, 민지 → 민O | PIPC 가명정보 처리 가이드라인 (2024.2) p.55: names in free text are deleted or replaced; KCPA 윤리규정 5-가-5, 5-마-1, 7-라-6 |
| Phone, e-mail, accounts/URLs, resident and student numbers, street addresses | Counselor-readable "비공개" label | 010-1234-5678 → 연락처 정보 비공개 | Guideline p.55 (names, addresses, phone numbers); direct identifiers |
| Organizations (schools, workplaces, hospitals, counseling centers, public offices, religious bodies, military units) | Organization type | 가상고등학교 → 고등학교, 한빛전자 → 회사 | 개인정보 보호법 제2조 제1호 나목 (identifiable when combined); guideline p.48 (identifiable-in-combination information judged in context), p.94 (categorize character data to a higher concept) |
| Occupation | One of 19 broad categories | 초등학교 교사 → 교육자, 연예인 → 예술가 | Guideline p.86/p.94 (generalization/categorization); KCPA 5-마-1 (change or delete personal details) |
| Current age | 10-year band; under 10 and 80+ top/bottom coded | 28세 → 20대, 85세 → 80세 이상 | Guideline pp.29-32 (age generalized to 10-year bands with top coding) |
| School grade | School level | 고2 → 고등학생, 중학교 3학년 → 중학생 | Same as age: a grade is an exact age equivalent |
| Specific place of residence/work/study (addresses, neighborhoods, apartment names, nearby landmarks) | `[지역]` | 행복동 푸른아파트 → [지역] | Guideline pp.29-31 (addresses below 시군구 deleted), p.55 |
| Birth date | `[생년월일]` | 1998년 3월 2일 → [생년월일] | Guideline p.42 (birth date removed from metadata), direct identifier in combination |

Not replaced:

- **Large regions** (서울, 부산, 경기도) and **ages of past events** ("7살 때"): low identification risk and often clinically meaningful.
- **Sensitive counseling content** (health, sexual life, beliefs; 개인정보 보호법 제23조): it is the record itself. The law requires separate consent and safety measures rather than deletion; KCPA 5-가-4 limits reports to information closely related to their purpose, which remains the counselor's judgment.
- **Unique events or traits** ("특이정보", guideline p.48, p.55): not reliably detectable; left to counselor review.

## How it works and its limits

1. One OpenAI structured-output request per save returns the mentions (names, occupations, organizations, ages, places, birth dates). The request receives the text as entered.
2. Replacement is deterministic and only for mentions that occur in the text. Contact details, explicit ages ("(28세)", "나이: 28") and school grades are also matched by regular expressions.
3. Without the model (stub mode, missing key, timeout, error) only the regular-expression rules and the known client alias are applied; free-text names, occupations, organizations and places then remain. Saving never fails because of this step.
4. The guideline itself notes that no technique detects every identifying item in unstructured text (p.40) and recommends self-review of results (p.41). This is pseudonymization support, not anonymization; the counselor reviews documents before use.

## Sources

- 개인정보 보호법 제2조 제1호 (definition of personal information, quoted in the guideline p.15), 제23조 (sensitive information).
- 개인정보보호위원회, 「가명정보 처리 가이드라인」, 2024.2 (발간등록번호 11-1790365-000029-01): pp.15, 29-32, 39-48, 52, 55, 86, 94.
- 한국상담심리학회 상담심리사 윤리규정 (https://krcpa.or.kr/user/new/sub03_1.asp): 5-가-1, 5-가-4, 5-가-5, 5-마-1, 5-마-2, 7-나-2, 7-라-6.
