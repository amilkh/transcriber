class PCMRecorder extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const processorOptions = options.processorOptions || {};
    this.targetSampleRate = processorOptions.targetSampleRate || 16000;
    this.chunkMillis = processorOptions.chunkMillis || 200;
    this.inputSampleRate = sampleRate;
    this.resampleRatio = this.inputSampleRate / this.targetSampleRate;
    this.floatBuffer = [];
    this.chunkSamples = Math.floor((this.targetSampleRate * this.chunkMillis) / 1000);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) {
      return true;
    }

    const channelData = input[0];

    for (let i = 0; i < channelData.length; i += this.resampleRatio) {
      const idx = Math.floor(i);
      if (idx < channelData.length) {
        this.floatBuffer.push(channelData[idx]);
      }

      if (this.floatBuffer.length >= this.chunkSamples) {
        const chunk = this.floatBuffer.slice(0, this.chunkSamples);
        this.floatBuffer = this.floatBuffer.slice(this.chunkSamples);

        const pcm = new Int16Array(chunk.length);
        for (let j = 0; j < chunk.length; j++) {
          const s = Math.max(-1, Math.min(1, chunk[j]));
          pcm[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }

        this.port.postMessage(pcm.buffer, [pcm.buffer]);
      }
    }

    return true;
  }
}

registerProcessor("pcm-recorder", PCMRecorder);
