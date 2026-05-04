import React from 'react'
import type { VerificationReport } from '../../types/session'
import { Card, CardHeader, CardContent } from '../ui/index'

interface VerificationReportProps {
  data: VerificationReport
}

const categoryConfig = {
  grounded: { label: '근거 있는 항목', color: 'bg-green-50 border-green-200' },
  ungrounded: { label: '근거 부족 항목', color: 'bg-amber-50 border-amber-200' },
  sensitive: { label: '민감정보', color: 'bg-red-50 border-red-200' },
  needs_human_judgment: { label: '판단 필요', color: 'bg-blue-50 border-blue-200' },
}

export const VerificationReportComponent = ({ data }: VerificationReportProps) => {
  return (
    <Card>
      <CardHeader>
        <h2 className="text-lg font-bold">검증 리포트</h2>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {(Object.keys(categoryConfig) as Array<keyof VerificationReport>).map((category) => {
            const config = categoryConfig[category]
            const items = data[category] || []

            return (
              <div key={category}>
                <p className="text-sm font-semibold text-gray-700 mb-2">{config.label}</p>
                <div className={`rounded-md border ${config.color} p-3 space-y-2`}>
                  {items.length > 0 ? (
                    items.map((item, idx) => (
                      <div key={idx} className="text-xs text-gray-600">
                        <span className="font-medium">{item.content}</span>
                        <span className="text-gray-500 ml-2">({item.source})</span>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-gray-500 italic">항목 없음</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
