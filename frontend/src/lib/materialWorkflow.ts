export type MaterialWorkflowKind = 'document' | 'audio'
export type MaterialWorkflowStatus =
  | 'uploading'
  | 'completed'
  | 'warning'
  | 'selected'
  | 'transcribing'
  | 'transcribed'
  | 'failed'
export type MaterialWorkflowApplyTarget =
  | 'transcript_text'
  | 'nonverbal_notes'
  | 'counselor_memo'
  | 'previous_session_summary'
  | 'psychological_test_summary'

export interface MaterialWorkflowSegment {
  text: string
}

export interface MaterialWorkflowItem {
  kind: MaterialWorkflowKind
  status: MaterialWorkflowStatus
  extractedText?: string
  transcriptText?: string
  segments?: MaterialWorkflowSegment[]
  appliedTargets: MaterialWorkflowApplyTarget[]
  dirtySinceApply?: boolean
}

export function getMaterialText(material: MaterialWorkflowItem | null | undefined): string {
  if (!material) return ''
  if (material.kind === 'audio') {
    if (material.transcriptText) return material.transcriptText
    if (material.segments?.length) {
      return material.segments.map((segment) => segment.text).filter(Boolean).join('\n')
    }
    return ''
  }
  return material.extractedText || ''
}

export function isReadyMaterial(material: MaterialWorkflowItem): boolean {
  const hasText = Boolean(getMaterialText(material).trim())
  if (!hasText) return false
  if (material.kind === 'document') {
    return ['completed', 'warning'].includes(material.status)
  }
  return material.status === 'transcribed'
}

export function getUnappliedReadyMaterials<T extends MaterialWorkflowItem>(materials: T[]): T[] {
  return materials.filter(
    (material) => isReadyMaterial(material) && (material.appliedTargets.length === 0 || material.dirtySinceApply),
  )
}
