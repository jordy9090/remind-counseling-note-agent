/** Read seekable PCM WAVs in bounded windows, including files larger than 500 MB. */
export interface WavSource {
  duration: number
  sampleRate: number
  frameCount: number
  read: (firstFrame: number, frameCount: number) => Promise<ArrayBuffer>
}

export async function openWavSource(file: File): Promise<WavSource | null> {
  const header = new Uint8Array(await file.slice(0, 12).arrayBuffer())
  const tag = (bytes: Uint8Array, start: number) => String.fromCharCode(...bytes.subarray(start, start + 4))
  if (tag(header, 0) !== 'RIFF' || tag(header, 8) !== 'WAVE') return null
  const invalid = () => new Error('WAV 파일의 형식이나 길이 정보가 올바르지 않습니다.')
  const declaredEnd = new DataView(header.buffer).getUint32(4, true) + 8
  if (declaredEnd > file.size || declaredEnd < 12) throw invalid()
  let format: Uint8Array | undefined, dataStart = 0, dataSize = 0
  for (let offset = 12, count = 0; offset + 8 <= declaredEnd; count++) {
    if (count >= 256) throw invalid()
    const chunk = new Uint8Array(await file.slice(offset, offset + 8).arrayBuffer())
    const size = new DataView(chunk.buffer).getUint32(4, true), start = offset + 8
    if (start + size > declaredEnd) throw invalid()
    if (tag(chunk, 0) === 'fmt ') {
      if (size < 16 || size > 64 || size % 2 || format) throw invalid()
      format = new Uint8Array(await file.slice(start, start + size).arrayBuffer())
    }
    if (tag(chunk, 0) === 'data') { dataStart = start; dataSize = size; break }
    offset = start + size + (size % 2)
  }
  if (!format || !dataStart || !dataSize) throw invalid()
  const view = new DataView(format.buffer)
  let encoding = view.getUint16(0, true)
  if (encoding === 0xfffe && format.length >= 40) encoding = view.getUint16(24, true)
  const channels = view.getUint16(2, true), sampleRate = view.getUint32(4, true)
  const blockAlign = view.getUint16(12, true), bits = view.getUint16(14, true)
  if (![1, 3].includes(encoding) || channels < 1 || channels > 8 || sampleRate < 8000 || sampleRate > 192000
      || ![8, 16, 24, 32].includes(bits) || (encoding === 3 && bits !== 32)
      || blockAlign !== channels * bits / 8 || dataSize % blockAlign) throw invalid()
  const frameCount = dataSize / blockAlign
  return {
    duration: frameCount / sampleRate, sampleRate, frameCount,
    async read(firstFrame, frames) {
      if (!Number.isInteger(firstFrame) || !Number.isInteger(frames) || firstFrame < 0 || frames < 1
          || firstFrame + frames > frameCount || frames > 61 * sampleRate) throw invalid()
      const pcmSize = frames * blockAlign
      const fmt = format!
      const bytes = new Uint8Array(28 + fmt.length + pcmSize + pcmSize % 2)
      const out = new DataView(bytes.buffer)
      const label = (offset: number, text: string) => [...text].forEach((char, i) => { bytes[offset + i] = char.charCodeAt(0) })
      label(0, 'RIFF'); out.setUint32(4, bytes.length - 8, true); label(8, 'WAVE')
      label(12, 'fmt '); out.setUint32(16, fmt.length, true); bytes.set(fmt, 20)
      label(20 + fmt.length, 'data'); out.setUint32(24 + fmt.length, pcmSize, true)
      bytes.set(new Uint8Array(await file.slice(dataStart + firstFrame * blockAlign,
        dataStart + (firstFrame + frames) * blockAlign).arrayBuffer()), 28 + fmt.length)
      return bytes.buffer
    },
  }
}
