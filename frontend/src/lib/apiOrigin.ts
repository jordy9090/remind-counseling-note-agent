const HOSTED_API_ORIGIN = 'https://api.remind.ai.kr'

/** Keep production counseling traffic off the frontend host, including on misconfiguration. */
export function resolveApiOrigin(configured: string | undefined, production: boolean): string {
  const value = (configured || '').trim().replace(/\/+$/, '')
  if (!production) return value
  if (!value) return HOSTED_API_ORIGIN
  if (value !== HOSTED_API_ORIGIN) {
    throw new Error('상담자료 처리 서버 주소가 올바르지 않습니다. 운영 담당자에게 문의해주세요.')
  }
  return value
}

export const API_BASE_URL = resolveApiOrigin(import.meta.env.VITE_API_BASE_URL, import.meta.env.PROD)
export const AUDIO_API_BASE_URL = resolveApiOrigin(
  import.meta.env.VITE_AUDIO_API_BASE_URL || API_BASE_URL,
  import.meta.env.PROD,
)
