import { useState } from 'react'
import type { SessionInput } from '../../types/session'
import { Button, Input, Label, Textarea } from '../ui/index'

interface SessionInputFormProps {
  onSubmit: (data: SessionInput) => void
  isLoading?: boolean
}

export const SessionInputForm: React.FC<SessionInputFormProps> = ({ onSubmit, isLoading = false }) => {
  const [formData, setFormData] = useState<SessionInput>({
    case_id: '',
    session_number: 1,
    session_date: new Date().toISOString().slice(0, 10),
    counselor_name: '',
    counselor_memo: '',
    transcript_text: '',
    previous_session_summary: '',
    counseling_goal: '',
    psychological_test_summary: '',
    key_issue_tags: [],
    nonverbal_notes: '',
  })

  const handleChange = (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'session_number' ? Number(value) : value,
    }))
  }

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="case_id">케이스 ID / 가명</Label>
          <Input id="case_id" name="case_id" value={formData.case_id} onChange={handleChange} required />
        </div>
        <div>
          <Label htmlFor="session_number">회기 번호</Label>
          <Input
            id="session_number"
            name="session_number"
            type="number"
            min={1}
            value={formData.session_number}
            onChange={handleChange}
            required
          />
        </div>
      </div>

      <div>
        <Label htmlFor="counselor_memo">상담사 메모</Label>
        <Textarea
          id="counselor_memo"
          name="counselor_memo"
          value={formData.counselor_memo}
          onChange={handleChange}
          rows={4}
          required
        />
      </div>

      <div>
        <Label htmlFor="transcript_text">축어록/STT 텍스트</Label>
        <Textarea
          id="transcript_text"
          name="transcript_text"
          value={formData.transcript_text}
          onChange={handleChange}
          rows={6}
          required
        />
      </div>

      <div>
        <Label htmlFor="previous_session_summary">이전 회기 요약</Label>
        <Textarea
          id="previous_session_summary"
          name="previous_session_summary"
          value={formData.previous_session_summary}
          onChange={handleChange}
          rows={3}
          required
        />
      </div>

      <Button type="submit" disabled={isLoading} className="w-full" size="lg">
        {isLoading ? '처리 중...' : '회기요약 초안 생성'}
      </Button>
    </form>
  )
}
