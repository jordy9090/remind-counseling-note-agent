import { supabase } from './supabase'

export const LIVE_AUDIO_RETENTION_MS = 24 * 60 * 60 * 1000
export interface LiveAudioScope { userId: string; caseId: string; sessionNumber: number }
export type LiveAudioKey = [string, string, number, string]
export interface StoredLiveAudio {
  key: LiveAudioKey
  filename: string
  expiresAt: number
  frames: number
  count: number
}
export interface StoredLiveChunk { key: [...LiveAudioKey, number]; recording: LiveAudioKey; index: number; pcm: Blob }

const DB_NAME = 'remind-live-audio'
const files = new WeakMap<File, LiveAudioKey>()
const listeners = new Set<() => void>()
let database: Promise<IDBDatabase> | undefined
let owner: string | null = null
let generation = 0
let expiryTimer: ReturnType<typeof setTimeout> | undefined
const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(DB_NAME)

function changed(broadcast = true): void {
  listeners.forEach(listener => listener())
  if (broadcast) channel?.postMessage('changed')
}
if (channel) channel.onmessage = () => changed(false)

export function subscribeLiveAudioStore(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function open(): Promise<IDBDatabase> {
  if (!database) database = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('recordings', { keyPath: 'key' })
      const chunks = request.result.createObjectStore('chunks', { keyPath: 'key' })
      chunks.createIndex('recording', 'recording')
    }
    request.onsuccess = () => {
      const db = request.result
      db.onversionchange = () => { db.close(); database = undefined }
      resolve(db)
    }
    request.onerror = () => { database = undefined; reject(request.error) }
    request.onblocked = () => { database = undefined; reject(new Error('녹음 저장소를 열지 못했습니다.')) }
  }).catch(error => { database = undefined; throw error })
  return database
}

function done(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onabort = () => reject(transaction.error || new Error('녹음 저장 작업이 취소되었습니다.'))
    transaction.onerror = () => reject(transaction.error)
  })
}

function remove(transaction: IDBTransaction, key: LiveAudioKey): void {
  transaction.objectStore('recordings').delete(key)
  const request = transaction.objectStore('chunks').index('recording').openCursor(IDBKeyRange.only(key))
  request.onsuccess = () => {
    const cursor = request.result
    if (cursor) { cursor.delete(); cursor.continue() }
  }
}

/** Remove expired data before reads, and foreign data after an account transition. */
async function sweep(removeForeign = false): Promise<void> {
  const retainedOwner = owner
  const db = await open()
  const transaction = db.transaction(['recordings', 'chunks'], 'readwrite')
  const completion = done(transaction)
  const request = transaction.objectStore('recordings').openCursor()
  let nextExpiry = Infinity
  let removed = false
  request.onsuccess = () => {
    const cursor = request.result
    if (!cursor) return
    const record = cursor.value as StoredLiveAudio
    if (record.expiresAt <= Date.now() || (removeForeign && record.key[0] !== retainedOwner)) {
      remove(transaction, record.key)
      removed = true
    } else nextExpiry = Math.min(nextExpiry, record.expiresAt)
    cursor.continue()
  }
  await completion
  clearTimeout(expiryTimer)
  if (Number.isFinite(nextExpiry)) expiryTimer = setTimeout(() => { void sweep().catch(() => {}) }, Math.max(0, nextExpiry - Date.now()))
  if (removed) changed()
}

// Keep this subscription for the app lifetime: logout may happen outside the recorder page.
supabase?.auth.onAuthStateChange((event, session) => {
  const nextOwner = session?.user?.is_anonymous ? null : session?.user.id || null
  if (nextOwner !== owner || event === 'SIGNED_OUT' || event === 'INITIAL_SESSION') {
    owner = nextOwner
    generation++
    void sweep(true).catch(() => {})
    changed(false)
  }
})
if (typeof window !== 'undefined') {
  window.addEventListener('focus', () => { void sweep().catch(() => {}) })
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void sweep().catch(() => {})
  })
}

function assertOwner(key: LiveAudioKey, expectedGeneration = generation): void {
  if (!owner || key[0] !== owner || expectedGeneration !== generation) throw new Error('녹음 계정이 변경되었습니다.')
}

