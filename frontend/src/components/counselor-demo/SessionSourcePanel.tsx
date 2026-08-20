import React, { useState } from 'react'
import { FileText, History, MessageSquare } from 'lucide-react'
import type { CounselorDemoFixtureData } from '../../data/counselorDemoFixture'

interface SessionSourcePanelProps {
  demoData: CounselorDemoFixtureData
}

type SourceTab = 'transcript' | 'memo' | 'previous'

export const SessionSourcePanel: React.FC<SessionSourcePanelProps> = ({ demoData }) => {
  const [activeTab, setActiveTab] = useState<SourceTab>('transcript')
  const [selectedHistorySession, setSelectedHistorySession] = useState(4)
  const selectedHistory = demoData.sessionSources.history.find(
    (session) => session.sessionNumber === selectedHistorySession,
  )

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs">
      <div className="flex gap-2 border-b border-slate-200 bg-slate-50 px-4 pt-3">
        <SourceTabButton
          active={activeTab === 'transcript'}
          onClick={() => setActiveTab('transcript')}
          icon={<MessageSquare className="h-3.5 w-3.5" />}
          label="5회기 축어록"
          activeClassName="text-blue-700"
        />
        <SourceTabButton
          active={activeTab === 'memo'}
          onClick={() => setActiveTab('memo')}
          icon={<FileText className="h-3.5 w-3.5" />}
          label="5회기 상담자 메모"
          activeClassName="text-emerald-700"
        />
        <SourceTabButton
          active={activeTab === 'previous'}
          onClick={() => setActiveTab('previous')}
          icon={<History className="h-3.5 w-3.5" />}
          label="이전 1~4회기"
          activeClassName="text-purple-700"
        />
      </div>

      <div className="max-h-[650px] overflow-y-auto bg-slate-50/30 p-5 text-sm leading-relaxed text-slate-800">
        {activeTab === 'transcript' ? (
          <div className="space-y-3">
            <div className="rounded border border-blue-100 bg-blue-50/50 p-3 text-xs font-semibold text-blue-900">
              5회기 상담 원문 · {demoData.clientInfo.sessionDate}
            </div>
            <pre className="whitespace-pre-wrap font-sans text-xs leading-6 text-slate-700">
              {formatTranscript(demoData.sessionSources.transcript)}
            </pre>
          </div>
        ) : null}

        {activeTab === 'memo' ? (
          <div className="space-y-3">
            <div className="rounded border border-emerald-100 bg-emerald-50/50 p-3 text-xs font-semibold text-emerald-900">
              5회기 상담자 입력 메모
            </div>
            <p className="whitespace-pre-wrap text-xs leading-6 text-slate-800">
              {demoData.sessionSources.counselorMemo}
            </p>
          </div>
        ) : null}

        {activeTab === 'previous' ? (
          <div className="space-y-4">
            <div className="rounded border border-purple-100 bg-purple-50/50 p-3 text-xs font-semibold text-purple-900">
              CASE-MUSPSY-1416 이전 상담 기록
            </div>
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="이전 회기 선택">
              {demoData.sessionSources.history.map((session) => (
                <button
                  key={session.sessionNumber}
                  type="button"
                  role="tab"
                  aria-selected={selectedHistorySession === session.sessionNumber}
                  onClick={() => setSelectedHistorySession(session.sessionNumber)}
                  className={`rounded-lg border px-3 py-1.5 text-xs font-bold transition-colors ${
                    selectedHistorySession === session.sessionNumber
                      ? 'border-purple-300 bg-purple-100 text-purple-800'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-purple-200 hover:text-purple-700'
                  }`}
                >
                  {session.sessionNumber}회기
                </button>
              ))}
            </div>

            {selectedHistory ? (
              <div role="tabpanel" className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
                <div>
                  <h3 className="text-sm font-bold text-slate-900">{selectedHistory.sessionNumber}회기 요약</h3>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-slate-700">
                    {selectedHistory.summary}
                  </p>
                </div>
                <details className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <summary className="cursor-pointer text-xs font-bold text-slate-700">
                    MusPsy 원문 보기
                  </summary>
                  <pre className="mt-3 whitespace-pre-wrap font-sans text-[11px] leading-5 text-slate-600">
                    {selectedHistory.rawSource}
                  </pre>
                </details>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

interface SourceTabButtonProps {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  activeClassName: string
}

const SourceTabButton: React.FC<SourceTabButtonProps> = ({
  active,
  onClick,
  icon,
  label,
  activeClassName,
}) => (
  <button
    type="button"
    aria-pressed={active}
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 rounded-t-lg border-x border-t px-3 py-2 text-xs font-bold transition-colors ${
      active
        ? `border-slate-200 border-b-transparent bg-white shadow-2xs ${activeClassName}`
        : 'border-transparent text-slate-500 hover:bg-slate-100 hover:text-slate-800'
    }`}
  >
    {icon}
    {label}
  </button>
)

function formatTranscript(transcript: string): string {
  return transcript.replace(/^Cl:/gm, '내담자:').replace(/^C:/gm, '상담자:')
}
