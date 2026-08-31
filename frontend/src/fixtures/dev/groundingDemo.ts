import type {
  GroundedGenerationResult,
  NoteDraftResponse,
  SessionInput,
  SupervisionReportDraft,
} from '../../types/session'

const rawAttempt = [
  '[counselor] 연습한 뒤 실제로 작은 의견을 말해본 순간이 있었나요?',
  '[client] 토요일 모임 대신 집에서 쉬고 다음번에는 가겠다고 어머니께 말했어요.',
  '[counselor] 실제로 들은 반응은 예상과 같았나요?',
  '[client] 아쉬워하시긴 했지만 다음에는 같이 가자며 받아주셨어요.',
].join('\n')

const rawRehearsal = [
  '[counselor] 오늘은 준비한 문장을 실제 대화처럼 연습해볼까요?',
  '[client] 막상 앞에 사람이 있다고 생각하면 머리가 하얘질 것 같아요.',
  '[counselor] 제가 부모 역할을 할 테니 짧게 원하는 점부터 말해보세요.',
  '[client] 걱정하시는 건 알지만 진로는 제가 더 알아보고 선택하고 싶어요.',
].join('\n')

export const groundingDemoForm: SessionInput = {
  case_id: 'SYNTH-PR5-DEMO',
  client_alias: '내담자 A',
  session_number: 8,
  session_date: '2026-08-29',
  counselor_name: '상담자 A',
  counselor_memo: '자기표현 변화와 남은 어려움을 확인함.',
  transcript_text: '[client] 작은 의견은 말할 수 있지만 목소리가 커지면 아직 긴장돼요.',
  previous_session_summary: '',
  counseling_goal: '부모와 갈등 상황에서 자신의 의견을 표현하기',
  key_issue_tags: ['자기표현', '부모 갈등'],
  target_document_type: 'session_note',
  persist: false,
}

export const groundingDemo: GroundedGenerationResult = {
  enabled: true,
  context: {
    needs: [],
    sources: [
      {
        evidence_id: 'R1', source_type: 'raw_transcript',
        source_ref: 'transcript:synthetic-session-5:0-3', source_text: rawAttempt,
        session_id: 'synthetic-session-5', session_number: 5, start_turn_index: 0, end_turn_index: 3,
        similarity_score: 0.84, retrieval_method: 'transcript_window_dense_region', need_ids: ['N1'],
      },
      {
        evidence_id: 'R2', source_type: 'raw_transcript',
        source_ref: 'transcript:synthetic-session-3:0-3', source_text: rawRehearsal,
        session_id: 'synthetic-session-3', session_number: 3, start_turn_index: 0, end_turn_index: 3,
        similarity_score: 0.81, retrieval_method: 'transcript_window_dense_region', need_ids: ['N1', 'N3'],
      },
      {
        evidence_id: 'M1', source_type: 'counselor_confirmed',
        source_ref: 'confirmed_note:synthetic-session-3:counselor_intervention',
        source_text: '상담자가 부모 역할을 맡아 자기주장 리허설을 진행하고 핵심 문장 반복에 대해 피드백함.',
        session_id: 'synthetic-session-3', session_number: 3, retrieval_method: 'case_memory_dense', need_ids: ['N2'],
      },
      {
        evidence_id: 'R9', source_type: 'raw_transcript',
        source_ref: 'transcript:uncited-candidate:0-1',
        source_text: 'UI에 노출되면 안 되는 retrieval candidate',
        session_id: 'uncited-candidate', session_number: 2, retrieval_method: 'transcript_window_dense_region', need_ids: ['N1'],
      },
    ],
    need_to_evidence_ids: { N1: ['R1', 'R2', 'R9'], N2: ['M1'], N3: ['R2'], N4: [] },
    diagnostics: {},
  },
  claims: [
    {
      claim_id: 'C1', need_id: 'N1', target_field: 'session_content',
      text: '내담자는 부모에게 쉬고 싶다는 의견을 전달하고 실제 반응을 확인했다.',
      claim_kind: 'factual', support_type: 'direct_evidence', evidence_ids: ['R1', 'R2'], review_required: false,
    },
    {
      claim_id: 'C2', need_id: 'N2', target_field: 'counselor_intervention',
      text: '상담사는 자기주장 리허설과 핵심 문장 반복을 개입으로 확정 기록했다.',
      claim_kind: 'factual', support_type: 'counselor_judgment', evidence_ids: ['M1'], review_required: false,
    },
    {
      claim_id: 'C3', need_id: 'N3', target_field: 'reflection',
      text: '구조화된 연습 경험이 실제 자기표현 시도를 촉진했을 가능성이 있다.',
      claim_kind: 'clinical_inference', support_type: 'clinical_inference', evidence_ids: ['R2'], review_required: true,
    },
    {
      claim_id: 'C4', need_id: 'N4', target_field: 'client_response',
      text: '내담자의 자기표현 불안이 완전히 해소되었다.',
      claim_kind: 'factual', support_type: 'unsupported', evidence_ids: [], review_required: true,
    },
    {
      claim_id: 'C5', need_id: 'N5', target_field: 'next_plan',
      text: '다음 회기에는 갈등 중 대화를 잠시 멈추는 문장을 연습한다.',
      claim_kind: 'factual', support_type: 'direct_evidence', evidence_ids: ['R404'], review_required: true,
    },
  ],
  citation_diagnostics: [],
  claim_support_validations: {
    C1: { verdict: 'supported', supported_evidence_ids: ['R1', 'R2'], category: null },
    C2: { verdict: 'supported', supported_evidence_ids: ['M1'], category: null },
    C5: { verdict: 'supported', supported_evidence_ids: ['R404'], category: null },
  },
  metrics: {
    citation_validity: 1,
    factual_claim_citation_coverage: 2 / 3,
    unsupported_factual_claim_rate: 1 / 3,
    semantic_support_validity: 1,
    raw_evidence_usage: 2,
    source_type_distribution: { direct_evidence: 1, counselor_judgment: 1, clinical_inference: 1, unsupported: 1 },
  },
}

