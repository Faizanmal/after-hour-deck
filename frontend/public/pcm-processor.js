class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = options.processorOptions || {};
    const inputSampleRate = opts.inputSampleRate || sampleRate;
    const targetSampleRate = opts.targetSampleRate || 24000;
    this.ratio = inputSampleRate / targetSampleRate;
    this.pending = [];
    this.frameTarget = Math.round(targetSampleRate * 0.05);
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;

    const outLength = Math.floor(input.length / this.ratio);
    for (let i = 0; i < outLength; i++) {
      const sample = input[Math.floor(i * this.ratio)] ?? 0;
      this.pending.push(Math.max(-1, Math.min(1, sample)));
    }

    while (this.pending.length >= this.frameTarget) {
      const slice = this.pending.splice(0, this.frameTarget);
      const pcm16 = new Int16Array(slice.length);
      for (let i = 0; i < slice.length; i++) {
        pcm16[i] = Math.max(-32768, Math.min(32767, Math.round(slice[i] * 32767)));
      }
      this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
