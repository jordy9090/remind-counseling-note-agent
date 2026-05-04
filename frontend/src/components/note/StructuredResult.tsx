import { StructuredCase } from '../../types/session'
import { Card, CardHeader, CardContent } from '../ui/index'

interface StructuredResultProps {
  data: StructuredCase
}

export const StructuredResult: React.FC<StructuredResultProps> = ({ data }) => {
  const fields = [
    { label: '기본정보', value: data.basic_info },
    { label: '주호소/문제', value: data.presenting_problem },
    { label: '상담목표', value: data.goals },
    { label: '상담내용', value: data.session_content },
    { label: '상담자 개입', value: data.counselor_intervention },
    { label: '내담자 반응', value: data.client_response },
    { label: '평가', value: data.assessment },
    { label: '추후계획', value: data.next_plan },
  ]

  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-bold">구조화 결과</h2>
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
