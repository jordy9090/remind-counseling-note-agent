import { SessionSummary } from '../../types/session'
import { Card, CardHeader, CardContent } from '../ui/index'

interface SummaryResultProps {
  data: SessionSummary
}

export const SummaryResult: React.FC<SummaryResultProps> = ({ data }) => {
  const fields = [
    { label: '상담내용', value: data.session_content },
    { label: '상담자소견', value: data.counselor_opinion },
    { label: '회기요약', value: data.session_summary },
    { label: '추후상담계획', value: data.next_counseling_plan },
  ]

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-bold">회기 요약</h2>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {fields.map((field) => (
            <div key={field.label}>
              <p className="text-sm font-semibold text-gray-700">{field.label}</p>
              <p className="mt-1 text-sm text-gray-600 whitespace-pre-wrap">{field.value || '정보 없음'}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
