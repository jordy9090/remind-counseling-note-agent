export interface DraftGenerationOptions<T> {
  generate: () => Promise<T>
  onError: (error: unknown) => void
  onSuccess: (result: T) => void
  setLoading: (loading: boolean) => void
}

export async function runDraftGeneration<T>({
  generate,
  onError,
  onSuccess,
  setLoading,
}: DraftGenerationOptions<T>): Promise<void> {
  setLoading(true)
  try {
    onSuccess(await generate())
  } catch (error) {
    onError(error)
  } finally {
    setLoading(false)
  }
}
