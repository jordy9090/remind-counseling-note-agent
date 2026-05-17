import type { StructuredCaseData } from '../../types/session'
import { Card, CardContent, CardHeader } from '../ui/index'

interface StructuredResultProps {
  data: StructuredCaseData
}

export const StructuredResult: React.FC<StructuredResultProps> = ({ data }) => {
  const fields = [
    { label: '주호소 / 주요 이슈', value: data.presenting_problem },
    { label: '회기 주제', value: data.session_theme },
    { label: '상담 내용', value: data.session_content },
    { label: '상담자 개입', value: data.counselor_interventions },
    { label: '내담자 반응', value: data.client_responses },
    { label: '추후 계획', value: data.next_plan },
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
              <div className="mt-1 space-y-2">
                {field.value.length ? (
                  field.value.map((item, index) => (
                    <p key={`${field.label}-${index}`} className="whitespace-pre-wrap text-sm text-gray-600">
                      {item.content}
                    </p>
                  ))
                ) : (
                  <p className="text-sm text-gray-500">정보 없음</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
