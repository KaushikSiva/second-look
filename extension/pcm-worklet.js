// Second Look — mic capture AudioWorklet.
// Downsamples the native-rate mic stream to 16 kHz mono (box-filter average per output
// sample, which doubles as a cheap anti-alias low-pass), converts to Int16 LE and posts
// ~100 ms chunks (transferable ArrayBuffers) to the main thread.
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = (options && options.processorOptions) || {};
    this.targetRate = o.targetRate || 16000;
    this.ratio = sampleRate / this.targetRate; // input samples per output sample
    this.chunkSize = Math.max(160, Math.round(this.targetRate * (o.chunkMs || 100) / 1000));
    this.buf = new Int16Array(this.chunkSize);
    this.n = 0;
    this.pos = 0;
    this.acc = 0;
    this.accN = 0;
    this.port.onmessage = (e) => {
      if (e.data === 'flush') this.flush();
    };
  }

  emit(v) {
    const s = v < -1 ? -1 : v > 1 ? 1 : v;
    this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    if (this.n === this.chunkSize) this.flush();
  }

  flush() {
    if (!this.n) return;
    const out = this.buf.slice(0, this.n);
    this.port.postMessage(out.buffer, [out.buffer]);
    this.n = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;
    const chans = input.length;
    const len = input[0].length;
    for (let i = 0; i < len; i++) {
      let x = input[0][i];
      if (chans > 1) {
        for (let c = 1; c < chans; c++) x += input[c][i];
        x /= chans;
      }
      this.acc += x;
      this.accN++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        const v = this.acc / this.accN;
        this.acc = 0;
        this.accN = 0;
        // ratio < 1 (input slower than 16 kHz) → repeat samples
        while (this.pos >= this.ratio) {
          this.pos -= this.ratio;
          this.emit(v);
        }
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
