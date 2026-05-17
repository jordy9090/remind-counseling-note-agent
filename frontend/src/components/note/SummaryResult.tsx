import type { SessionSummaryDraft } from '../../types/session'
import { Card, CardContent, CardHeader } from '../ui/index'

interface SummaryResultProps {
  data: SessionSummaryDraft
}

export const SummaryResult: React.FC<SummaryResultProps> = ({ data }) => {
  const fields = [
    { label: '회기 주제', value: data.session_theme.text },
    { label: '주호소 / 주요 문제', value: data.presenting_problem.text },
    { label: '상담 내용 요약', value: data.session_content.text },
    { label: '상담자 개입', value: data.counselor_intervention.text },
    { label: '내담자 반응 및 변화', value: data.client_response.text },
    { label: 'Reflection', value: data.reflection.text },
    { label: '추후 개입 계획', value: data.next_plan.text },
  ]

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-bold">회기요약 초안</h2>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {fields.map((field) => (
            <div key={field.label}>
              <p className="text-sm font-semibold text-gray-700">{field.label}</p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-gray-600">{field.value || '정보 없음'}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
