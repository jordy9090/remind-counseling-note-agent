import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || ''
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || ''

export const isAuthConfigured = Boolean(supabaseUrl && supabasePublishableKey)

export const supabase = isAuthConfigured
  ? createClient(supabaseUrl, supabasePublishableKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null

export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return null
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token || null
}

export type AvailableOAuthProviders = {
  google: boolean
  kakao: boolean
}

export async function getAvailableOAuthProviders(): Promise<AvailableOAuthProviders> {
  if (!isAuthConfigured) return { google: false, kakao: false }

  try {
    const response = await fetch(`${supabaseUrl.replace(/\/$/, '')}/auth/v1/settings`, {
      headers: { apikey: supabasePublishableKey },
    })
    if (!response.ok) return { google: false, kakao: false }
    const settings = await response.json() as { external?: Record<string, boolean> }
    return {
      google: settings.external?.google === true,
      kakao: settings.external?.kakao === true,
    }
  } catch {
    return { google: false, kakao: false }
  }
}