export const groundingDemoNote: NoteDraftResponse = {
  case_id: groundingDemoForm.case_id,
  session_number: groundingDemoForm.session_number,
  session_summary: '내담자는 부모와의 갈등에서 작은 의견을 전달한 경험과 여전히 긴장되는 상황을 함께 점검했다.',
  main_issue: '부모와 의견이 다를 때 자신의 선호를 말하기 어렵고 갈등을 예상하면 긴장한다.',
  counselor_intervention: '자기주장 문장을 짧게 유지하는 연습과 실제 시도 결과를 검토했다.',
  client_response: '작은 의견은 표현할 수 있었으나 강한 반대 상황에서는 긴장이 남아 있다고 보고했다.',
  next_plan: '강한 갈등에서 대화를 중단하기 전 다시 이야기할 시간을 제안하는 문장을 연습한다.',
  evidence_check: [],
  missing_items: [],
  warnings: ['Synthetic grounding UI demo입니다. 실제 상담 데이터가 아닙니다.'],
  grounding: groundingDemo,
}

export const groundingDemoSupervisionReport: SupervisionReportDraft = {
  reportId: 'SYNTH-PR5-SUPERVISION',
  caseId: groundingDemoForm.case_id,
  reportType: 'personal_counseling_supervision',
  title: '개인상담 사례 수퍼비전 보고서',
  meta: {
    clientAlias: groundingDemoForm.client_alias || '내담자 A',
    sessionNumber: groundingDemoForm.session_number,
    reportDate: groundingDemoForm.session_date,
    counselorName: groundingDemoForm.counselor_name,
    institution: '마음터 상담센터',
    supervisor: '박수퍼 박사',
    supervisionDatePlace: '2026-09-02 · 수퍼비전실',
  },
  sections: [
    {
      id: 'overview', title: 'I. 주요 호소 문제 및 상담 목표', level: 1, status: 'complete', contentBlocks: [],
    },
    {
      id: 'overview-content', title: '1. 주요 호소 문제와 목표', level: 2, status: 'complete',
      contentBlocks: [{
        id: 'overview-paragraph', type: 'paragraph',
        text: '내담자는 부모와 의견이 다를 때 자신의 선호를 표현하기 어렵고 갈등을 예상하면 긴장한다고 보고하였다. 상담 목표는 갈등 상황에서 짧고 분명한 자기표현을 시도하는 것이다.',
        evidenceIds: [], aiGenerated: true, demoValue: false, reviewStatus: 'confirmed',
      }],
    },
    {
      id: 'session', title: 'II. 이번 회기 주요 내용', level: 1, status: 'complete', contentBlocks: [],
    },
    {
      id: 'session-content', title: '1. 상담 내용과 개입', level: 2, status: 'complete',
      contentBlocks: [{
        id: 'session-paragraph', type: 'paragraph',
        text: '자기주장 리허설 이후 실제로 작은 의견을 전달한 경험을 검토하였다. 내담자는 예상보다 수용적인 반응을 확인했지만, 강한 반대 상황에서는 여전히 긴장이 남아 있다고 설명하였다.',
        evidenceIds: [], aiGenerated: true, demoValue: false, reviewStatus: 'confirmed',
      }],
    },
    {
      id: 'reflection', title: 'III. 상담자 성찰 및 수퍼비전 질문', level: 1, status: 'needs_review', contentBlocks: [],
    },
    {
      id: 'reflection-content', title: '1. 상담자 성찰', level: 2, status: 'needs_review',
      contentBlocks: [{
        id: 'reflection-box', type: 'reflection_box',
        text: '실제 행동 시도를 강화하면서도 남아 있는 긴장을 성급하게 진전으로 해석하지 않았는지 점검하고 싶다.',
        evidenceIds: [], aiGenerated: false, demoValue: false, reviewStatus: 'needs_human_input',
      }],
    },
  ],
  aiReview: {
    completionChecklist: [
      { label: '주요 호소 문제', status: 'done' },
      { label: '상담 목표 및 개입', status: 'done' },
      { label: '상담자 성찰', status: 'partial', reason: '수퍼바이저와 추가 확인이 필요합니다.' },
    ],
    missingFields: [],
    demoInputs: [],
    needsHumanReview: [{ sectionId: 'reflection', message: '임상적 해석은 상담사가 확인해야 합니다.', severity: 'medium' }],
    unsupportedClaims: [],
    suggestedSupervisionQuestions: ['남아 있는 긴장을 다룰 다음 개입의 강도는 적절한가?'],
    caution: 'Synthetic UI fixture이며 실제 상담 데이터가 아닙니다.',
  },
  evidenceIndex: {},
}
