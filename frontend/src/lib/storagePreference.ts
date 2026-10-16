import { supabase } from './supabase'

/**
 * Supabase user_metadata key for the counselor's 원문 저장 setting. Must match
 * ORIGINAL_INPUT_PREFERENCE_KEY in backend/app/api/security.py, which enforces it on every save.
 */
export const ORIGINAL_INPUT_PREFERENCE_KEY = 'remind_store_original_input'

/** Only an explicit false turns 원문 저장 off; the default is to store the session input. */
export async function readStoreOriginalInput(): Promise<boolean> {
  if (!supabase) return true
  const { data, error } = await supabase.auth.getUser()
  if (error) throw error
  return data.user?.user_metadata?.[ORIGINAL_INPUT_PREFERENCE_KEY] !== false
}

export async function writeStoreOriginalInput(value: boolean): Promise<void> {
  if (!supabase) throw new Error('로그인 설정을 확인할 수 없습니다.')
  const { error } = await supabase.auth.updateUser({ data: { [ORIGINAL_INPUT_PREFERENCE_KEY]: value } })
  if (error) throw error
}
