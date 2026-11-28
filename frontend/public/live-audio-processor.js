/** Mono PCM capture with a continuous box-filter resampler; the output stays silent. */
class RemindLiveAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.active = false
    this.ratio = sampleRate / 16000
    this.weight = 0
    this.sum = 0
    this.buffer = new Float32Array(2048)
    this.length = 0
    this.port.onmessage = event => {
      if (event.data.type === 'resume') this.active = true
      if (event.data.type === 'pause' || event.data.type === 'stop') {
        this.active = false
        this.flush()
        this.sum = 0
        this.weight = 0
        if (event.data.type === 'stop') this.port.postMessage({ type: 'stopped' })
      }
    }
  }

  flush() {
    if (!this.length) return
    const samples = this.buffer.slice(0, this.length)
    this.port.postMessage({ type: 'samples', samples }, [samples.buffer])
    this.length = 0
  }

  process(inputs, outputs) {
    for (const channel of outputs[0] || []) channel.fill(0)
    const channels = inputs[0]
    if (!this.active || !channels?.length || !channels[0]?.length) return true
    for (let frame = 0; frame < channels[0].length; frame++) {
      let sample = 0
      for (const channel of channels) sample += channel[frame] / channels.length
      let remaining = 1
      while (remaining > 1e-9) {
        const weight = Math.min(remaining, this.ratio - this.weight)
        this.sum += sample * weight
        this.weight += weight
        remaining -= weight
        if (this.weight >= this.ratio - 1e-9) {
          this.buffer[this.length++] = this.sum / this.ratio
          this.sum = 0
          this.weight = 0
          if (this.length === this.buffer.length) this.flush()
        }
      }
    }
    return true
  }
}

registerProcessor('remind-live-audio', RemindLiveAudioProcessor)
