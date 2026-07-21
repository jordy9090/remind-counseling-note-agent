import React, { useState } from 'react'
import { FileText, MessageSquare, History } from 'lucide-react'
import type { CounselorDemoFixtureData } from '../../data/counselorDemoFixture'

interface SessionSourcePanelProps {
  demoData: CounselorDemoFixtureData
}

export const SessionSourcePanel: React.FC<SessionSourcePanelProps> = ({ demoData }) => {
  const [activeTab, setActiveTab] = useState<'transcript' | 'memo' | 'previous'>('transcript')

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden space-y-0">
      {/* Tabs */}
      <div className="flex border-b border-slate-200 bg-slate-50 px-4 pt-3 gap-2">
        <button
          type="button"
          onClick={() => setActiveTab('transcript')}
          className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold rounded-t-lg border-t border-x transition-colors ${
            activeTab === 'transcript'
              ? 'bg-white border-slate-200 text-blue-700 border-b-transparent shadow-2xs'
              : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100'
          }`}
        >
          <MessageSquare className="w-3.5 h-3.5" />5회기 STT 축어록
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('memo')}
          className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold rounded-t-lg border-t border-x transition-colors ${
            activeTab === 'memo'
              ? 'bg-white border-slate-200 text-emerald-700 border-b-transparent shadow-2xs'
              : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100'
          }`}
        >
          <FileText className="w-3.5 h-3.5" />
          상담사 관찰 메모
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('previous')}
          className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold rounded-t-lg border-t border-x transition-colors ${
            activeTab === 'previous'
              ? 'bg-white border-slate-200 text-purple-700 border-b-transparent shadow-2xs'
              : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100'
          }`}
        >
          <History className="w-3.5 h-3.5" />
          이전 회기(4회기) 요약
        </button>
      </div>

      {/* Tab Content */}
      <div className="p-5 max-h-[600px] overflow-y-auto font-sans text-sm text-slate-800 leading-relaxed whitespace-pre-line bg-slate-50/30">
        {activeTab === 'transcript' && (
          <div className="space-y-3">
            <div className="p-3 bg-blue-50/50 rounded border border-blue-100 text-xs text-blue-900 font-semibold">
              🎙️ 5회기 음성 녹음 자동 변환 축어록 (2026.04.28 14:00~14:50)
            </div>
            <p className="font-mono text-xs text-slate-700 space-y-2">
              <span className="font-bold text-blue-700">04:12 내담자:</span> "친구들은 벌써 서류
              합격해서 면접 보러 다니는데, 저는 서류 하나 내는 것도 너무 덜덜 떨려요. 제가 너무
              뒤처진 것 같아서 밤마다 잠이 안 와요."
              <br />
              <br />
              <span className="font-bold text-slate-600">04:35 상담자:</span> "동기들과의 비교가
              민서 씨를 많이 압박하고 잠들지 못할 만큼 불안하게 만들고 있군요."
              <br />
              <br />
              <span className="font-bold text-blue-700">12:35 내담자:</span> "면접관이 질문했을 때
              머리가 하얗게 될 것 같아요. 말 막히면 끝장이라는 생각만 들고... 그래서 면접 연습 대본
              작성을 자꾸 미루고 있어요."
              <br />
              <br />
              <span className="font-bold text-slate-600">24:18 상담자:</span> "민서 씨, 면접에서
              대답을 잠시 머뭇거린다고 해서 면접관이 민서 씨의 인격 전체를 부정적으로 볼까요? 우리가
              지난번에 연습했던 생각 멈추기 기법을 지금 같이 해볼까요?"
              <br />
              <br />
              <span className="font-bold text-blue-700">38:50 내담자:</span> "생각해보니 꼭 한 번에
              다 완벽히 해야 하는 건 아니네요. 숨 깊게 쉬니까 답답한 것도 좀 나아졌어요. 이번 주에
              면접 질문 3개만 먼저 작성해볼게요."
              <br />
              <br />
              <span className="font-bold text-blue-700">45:10 내담자:</span> "요즘 잠을 너무 못 자서
              약국에서 처방전 없이 살 수 있는 수면유도제를 두 번 먹었는데... 괜찮겠죠?"
            </p>
          </div>
        )}

        {activeTab === 'memo' && (
          <div className="space-y-3">
            <div className="p-3 bg-emerald-50/50 rounded border border-emerald-100 text-xs text-emerald-900 font-semibold">
              📝 상담사 수기 메모 (세션 전후 기록)
            </div>
            <div className="text-xs space-y-2 text-slate-800">
              <p>
                - 서류 합격 통보 직후 면접에 대한 부담으로 불안 지수(VAS 8/10) 급상승. 자기비난적
                사고 자극됨.
              </p>
              <p>
                - 회기 중 4-7-8 복식호흡법 및 생각 멈추기 기법 재연습. 시행 후 신체 긴장도 VAS
                8→4로 저하 확인.
              </p>
              <p>- 인지적 재구성 질문에 대한 수용도 양호함.</p>
              <p>- 수면유도제 임의 복용 발언 관련: 수면 위생 가이드 및 재발 방지 확인 필요.</p>
            </div>
          </div>
        )}

        {activeTab === 'previous' && (
          <div className="space-y-3">
            <div className="p-3 bg-purple-50/50 rounded border border-purple-100 text-xs text-purple-900 font-semibold">
              📂 4회기 상담일지 요약 (2026.04.21)
            </div>
            <div className="text-xs space-y-2 text-slate-800">
              <p>
                - 주호소: 진로 결정 장애 및 타인과의 비현실적 비교로 인한 자기유능성 저평가.
              </p>
              <p>
                - 개입: 인지치료적 사례 개념화 적용. 완벽주의 신념 명료화.
              </p>
              <p>- 과제: 15분 일상 산책 및 불안 일지 작성.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
