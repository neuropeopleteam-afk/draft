// Запасной голос без видеопотока: PCM s16le (16/24 кГц) через Web Audio, кусками по мере прихода, без пауз между ними.
// Используется, пока поток аватара подключается или переподключается, и если он не поднялся вовсе: голос не теряется.
export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private gain: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private next = 0;  // время контекста, когда закончится последний запланированный кусок
  private nextWall = 0;  // то же по часам страницы (performance.now), когда контекст не идёт (звук заблокирован)
  private buf: Uint8Array<ArrayBuffer> = new Uint8Array(512);

  /** Создать/разбудить контекст — звать из обработчика нажатия (правило автозапуска звука). */
  unlock(): AudioContext | null {
    try {
      if (!this.ctx) {
        const ctx = new AudioContext();
        const gain = ctx.createGain();
        const an = ctx.createAnalyser();
        an.fftSize = 512;
        gain.connect(an);
        an.connect(ctx.destination);
        this.ctx = ctx; this.gain = gain; this.analyser = an;
      }
      if (this.ctx.state === "suspended") void this.ctx.resume().catch(() => undefined);
    } catch { return null; }
    return this.ctx;
  }

  /** Поставить кусок в очередь; возвращает момент (performance.now), когда он доиграет. */
  push(bytes: Uint8Array, rate: number): number {
    const ctx = this.unlock();
    if (!ctx || !this.gain) return performance.now();
    const n = Math.floor(bytes.byteLength / 2);
    if (!n) return this.untilMs();
    if (ctx.state !== "running") {
      // контекст не идёт (автозапуск звука запрещён, нет жеста): его часы стоят, поэтому считаем по часам страницы —
      // реплики идут в реальном темпе и не накапливают задержку; звук в это время не ставим (иначе при пробуждении
      // всё накопленное прозвучит разом)
      const startMs = Math.max(performance.now() + 30, this.nextWall);
      this.nextWall = startMs + (n / rate) * 1000;
      return this.untilMs();
    }
    const view = new DataView(bytes.buffer, bytes.byteOffset, n * 2);
    const ab = ctx.createBuffer(1, n, rate);
    const ch = ab.getChannelData(0);
    for (let i = 0; i < n; i++) ch[i] = view.getInt16(i * 2, true) / 32768;
    const src = ctx.createBufferSource();
    src.buffer = ab;
    src.connect(this.gain);
    const at = Math.max(ctx.currentTime + 0.03, this.next);
    src.start(at);
    this.next = at + ab.duration;
    this.sources.add(src);
    src.onended = () => { this.sources.delete(src); };
    return this.untilMs();
  }

  untilMs(): number {
    const ctx = this.ctx;
    const wall = this.nextWall > performance.now() ? this.nextWall : 0;
    if (!ctx || this.next <= ctx.currentTime) return wall;
    return Math.max(wall, performance.now() + (this.next - ctx.currentTime) * 1000);
  }

  playing(): boolean { return this.untilMs() > performance.now(); }

  setVolume(v: number) { if (this.gain && this.ctx) this.gain.gain.setTargetAtTime(v, this.ctx.currentTime, 0.05); }

  stop() {
    for (const s of this.sources) { try { s.stop(); } catch { /* уже остановлен */ } }
    this.sources.clear();
    this.next = 0;
    this.nextWall = 0;
  }

  level(): number {
    const an = this.analyser;
    if (!an || !this.playing()) return 0;
    if (this.buf.length !== an.fftSize) this.buf = new Uint8Array(an.fftSize);
    an.getByteTimeDomainData(this.buf);
    let acc = 0;
    for (let i = 0; i < this.buf.length; i++) { const v = (this.buf[i] - 128) / 128; acc += v * v; }
    return Math.min(1, Math.sqrt(acc / this.buf.length) * 3);
  }

  close() {
    this.stop();
    const ctx = this.ctx;
    this.ctx = null;
    void ctx?.close().catch(() => undefined);
  }
}
