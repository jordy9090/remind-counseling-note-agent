import type { VerificationReport } from '../../types/session'
import { Card, CardContent, CardHeader } from '../ui/index'

interface VerificationReportProps {
  data: VerificationReport
}

export const VerificationReportComponent = ({ data }: VerificationReportProps) => {
  const groups = [
    {
      label: '입력 근거 있음',
      items: data.grounded_items.map((item) => `${item.claim} (${item.source_refs.join(', ')})`),
    },
    {
      label: '입력 근거 부족 / 추론 가능성',
      items: [...data.weakly_grounded_items, ...data.unsupported_or_risky_claims].map(
        (item) => `${item.claim} - ${item.reason}`,
      ),
    },
    {
      label: '민감정보 후보',
      items: data.sensitive_info_items.map((item) => `${item.text} (${item.recommendation})`),
    },
    {
      label: '상담사 직접 판단 필요',
      items: data.requires_counselor_review.map((item) => `${item.field} - ${item.reason}`),
    },
  ]

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-bold">검증 리포트</h2>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {groups.map((group) => (
            <div key={group.label}>
              <p className="mb-2 text-sm font-semibold text-gray-700">{group.label}</p>
              <div className="space-y-2 rounded-md border border-gray-200 bg-gray-50 p-3">
                {group.items.length ? (
                  group.items.map((item, index) => (
                    <p key={`${group.label}-${index}`} className="text-xs text-gray-600">
                      {item}
                    </p>
                  ))
                ) : (
                  <p className="text-xs text-gray-500">항목 없음</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
