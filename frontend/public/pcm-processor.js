/**
 * AudioWorklet processor that captures microphone audio, downsamples to 16 kHz,
 * converts Float32 samples to 16-bit signed little-endian PCM, and posts chunks
 * to the main thread for streaming over the Pipecat WebSocket.
 */
class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._targetRate = 16000;
    this._buffer = [];
    this._chunkSize = 1600; // 100ms at 16kHz
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const channelData = input[0];
    const ratio = sampleRate / this._targetRate;

    if (ratio === 1) {
      for (let i = 0; i < channelData.length; i++) {
        this._buffer.push(channelData[i]);
      }
    } else {
      const newLength = Math.floor(channelData.length / ratio);
      for (let i = 0; i < newLength; i++) {
        const start = Math.floor(i * ratio);
        const end = Math.min(Math.floor((i + 1) * ratio), channelData.length);
        let sum = 0;
        for (let j = start; j < end; j++) {
          sum += channelData[j];
        }
        this._buffer.push(sum / Math.max(1, end - start));
      }
    }

    while (this._buffer.length >= this._chunkSize) {
      const slice = this._buffer.splice(0, this._chunkSize);
      const pcm16 = new Int16Array(slice.length);
      let energy = 0;
      for (let i = 0; i < slice.length; i++) {
        const s = Math.max(-1, Math.min(1, slice[i]));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        energy += s * s;
      }
      const rms = Math.sqrt(energy / slice.length);
      this.port.postMessage(
        { pcm: pcm16.buffer, rms },
        [pcm16.buffer]
      );
    }

    return true;
  }
}

registerProcessor('pcm-capture-processor', PCMCaptureProcessor);
