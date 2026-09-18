import { Loader2 } from 'lucide-react'

import { EmptyState } from '../app-shell/ui'
import { DocumentIcon } from '../../pages/HomeDashboardPage'
import { isConfirmedStatus, relativeTime } from '../../lib/caseList'
import type { RecentDocumentItem } from '../../types/session'

/** 문서 보관함 (데이터 축소판): 내 계정의 생성 문서 목록. 클릭하면 저장된 기록을 연다. */
export default function DocumentArchivePage({
  documents,
  loading,
  onOpenDocument,
}: {
  documents: RecentDocumentItem[]
  loading: boolean
  onOpenDocument: (document: RecentDocumentItem) => void
}) {
  return (
    <section aria-label="문서 보관함" className="mx-auto w-full max-w-[1240px] px-4 py-6 md:px-6 md:py-7">
      <h1 className="text-2xl font-extrabold text-grey-900">문서 보관함</h1>
      <p className="mt-1 text-sm text-grey-500">회기 요약과 보고서 기록입니다. 회기 기록을 누르면 저장된 내용을 다시 열 수 있습니다.</p>
      <div className="rm-card mt-5 overflow-x-auto">
        {loading && !documents.length ? (
          <p role="status" className="flex items-center justify-center gap-2 py-12 text-sm text-grey-500"><Loader2 className="h-4 w-4 animate-spin" />불러오는 중입니다…</p>
        ) : documents.length === 0 ? (
          <EmptyState title="아직 생성된 문서가 없어요." description="회기를 기록하고 AI 요약을 생성하면 여기에 쌓입니다." />
        ) : (
          <table className="rm-table w-full min-w-[560px]">
            <thead><tr><th>이름</th><th>문서 제목</th><th>상태</th><th className="text-right">최종 수정</th></tr></thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.document_id} className="cursor-pointer hover:bg-grey-100/60" onClick={() => onOpenDocument(doc)}>
                  <td className="font-semibold text-grey-800">{doc.case_alias || doc.case_id}</td>
                  <td><span className="inline-flex items-center gap-2"><DocumentIcon type={doc.document_type} confirmed={isConfirmedStatus(doc.status)} />{doc.title} - {doc.case_alias || doc.case_id}</span></td>
                  <td className="text-grey-500">{doc.document_type === 'session_note' ? (isConfirmedStatus(doc.status) ? '검토 완료' : 'AI 초안') : '초안'}</td>
                  <td className="whitespace-nowrap text-right text-grey-500">{relativeTime(doc.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
