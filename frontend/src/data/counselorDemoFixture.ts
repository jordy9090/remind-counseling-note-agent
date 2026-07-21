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
}

export interface CounselorDemoFixtureData {
  clientInfo: DemoClientInfo
  sections: DemoDraftSection[]
  evidences: Record<string, DemoEvidenceItem>
  missingItems: string[]
  warnings: string[]
}

export const COUNSELOR_DEMO_FIXTURE: CounselorDemoFixtureData = {
  clientInfo: {
    name: '김민서 (가명)',
    caseId: 'CASE-2026-05',
    sessionNumber: 5,
    sessionDate: '2026.04.28',
    counselorName: '이수진 상담사',
    counselingGoal: '취업 준비 과정의 대인 비교 불안 완화 및 완벽주의적 사고 재구성',
    institution: '마음연결 심리상담센터',
  },
  sections: [
    {
      id: 'presenting_problem',
      title: '주호소 및 회기 주제',
      content:
        '진로 및 취업 준비 과정에서 주변 동기들과의 비교로 인한 강한 불안과 자기비난을 호소함. 5회기에서는 서류 전형 합격 후 면접을 앞두고 급격히 높아진 발표/평가 불안과 무기력감을 집중 다룸.',
      status: 'connected',
      evidenceIds: ['ev_1', 'ev_2'],
    },
    {
      id: 'main_content',
      title: '주요 상담 내용',
      content:
        '동기들의 취업 소식을 들은 뒤 "나만 제자리에 있는 것 같다"는 생각이 반복되며, 밤에 잠들기 어렵고 두통이 동반된다고 보고함. 면접관 앞에서 실수할 것에 대한 두려움으로 인해 대본 작성을 미루는 회피 행동을 보임.',
      status: 'connected',
      evidenceIds: ['ev_3', 'ev_4'],
    },
    {
      id: 'counselor_intervention',
      title: '상담자 개입',
      content:
        "내담자의 취업 불안 속에 가려진 '완벽주의적 자동적 사고'를 명료화하고, 면접 결과와 본인 가치를 분리하는 인지 재구성을 제공함. 이전 회기에서 연습한 4-7-8 복식호흡법과 생각 멈추기 기법을 회기 중 재연습함.",
      status: 'connected',
      evidenceIds: ['ev_5', 'ev_6'],
    },
    {
      id: 'client_response',
      title: '내담자 반응',
      content:
        '현실 검증 질문을 통해 "면접 하나로 내 전체 유능성이 결정되는 것은 아니다"라는 점을 인지적으로 수용함. 호흡 재훈련 후 신체적 긴장도(VAS 8→4) 감소를 경험하고, 이번 주 모의 면접 질문 3개 작성 과제에 동의함.',
      status: 'connected',
      evidenceIds: ['ev_7'],
    },
    {
      id: 'risk_safety',
      title: '위험·안전 확인',
      content:
        '자살 및 자해 위험성은 낮음(경미한 무기력감 및 불면 표현). 단, 최근 2주간 불면으로 약국 판매 수면유도제를 임의 복용했음을 보고하여, 다음 회기 시작 시 수면 양상 및 필요시 정신건강의학과 전문의 상담 안내 여부를 확인해야 함.',
      status: 'needs_review',
      evidenceIds: ['ev_8'],
      missingNotice: '약물 복용 보고 건: 상담사의 직접 확인 및 수면 수칙 안내 필요',
    },
    {
      id: 'next_plan',
      title: '다음 회기 계획',
      content:
        '1) 면접 예상 질문 3가지 인지적 재구성 적용 연습 점검 2) 주 3회 15분 일상 산책 과제 수행 여부 확인 3) 수면 패턴 및 신체 긴장도 재평가',
      status: 'connected',
      evidenceIds: ['ev_9'],
    },
  ],
  evidences: {
    ev_1: {
      id: 'ev_1',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (04:12)',
      excerpt:
        '내담자: "친구들은 벌써 서류 합격해서 면접 보러 다니는데, 저는 서류 하나 내는 것도 너무 덜덜 떨려요. 제가 너무 뒤처진 것 같아서 밤마다 잠이 안 와요."',
      rationale: '취업 준비 중 동기 비교 및 제출/평가 불안에 대한 내담자의 직접 표현',
    },
    ev_2: {
      id: 'ev_2',
      sourceType: 'counselor_memo',
      sourceLabel: '상담사 사전 관찰 메모',
      excerpt:
        '서류 합격 통보 직후 면접에 대한 부담으로 불안 지수(VAS 8/10) 급상승. 자기비난적 사고 자극됨.',
      rationale: '상담 시작 시 상담사가 직접 기록한 관찰 및 세션 전 상태',
    },
    ev_3: {
      id: 'ev_3',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (12:35)',
      excerpt:
        '내담자: "면접관이 질문했을 때 머리가 하얗게 될 것 같아요. 말 막히면 끝장이라는 생각만 들고... 그래서 면접 연습 대본 작성을 자꾸 미루고 있어요."',
      rationale: '평가 두려움 및 준비 회피 행동에 대한 내담자 진술',
    },
    ev_4: {
      id: 'ev_4',
      sourceType: 'previous_summary',
      sourceLabel: '4회기 요약록',
      excerpt:
        '4회기 사례 개념화: 과도한 타인 인식 및 유능성에 대한 완벽주의적 기준이 주요 불안 유발 인자로 파악됨.',
      rationale: '이전 회기 사례 개념화 데이터와 연결된 맥락',
    },
    ev_5: {
      id: 'ev_5',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (24:18)',
      excerpt:
        '상담자: "민서 씨, 면접에서 대답을 잠시 머뭇거린다고 해서 면접관이 민서 씨의 인격 전체를 부정적으로 볼까요? 우리가 지난번에 연습했던 생각 멈추기 기법을 지금 같이 해볼까요?"',
      rationale: '인지 재구성 질의 및 신체 이완 기법 적용 개입 원문',
    },
    ev_6: {
      id: 'ev_6',
      sourceType: 'counselor_memo',
      sourceLabel: '상담 과정 메모',
      excerpt:
        '4-7-8 호흡법 안내 후 신체 긴장도 VAS 8에서 4로 저하 확인. 인지적 재구성 질문 반응 양호.',
      rationale: '상담사의 개입 및 신체 반응 변화 관찰 기록',
    },
    ev_7: {
      id: 'ev_7',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (38:50)',
      excerpt:
        '내담자: "생각해보니 꼭 한 번에 다 완벽히 해야 하는 건 아니네요. 숨 깊게 쉬니까 답답한 것도 좀 나아졌어요. 이번 주에 면접 질문 3개만 먼저 작성해볼게요."',
      rationale: '인지적 수용 및 행동 과제 합의 발언',
    },
    ev_8: {
      id: 'ev_8',
      sourceType: 'transcript',
      sourceLabel: '5회기 축어록 (45:10)',
      excerpt:
        '내담자: "요즘 잠을 너무 못 자서 약국에서 처방전 없이 살 수 있는 수면유도제를 두 번 먹었는데... 괜찮겠죠?"',
      rationale: '일시적 수면유도제 임의 복용 발언',
      warning:
        '상담사 검토 필요: 의료적 조언은 삼가고, 수면 위생 교육 및 필요시 전문의 상담 권유 여부를 확인해야 합니다.',
    },
    ev_9: {
      id: 'ev_9',
      sourceType: 'previous_summary',
      sourceLabel: '4회기 과제 평가',
      excerpt: '일상 산책 및 신체 반응 기재 과제를 다음 회기 연속 과제로 유지하기로 함.',
      rationale: '이전 회기 과제 및 지속 계획 연계',
    },
  },
  missingItems: ['수면유도제 복용 관련 수면 위생 및 안전 가이드 확인'],
  warnings: [
    'AI 초안은 상담사의 임상적 검토 전 최종 회기 기록으로 사용하지 마십시오.',
    '약물 관련 발언은 의료적 처방이 아닌 상담 내 관찰로 기록되었습니다.',
  ],
}
