import { useMemo, useState, type FormEvent } from 'react'
import { ArrowLeft, Plus, Sparkles, UserPlus, X } from 'lucide-react'

import ModalShell from '../app-shell/ModalShell'
import { OutlineButton, PrimaryButton } from '../app-shell/ui'
import {
  applyPersonMapping,
  createPerson,
  detectPersonMapping,
  manualMention,
  personDictionary,
  type PersonMapping,
  type PersonMention,
  type PersonMentionKind,
  type StoredPerson,
} from '../../lib/personMapping'

export interface PersonMappingSource {
  key: string
  label: string
  /** Input text before the mandatory privacy review. */
  text: string
}

const NEW_PERSON = '__new__'

const KIND_BADGE: Record<PersonMentionKind, { label: string; className: string }> = {
  label: { label: '가명', className: 'bg-primary-50 text-primary-400' },
  name: { label: '이름', className: 'bg-grey-100 text-grey-600' },
  relation: { label: '관계 표현', className: 'bg-grey-100 text-grey-600' },
  manual: { label: '직접 추가', className: 'bg-grey-100 text-grey-600' },
}

/** Optional name and alias matching before the mandatory privacy review. */
export default function PersonMappingModal({
  sources,
  stored = [],
  savesToClient = false,
  onBack,
  onConfirm,
}: {
  sources: PersonMappingSource[]
  /** The client's saved 인물 사전; its people and relation links are preselected. */
  stored?: StoredPerson[]
  /** The page saves the result as the client's 인물 사전. */
  savesToClient?: boolean
  onBack: () => void
  /** Texts per source key as the AI receives them, and the matching for the 인물 사전. */
  onConfirm: (texts: Record<string, string>, mapping: PersonMapping) => void
}) {
  const texts = useMemo(() => sources.map((source) => source.text), [sources])
  const [mapping, setMapping] = useState<PersonMapping>(() => detectPersonMapping(texts, stored))
  const [draftText, setDraftText] = useState('')
  const [draftHides, setDraftHides] = useState(true)
  const [formError, setFormError] = useState<string | null>(null)
  const [preview, setPreview] = useState(false)

  const dictionary = personDictionary(mapping)

  const link = (mentionId: string, value: string) => {
    setMapping((current) => {
      let persons = current.persons
      let personId: string | null = value || null
      if (value === NEW_PERSON) {
        const person = createPerson(persons)
        persons = [...persons, person]
        personId = person.id
      }
      return { persons, mentions: current.mentions.map((mention) => (mention.id === mentionId ? { ...mention, personId } : mention)) }
    })
  }

  const addPerson = () => setMapping((current) => ({ ...current, persons: [...current.persons, createPerson(current.persons)] }))

  const removePerson = (personId: string) => setMapping((current) => ({
    persons: current.persons.filter((person) => person.id !== personId),
    mentions: current.mentions.map((mention) => (mention.personId === personId ? { ...mention, personId: null } : mention)),
  }))

  const addMention = (event: FormEvent) => {
    event.preventDefault()
    const result = manualMention(texts, mapping, draftText, draftHides ? 'replace' : 'annotate')
    if ('error' in result) return setFormError(result.error)
    setMapping((current) => ({ ...current, mentions: [...current.mentions, result.mention] }))
    setDraftText('')
    setFormError(null)
  }

  const removeMention = (mentionId: string) => setMapping((current) => ({ ...current, mentions: current.mentions.filter((mention) => mention.id !== mentionId) }))

  const submit = () => {
    onConfirm(
      Object.fromEntries(sources.map((source) => [source.key, applyPersonMapping(source.text, mapping)])),
      mapping,
    )
  }

  const previewSource = sources.find((source) => source.text.trim()) ?? sources[0]

  return (
    <ModalShell
      ariaLabel="이름 사전"
      title="이름 사전"
      description={savesToClient ? '같은 사람의 이름과 별명을 연결하세요. 요약 후 내담자의 이름 사전에 저장됩니다.' : '같은 사람의 이름과 별명을 연결하세요. 이번 요약에만 적용됩니다.'}
      onClose={onBack}
      width={660}
      footer={(
        <div className="flex w-full flex-col gap-3 sm:flex-row">
          <OutlineButton className="h-[52px] rounded-[12px] text-[15px] sm:w-[160px]" onClick={onBack}>
            <ArrowLeft className="h-5 w-5" />뒤로가기
          </OutlineButton>
          <PrimaryButton className="h-[52px] flex-1 rounded-[12px] text-[15px]" onClick={submit}>
            <Sparkles className="h-5 w-5" />적용하고 개인정보 확인
          </PrimaryButton>
        </div>
      )}
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3">

          <section aria-label="등장 표현">
            <ul className="rm-scroll max-h-[32vh] space-y-2 overflow-y-auto">
              {mapping.mentions.length === 0 && (
                <li className="rounded-[12px] border border-dashed border-grey-200 px-4 py-8 text-center text-sm leading-6 text-grey-500">
                  자동으로 찾은 인물 표현이 없어요.<br />아래에서 별명이나 잘못 받아 적힌 이름을 직접 추가할 수 있어요.
                </li>
              )}
              {mapping.mentions.map((mention) => (
                <MentionRow key={mention.id} mention={mention} mapping={mapping} onLink={link} onRemove={removeMention} />
              ))}
            </ul>
            <form onSubmit={addMention} className="pt-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <input
                  aria-label="추가할 표현"
                  className="h-10 min-w-0 flex-1 rounded-[10px] border border-grey-200 bg-white px-3 text-sm text-grey-900 outline-none placeholder:text-grey-400 focus:border-primary-400"
                  placeholder="예: 서연, 그 애, 짝꿍"
                  value={draftText}
                  onChange={(event) => { setDraftText(event.target.value); setFormError(null) }}
                />
                <label className="flex shrink-0 items-center gap-2 text-xs text-grey-600" title="이름이면 켜두세요. 끄면 표현은 그대로 두고 인물 라벨만 붙여요.">
                  <input type="checkbox" className="h-4 w-4 accent-primary-400" checked={draftHides} onChange={(event) => setDraftHides(event.target.checked)} />
                  이름이라 가리기
                </label>
                <button type="submit" className="inline-flex h-10 shrink-0 items-center justify-center gap-1 rounded-full bg-primary-400 px-4 text-sm font-bold text-white hover:bg-primary-500">
                  <Plus className="h-4 w-4" />표현 추가
                </button>
              </div>
              {formError && <p role="alert" className="mt-2 text-xs text-danger-500">{formError}</p>}
            </form>
          </section>
          <details className="rounded-xl border border-grey-200 px-4 py-2">
            <summary className="cursor-pointer text-sm font-semibold text-grey-700">인물 목록</summary>
            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={addPerson}
                className="inline-flex h-10 items-center gap-1.5 rounded-full border border-primary-400 px-4 text-sm font-bold text-primary-400 hover:bg-primary-50"
              >
                <UserPlus className="h-4 w-4" />새 인물
              </button>
            </div>
            <ul className="rm-scroll max-h-48 space-y-2 overflow-y-auto py-2">
              {mapping.persons.map((person) => {
                const expressions = dictionary.find((entry) => entry.person.id === person.id)?.expressions ?? []
                return (
                  <li key={person.id} className="rounded-[12px] border border-grey-200 px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-bold text-grey-900">[{person.label}]</span>
                      {!person.fixed && (
                        <button type="button" onClick={() => removePerson(person.id)} aria-label={`${person.label} 삭제`} className="text-grey-400 hover:text-grey-900">
                          <X className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                    <p className="mt-2 flex flex-wrap gap-1.5 text-xs">
                      {expressions.length === 0 && <span className="text-grey-400">연결된 표현 없음</span>}
                      {expressions.map((expression) => (
                        <span key={expression} className="rounded-full bg-primary-50 px-2.5 py-1 font-semibold text-primary-400">{expression}</span>
                      ))}
                    </p>
                  </li>
                )
              })}
            </ul>
          </details>
        </div>

        {previewSource && (
          <div className="rounded-card border border-grey-200">
            <button type="button" onClick={() => setPreview((value) => !value)} aria-expanded={preview} className="flex h-12 w-full items-center px-6 text-sm font-bold text-grey-700">
              {preview ? '▾' : '▸'} 이름 적용 미리보기
            </button>
            {preview && (
              <div className="rm-scroll mx-6 mb-5 max-h-[220px] overflow-y-auto whitespace-pre-wrap break-words rounded-[10px] border border-grey-200 bg-[#F8FAFC] px-3.5 py-3 text-sm leading-7 text-grey-800">
                {applyPersonMapping(previewSource.text, mapping)}
              </div>
            )}
          </div>
        )}
      </div>
    </ModalShell>
  )
}

function MentionRow({
  mention,
  mapping,
  onLink,
  onRemove,
}: {
  mention: PersonMention
  mapping: PersonMapping
  onLink: (mentionId: string, value: string) => void
  onRemove: (mentionId: string) => void
}) {
  const badge = mention.kind === 'manual'
    ? { label: mention.mode === 'replace' ? '직접 추가 · 가려짐' : '직접 추가', className: KIND_BADGE.manual.className }
    : KIND_BADGE[mention.kind]
  return (
    <li className="rounded-[12px] bg-grey-100 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold text-grey-900">{mention.text}</span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${badge.className}`}>{badge.label}</span>
        <span className="text-xs text-grey-500">{mention.count}회</span>
        <div className="ml-auto flex items-center gap-2">
          <select
            aria-label={`${mention.text} 연결할 인물`}
            value={mention.personId ?? ''}
            onChange={(event) => onLink(mention.id, event.target.value)}
            className={`h-9 rounded-[10px] border bg-white px-2 text-sm ${mention.personId ? 'border-primary-400 font-bold text-primary-400' : 'border-grey-200 text-grey-600'}`}
          >
            <option value="">연결 안 함</option>
            {mapping.persons.map((person) => <option key={person.id} value={person.id}>{person.label}</option>)}
            <option value={NEW_PERSON}>+ 새 인물로</option>
          </select>
          {mention.kind === 'manual' && (
            <button type="button" onClick={() => onRemove(mention.id)} aria-label={`${mention.text} 표현 삭제`} className="text-grey-400 hover:text-grey-900">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
      {mention.context && <p className="mt-1.5 truncate text-xs text-grey-500" title={mention.context}>{mention.context}</p>}
    </li>
  )
}
