import { RetrievedTemplateContext } from '../types/session'

export interface DemoEvidenceItem {
  id: string
  sourceType: 'transcript' | 'counselor_memo' | 'previous_summary' | 'ai_inference'
  sourceLabel: string
  excerpt: string
  rationale: string
  warning?: string | null
}

export interface DemoDraftSection {
  id: string
  title: string
  content: string
  status: 'connected' | 'needs_review'
  evidenceIds: string[]
  missingNotice?: string
}

export interface DemoClientInfo {
  name: string
  caseId: string
  sessionNumber: number
  sessionDate: string
  counselorName: string
  counselingGoal: string
  institution: string
  supervisor?: string
  supervisionDatePlace?: string
}

export interface CounselorDemoFixtureData {
  clientInfo: DemoClientInfo
  sections: DemoDraftSection[]
  evidences: Record<string, DemoEvidenceItem>
  missingItems: string[]
  warnings: string[]
  templateContext?: RetrievedTemplateContext
}

export const COUNSELOR_DEMO_FIXTURE: CounselorDemoFixtureData = {
  templateContext: {
    target_document_type: 'supervision_report',
    required_fields: [
      'session_metadata',
      'case_id',
      'session_number',
      'session_date',
      'presenting_problem',
      'family_relations',
      'counseling_goal',
      'session_content',
      'counselor_reflection',
      'next_plan'
    ],
    optional_fields: [
      'nonverbal_observation',
      'psychological_tests'
    ],
    counselor_review_fields: [
      'case_conceptualization',
      'supervision_questions'
    ],
    missing_field_checklist: [
      'family genogram outline',
      'direct client quotes',
      'prior counseling details',
      'suicide risk screening'
    ],
    source_refs: [
      'kb:supervision-report-template-v1:1',
      'kb:supervision-report-template-v1:demographics',
      'kb:supervision-report-template-v1:family-dynamics',
      'kb:supervision-report-template-v1:session-excerpts',
      'kb:supervision-report-template-v1:reflection-goals'
    ]
  },
  clientInfo: {
    name: '김민서 (가명)',
    caseId: 'CASE-2026-05',
    sessionNumber: 5,
    sessionDate: '2026.05.30',
    counselorName: '이수진',
    counselingGoal: '취업 준비 과정의 대인 비교 불안 완화 및 완벽주의적 사고 재구성',
    institution: '마음연결 심리상담센터',
    supervisor: '김OO 상담심리사',
    supervisionDatePlace: '2026.05.30 14:00 / 사례회의실',
  },
  sections: [
    {
      id: 'A-1',
      title: 'A-1. 인적사항',
      content:
        '내담자는 24세 대학 4학년 여학생으로, 현재 졸업과 공채 취업 준비를 병행하고 있다. 주거 형태는 부모님과 동거 중이며 종교는 무교로 보고되었다. 최근 대형 공기업의 1차 서류 합격 소식을 들은 직후부터 발표와 면접 상황에 대한 불안을 강하게 호소하고 있다. 경제적 부양 수준이나 구체적인 학업 평점 등의 세부 사항은 접수면접지를 통해 추가 확인이 필요하다.',
      status: 'connected',
      evidenceIds: ['ev_1'],
    },
    {
      id: 'A-2',
      title: 'A-2. 상담신청경위',
      content:
        '내담자는 진로 결정 과정에서 주변 동기들에 비해 준비가 늦었다는 생각이 반복되자, 자발적으로 센터를 찾았다. 이전에는 무기력감을 혼자 견뎠으나 취업 준비가 본격화되면서 수행 불안이 신체화 증상으로까지 이어져 개입을 원했다. 특히 부모님의 높은 기대에 부응하지 못해 실패할 것이라는 두려움이 상담 신청의 결정적 계기로 작용했다. 자발적 내원이나 신청 상세 경로는 초기 기록을 대조하여 보완이 필요하다.',
      status: 'connected',
      evidenceIds: ['ev_2'],
    },
    {
      id: 'A-3',
      title: 'A-3. 주 호소문제',
      content:
        '취업 준비 및 수행 상황에서 자신을 타인과 끊임없이 비교하며 비난하는 양상을 보인다. 서류 합격 후 면접 연습 대본을 작성해야 함에도 "내가 잘할 리 없다", "면접장에서 버벅거리면 다 망할 거다"는 생각에 시달리며 과제를 미루는 회피 패턴이 두드러진다. 불안이 높은 날에는 답답함과 두통을 호소하고 있으며, 최근 2주간 야간 불면이 동반되는 상태이다. 신체 증상의 의학적 배제 여부는 추가적인 모니터링이 요구된다.',
      status: 'connected',
      evidenceIds: ['ev_3', 'ev_4'],
    },
    {
      id: 'A-4',
      title: 'A-4. 이전 상담 경험',
      content:
        '대학 학생상담센터나 사설 기관을 포함하여 과거에 전문적인 심리상담을 받아본 경험은 없는 것으로 나타났다. 다만 고등학교 시절 진로 탐색을 위한 집단 상담에 1회 참여한 적이 있으나, 개인적인 심리적 어려움을 주제로 심층 상담을 진행한 적은 이번이 처음이다. 이전 상담 경험이 전혀 없기 때문에 상담 관계 형성 초기 구조화가 중요하게 작용하였다.',
      status: 'connected',
      evidenceIds: ['ev_5'],
    },
    {
      id: 'A-5',
      title: 'A-5. 가족관계',
      content:
        '부모님과 남동생으로 구성된 4인 가정이며, 아버지는 권위적이고 성취 지향적인 편이다. 어머니는 내담자를 지지해주지만 내심 은근히 취업 성과를 기대하는 태도를 보여 내담자에게 은밀한 압박으로 작용하고 있다. 어린 시절부터 "가족의 기대를 저버리면 안 된다"는 신념이 학습되었고, 이것이 현재의 수행불안과 과도한 책임감으로 연결된 양상이다. 구체적인 가계도와 세부 관계망은 추가 면담을 통해 보완할 예정이다.',
      status: 'connected',
      evidenceIds: ['ev_6'],
    },
    {
      id: 'A-6',
      title: 'A-6. 인상 및 행동특성',
      content:
        '단정하고 깔끔한 차림새로 내원하였으나, 대화 중 손가락을 자주 만지작거리며 불안정한 시선 처리를 보였다. 자신의 학업이나 준비 수준을 설명할 때 한숨을 자주 쉬며 자책감을 적극적으로 표현하였다. 면접 장면을 시뮬레이션할 때는 목소리가 작아지고 문장을 끝맺지 못하는 급박한 호흡 곤란 증상을 일시적으로 관찰하였다. 호흡 훈련과 인지 재구성 개입 이후에는 어조가 다소 차분해지며 신체적 이완 상태를 회복하였다.',
      status: 'connected',
      evidenceIds: ['ev_7'],
    },
    {
      id: 'A-7',
      title: 'A-7. 심리검사 결과 및 주요 해석내용',
      content:
        '접수 면접 시 진행한 진로흥미검사 결과 사회형과 탐구형 흥미가 유의미하게 높게 확인되었다. 상태불안 척도는 상위 10%에 해당하여 현재 평가 국면에서 급격한 신체적, 심리적 불안을 경험하고 있음을 뒷받침한다. 단, 본 평가 결과는 현재의 급성 스트레스 반응을 이해하기 위한 참고 수치로만 활용하고 있으며 임상적 진단 근거는 아니다.',
      status: 'connected',
      evidenceIds: ['ev_8'],
    },
    {
      id: 'A-8',
      title: 'A-8. 내담자 강점 및 자원',
      content:
        '내담자는 자신의 불안 상태를 인지하고 이를 변화시키고자 하는 자발적인 치료적 동기가 높다. 면접 발표 장면에서 자동사고를 사실과 의견으로 객관화하여 구분하려는 연습에 적극적으로 동참하였다. 회기 말에 제시된 구체적인 모의 과제 수행 및 행동 과제(간단한 메시지 발송 등)에 순응하고 동의하는 등 실행 자원이 우수하다.',
      status: 'connected',
      evidenceIds: ['ev_9'],
    },
  ],
  evidences: {
    ev_1: {
      id: 'ev_1',
      sourceType: 'transcript',
      sourceLabel: '초기 면담 기록 (04:12)',
      excerpt:
        '내담자: "나이는 스물넷이고 대학교 4학년이에요. 부모님이랑 같이 살고요. 종교는 없어요. 이번에 서류는 붙었는데 면접 볼 생각 하니 잠이 안 와요."',
      rationale: '내담자가 직접 밝힌 인적사항 및 동거 여부 기록',
    },
    ev_2: {
      id: 'ev_2',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (10:15)',
      excerpt:
        '내담자: "취업 준비를 본격적으로 시작하면서 머리도 아프고 잠도 통 못 자요. 혼자 해결해 보려고 노력해 봤는데 더는 안 될 것 같아서 고민 끝에 신청했어요."',
      rationale: '진로 문제로 인한 신체화 증상 및 상담 신청 계기',
    },
    ev_3: {
      id: 'ev_3',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (15:20)',
      excerpt:
        '내담자: "서류는 합격했는데 면접이 너무 무서워요. 내가 잘할 리가 없고, 면접장에서 버벅거리면 다 망할 거 같아요. 대본도 자꾸 미루고 안 써요."',
      rationale: '타인 비교, 수행 불안, 면접 준비 미루기 등 주요 호소 사항',
    },
    ev_4: {
      id: 'ev_4',
      sourceType: 'counselor_memo',
      sourceLabel: '상담사 관찰 기록',
      excerpt:
        '내담자는 발표 상황을 상상할 때 가슴 답답함과 신체적 긴장감을 두드러지게 호소함.',
      rationale: '상담 회기 중 관찰된 불안의 신체화 양상',
    },
    ev_5: {
      id: 'ev_5',
      sourceType: 'transcript',
      sourceLabel: '초기 접수 면담 (08:45)',
      excerpt:
        '내담자: "학교 상담센터 같은 데는 한 번도 안 가봤어요. 고등학교 때 진로 검사 한 번 해본 게 전부예요."',
      rationale: '이전 상담 경험 여부 및 구조화 배경 정보',
    },
    ev_6: {
      id: 'ev_6',
      sourceType: 'transcript',
      sourceLabel: '3회기 축어록 (22:40)',
      excerpt:
        '내담자: "아빠는 늘 완벽해야 한다고 하시고 엄마도 이번엔 꼭 대기업 가야지 하셔서 마음이 무거워요. 가족 기대를 저버리는 것 같아서요."',
      rationale: '가족의 기대 수준 및 완벽주의 신념의 형성 배경',
    },
    ev_7: {
      id: 'ev_7',
      sourceType: 'counselor_memo',
      sourceLabel: '행동 관찰 기록',
      excerpt:
        '내원 시 다소 경직된 자세를 취하고 손을 가만히 두지 못함. 한숨이 잦고 질문에 대답할 때 끝맺음을 주저함.',
      rationale: '상담 장면에서의 비언어적 긴장 및 행동 특성',
    },
    ev_8: {
      id: 'ev_8',
      sourceType: 'counselor_memo',
      sourceLabel: '접수 평가 자료',
      excerpt:
        '진로흥미검사 사회형/탐구형 높음. 상태불안 척도 상위 10% 범주. 임상적 진단 수준은 아님.',
      rationale: '접수 단계에서 실시한 간이 검사 결과 및 해석 근거',
    },
    ev_9: {
      id: 'ev_9',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (38:50)',
      excerpt:
        '내담자: "알려주신 호흡 기법을 해보니까 가슴이 조금 편해졌어요. 이번 주엔 일단 면접 질문 세 개만 먼저 적어볼게요."',
      rationale: '치료 동기, 자동사고 탐색 및 행동 과제 수행 태도',
    },
  },
  missingItems: ['가족 구성 및 가계도 상세 구조 보완 필요'],
  warnings: [
    '작성된 내용은 상담사의 최종 검토용 초안입니다. 실제 제출 전 반드시 수정보완하십시오.',
  ],
}
