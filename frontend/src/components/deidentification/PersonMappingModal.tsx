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
  unresolvedNameMentions,
  type PersonMapping,
  type PersonMention,
  type PersonMentionKind,
  type StoredPerson,
} from '../../lib/personMapping'

export interface PersonMappingSource {
  key: string
  label: string
  /** Text after the de-identification review. */
  text: string
}

const NEW_PERSON = '__new__'

const KIND_BADGE: Record<PersonMentionKind, { label: string; className: string }> = {
  label: { label: '비식별 라벨', className: 'bg-primary-50 text-primary-400' },
  name: { label: '남은 이름 · 연결하면 가려짐', className: 'bg-danger-50 text-danger-500' },
  relation: { label: '관계 표현', className: 'bg-grey-100 text-grey-600' },
  manual: { label: '직접 추가', className: 'bg-grey-100 text-grey-600' },
}

/** True when the reviewed text mentions anyone the counselor could match. */
export function hasPersonMentions(texts: string[], stored: StoredPerson[] = []): boolean {
  return detectPersonMapping(texts, stored).mentions.length > 0
}

/**
 * "등장 인물을 정리해주세요": after the de-identification review and before summary generation,
 * the counselor links names, misheard names, nicknames and relation words to one person each,
 * so the AI does not split one person into several.
 */
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
  const unresolved = unresolvedNameMentions(mapping)
  const linkedCount = mapping.mentions.filter((mention) => mention.personId).length

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

  const submit = (useMapping: boolean) => {
    onConfirm(
      Object.fromEntries(sources.map((source) => [source.key, useMapping ? applyPersonMapping(source.text, mapping) : source.text])),
      useMapping ? mapping : { persons: mapping.persons, mentions: [] },
    )
  }

  const previewSource = sources.find((source) => source.text.trim()) ?? sources[0]

  return (
    <ModalShell
      ariaLabel="등장 인물 정리"
      title="등장 인물을 정리해주세요"
      description="같은 사람을 가리키는 이름·잘못 받아 적힌 이름·별명·관계 표현을 한 인물로 묶어주세요. AI가 같은 사람으로 이해하고 요약해요."
      onClose={onBack}
      width={1080}
      footer={(
        <div className="flex w-full flex-col gap-3 sm:flex-row">
          <OutlineButton className="h-[52px] rounded-[12px] text-[15px] sm:w-[160px]" onClick={onBack}>
            <ArrowLeft className="h-5 w-5" />뒤로가기
          </OutlineButton>
          <OutlineButton className="h-[52px] rounded-[12px] text-[15px] sm:w-[200px]" onClick={() => submit(false)}>
            정리 없이 다음으로
          </OutlineButton>
          <PrimaryButton className="h-[52px] flex-1 rounded-[12px] text-[15px]" onClick={() => submit(true)}>
            <Sparkles className="h-5 w-5" />정리한 내용 확인하기
          </PrimaryButton>
        </div>
      )}
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex h-9 items-center rounded-[10px] bg-primary-50 px-3 text-sm font-bold text-primary-400">
            찾은 표현 {mapping.mentions.length}개 · 연결 {linkedCount}개
          </span>
          {unresolved.length > 0 && (
            <span role="status" className="inline-flex h-9 items-center rounded-[10px] bg-danger-50 px-3 text-sm font-bold text-danger-500">
              연결하지 않은 이름 {unresolved.length}개는 그대로 AI에 전달돼요
            </span>
          )}
          <p className="text-xs text-grey-500">
            {savesToClient
              ? '요약을 만들면 이 정리가 내담자의 인물 사전에 저장되어, 다음 회기에도 같은 라벨로 쓰여요.'
              : '이 정리는 이 브라우저에서만 이루어지고 저장되지 않아요.'}
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <section aria-label="인물 사전" className="flex min-h-0 flex-col rounded-card border border-grey-200 lg:h-[min(520px,54vh)]">
            <div className="flex h-[62px] shrink-0 items-center justify-between gap-3 border-b border-grey-200 px-6">
              <h3 className="text-base font-bold text-grey-900">인물 사전</h3>
              <button
                type="button"
                onClick={addPerson}
                className="inline-flex h-10 items-center gap-1.5 rounded-full border border-primary-400 px-4 text-sm font-bold text-primary-400 hover:bg-primary-50"
              >
                <UserPlus className="h-4 w-4" />새 인물
              </button>
            </div>
            <ul className="rm-scroll min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-5">
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
          </section>

          <section aria-label="등장 표현" className="flex min-h-0 flex-col rounded-card border border-grey-200 lg:h-[min(520px,54vh)]">
            <div className="flex h-[62px] shrink-0 items-center border-b border-grey-200 px-6">
              <h3 className="text-base font-bold text-grey-900">등장 표현</h3>
            </div>
            <ul className="rm-scroll min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-5">
              {mapping.mentions.length === 0 && (
                <li className="rounded-[12px] border border-dashed border-grey-200 px-4 py-8 text-center text-sm leading-6 text-grey-500">
                  자동으로 찾은 인물 표현이 없어요.<br />아래에서 별명이나 잘못 받아 적힌 이름을 직접 추가할 수 있어요.
                </li>
              )}
              {mapping.mentions.map((mention) => (
                <MentionRow key={mention.id} mention={mention} mapping={mapping} onLink={link} onRemove={removeMention} />
              ))}
            </ul>
            <form onSubmit={addMention} className="shrink-0 border-t border-grey-200 px-6 pb-5 pt-4">
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
        </div>

        {previewSource && (
          <div className="rounded-card border border-grey-200">
            <button type="button" onClick={() => setPreview((value) => !value)} aria-expanded={preview} className="flex h-12 w-full items-center px-6 text-sm font-bold text-grey-700">
              {preview ? '▾' : '▸'} AI 전달용 미리보기 ({previewSource.label})
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
