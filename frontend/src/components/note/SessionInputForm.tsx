import { useState } from 'react'
import type { SessionInput } from '../../types/session'
import { Input, Label, Textarea, Button } from '../ui/index'

interface SessionInputFormProps {
  onSubmit: (data: SessionInput) => void
  isLoading?: boolean
}

export const SessionInputForm: React.FC<SessionInputFormProps> = ({ onSubmit, isLoading = false }) => {
  const [formData, setFormData] = useState<SessionInput>({
    case_id: '',
    session_no: 1,
    counselor_memo: '',
    transcript: '',
    prev_summary: '',
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'session_no' ? parseInt(value, 10) : value,
    }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <Label htmlFor="case_id">케이스 ID</Label>
        <Input
          id="case_id"
          name="case_id"
          value={formData.case_id}
          onChange={handleChange}
          placeholder="예: CASE001"
          required
          className="mt-1"
        />
      </div>

      <div>
        <Label htmlFor="session_no">회기번호</Label>
        <Input
          id="session_no"
          name="session_no"
          type="number"
          value={formData.session_no}
          onChange={handleChange}
          min={1}
          required
          className="mt-1"
        />
      </div>

      <div>
        <Label htmlFor="counselor_memo">상담사 메모</Label>
        <Textarea
          id="counselor_memo"
          name="counselor_memo"
          value={formData.counselor_memo}
          onChange={handleChange}
          placeholder="상담사의 메모를 입력하세요..."
          rows={4}
          required
          className="mt-1"
        />
      </div>

      <div>
        <Label htmlFor="transcript">축어록 (상담 전사)</Label>
        <Textarea
          id="transcript"
          name="transcript"
          value={formData.transcript}
          onChange={handleChange}
          placeholder="상담 중 나눈 대화 내용을 입력하세요..."
          rows={6}
          required
          className="mt-1"
        />
      </div>

      <div>
        <Label htmlFor="prev_summary">이전 회기 요약 (선택사항)</Label>
        <Textarea
          id="prev_summary"
          name="prev_summary"
          value={formData.prev_summary}
          onChange={handleChange}
          placeholder="이전 회기의 요약 (없으면 비워두세요)"
          rows={3}
          className="mt-1"
        />
      </div>

      <Button
        type="submit"
        disabled={isLoading}
        className="w-full"
        size="lg"
      >
        {isLoading ? '처리 중...' : '회기 요약 생성'}
      </Button>
    </form>
  )
}
