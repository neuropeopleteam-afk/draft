// Захват микрофона в AudioWorklet: понижение частоты до 16 кГц, PCM s16le кадрами по 100 мс + громкость кадра (RMS).
// Кадр уходит в WebSocket живого распознавания (/api/interview/live/stt), громкость — индикатору микрофона.
export const CAPTURE_WORKLET = `
class DraftCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.acc = 0; this.sum = 0; this.n = 0;
    this.out = new Int16Array(1600); this.pos = 0; this.energy = 0;
    this.port.onmessage = (e) => { if (e.data === "flush") this.flush(); };
  }
  flush() {
    if (this.pos === 0) return;
    const chunk = this.out.slice(0, this.pos);
    const level = Math.sqrt(this.energy / this.pos);
    this.pos = 0; this.energy = 0;
    this.port.postMessage({ b: chunk.buffer, l: level }, [chunk.buffer]);
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.sum += ch[i]; this.n++; this.acc += 1;
      if (this.acc >= this.ratio) {
        this.acc -= this.ratio;
        const v = Math.max(-1, Math.min(1, this.sum / this.n));
        this.sum = 0; this.n = 0;
        this.out[this.pos++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        this.energy += v * v;
        if (this.pos === this.out.length) this.flush();
      }
    }
    return true;
  }
}
registerProcessor("draft-capture", DraftCapture);
`;