export async function createLiveAudio(scope: LiveAudioScope, filename: string): Promise<StoredLiveAudio> {
  const record: StoredLiveAudio = {
    key: [scope.userId, scope.caseId, scope.sessionNumber, crypto.randomUUID()], filename,
    expiresAt: Date.now() + LIVE_AUDIO_RETENTION_MS, frames: 0, count: 0,
  }
  const started = generation
  assertOwner(record.key, started)
  await sweep()
  const db = await open()
  assertOwner(record.key, started)
  const transaction = db.transaction('recordings', 'readwrite')
  const completion = done(transaction)
  transaction.objectStore('recordings').add(record)
  await completion
  void sweep().catch(() => {})
  return record
}

/** One transaction commits PCM and its ordered manifest; no text or ASR result is persisted. */
export async function appendLiveAudio(key: LiveAudioKey, index: number, pcm: Blob): Promise<void> {
  const started = generation
  assertOwner(key, started)
  const db = await open()
  assertOwner(key, started)
  const transaction = db.transaction(['recordings', 'chunks'], 'readwrite', { durability: 'strict' })
  const completion = done(transaction)
  const records = transaction.objectStore('recordings')
  const request = records.get(key)
  request.onsuccess = () => {
    const record = request.result as StoredLiveAudio | undefined
    // Deleted, expired or incomplete recordings must never be recreated by a late writer.
    if (!record || record.expiresAt <= Date.now() || record.count !== index || key[0] !== owner || started !== generation) {
      transaction.abort()
      return
    }
    try {
      transaction.objectStore('chunks').add({ key: [...key, index], recording: key, index, pcm } satisfies StoredLiveChunk)
      records.put({ ...record, count: index + 1, frames: record.frames + pcm.size / 2 })
    } catch { transaction.abort() }
  }
  await completion
}

export async function listLiveAudio(scope: LiveAudioScope): Promise<StoredLiveAudio[]> {
  const started = generation
  await sweep()
  const db = await open()
  const key: LiveAudioKey = [scope.userId, scope.caseId, scope.sessionNumber, '']
  assertOwner(key, started)
  const transaction = db.transaction('recordings', 'readonly')
  const completion = done(transaction)
  const request = transaction.objectStore('recordings').getAll(IDBKeyRange.bound(key, [...key.slice(0, 3), []]))
  await completion
  assertOwner(key, started)
  return (request.result as StoredLiveAudio[]).filter(record => record.count > 0 && record.expiresAt > Date.now())
}

export async function loadLiveAudio(key: LiveAudioKey): Promise<{ record: StoredLiveAudio; chunks: StoredLiveChunk[] }> {
  const started = generation
  await sweep()
  const db = await open()
  assertOwner(key, started)
  const transaction = db.transaction(['recordings', 'chunks'], 'readonly')
  const completion = done(transaction)
  const metadata = transaction.objectStore('recordings').get(key)
  const parts = transaction.objectStore('chunks').index('recording').getAll(IDBKeyRange.only(key))
  await completion
  assertOwner(key, started)
  const record = metadata.result as StoredLiveAudio | undefined
  if (!record || record.expiresAt <= Date.now()) throw new Error('보관된 녹음이 만료되었거나 삭제되었습니다.')
  const chunks = (parts.result as StoredLiveChunk[]).sort((a, b) => a.index - b.index)
  if (chunks.length !== record.count || chunks.some((part, index) => part.index !== index)) throw new Error('보관된 녹음 구간을 확인하지 못했습니다.')
  return { record, chunks }
}

export async function deleteLiveAudio(key: LiveAudioKey): Promise<void> {
  const started = generation
  const db = await open()
  assertOwner(key, started)
  const transaction = db.transaction(['recordings', 'chunks'], 'readwrite')
  const completion = done(transaction)
  remove(transaction, key)
  await completion
  changed()
}

export function rememberLiveAudioFile(file: File, key: LiveAudioKey): void { files.set(file, key) }
export async function deleteLiveAudioFile(file: File): Promise<void> {
  const key = files.get(file)
  if (key) { await deleteLiveAudio(key); files.delete(file) }
}
