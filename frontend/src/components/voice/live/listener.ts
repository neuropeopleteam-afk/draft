// Живой микрофон «как по видеосвязи»: включается один раз (эхоподавление, шумоподавление, автоусиление браузера),
// дальше непрерывно шлёт PCM 16 кГц в /api/interview/live/stt и получает события распознавания (речь началась,
// промежуточный и окончательный текст, пауза). Никаких кнопок «нажми и говори» после каждой реплики.
// Обрыв канала — тихое переподключение (до 5 раз за минуту) с буфером последних 5 с звука.
import { CAPTURE_WORKLET } from "./capture";

export type SttEvent =
  | { type: "ready" }
  | { type: "speech_started" }
  | { type: "interim"; text: string }
  | { type: "final"; text: string; speech_final: boolean }
  | { type: "speech_final_empty" }
  | { type: "utterance_end" }
  | { type: "error"; message?: string };

export type MicState = "off" | "connecting" | "on" | "muted" | "denied" | "nodevice" | "error";

export interface ListenerOptions {
  onEvent: (e: SttEvent) => void;
  onState?: (s: MicState) => void;
  /** true — вместо звука слать тишину (распознавание не нужно, канал держим открытым). */
  gate?: () => boolean;
  path?: string;
}

const MAX_PENDING = 50;  // ~5 с звука, пока канал переподключается

export function liveSttSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioWorkletNode !== "undefined"
    && typeof WebSocket !== "undefined";
}

export class LiveListener {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private ws: WebSocket | null = null;
  private pending: ArrayBuffer[] = [];
  private closed = false;
  private attempt = 0;
  private reconnects: number[] = [];
  private reconnectTimer = 0;
  private lvl = 0;
  private muted = false;
  private state: MicState = "off";
  private readyOnce = false;

  constructor(private opts: ListenerOptions) {}

  level(): number { return this.muted ? 0 : this.lvl; }
  getState(): MicState { return this.state; }
  isMuted(): boolean { return this.muted; }

  private set(s: MicState) {
    this.state = s;
    this.opts.onState?.(s);
  }

  /** Включить микрофон (нужно разрешение браузера; лучше звать из обработчика нажатия или сразу после него). */
  async start(): Promise<MicState> {
    if (this.closed) return "off";
    if (!liveSttSupported()) { this.set("error"); return "error"; }
    this.set("connecting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      const name = (e as { name?: string })?.name ?? "";
      const st: MicState = name === "NotAllowedError" || name === "SecurityError" ? "denied"
        : name === "NotFoundError" || name === "OverconstrainedError" ? "nodevice" : "error";
      this.set(st);
      return st;
    }
    if (this.closed) { this.stream.getTracks().forEach((t) => t.stop()); return "off"; }
    try {
      const ctx = new AudioContext();
      this.ctx = ctx;
      const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "application/javascript" }));
      try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
      if (this.closed) { await this.teardown(); return "off"; }
      const src = ctx.createMediaStreamSource(this.stream);
      const node = new AudioWorkletNode(ctx, "draft-capture");
      const silent = ctx.createGain();
      silent.gain.value = 0;
      src.connect(node); node.connect(silent); silent.connect(ctx.destination);
      this.node = node;
      node.port.onmessage = (ev: MessageEvent<{ b: ArrayBuffer; l: number }>) => this.onFrame(ev.data);
      ctx.onstatechange = () => { if (ctx.state === "suspended" && !this.closed) void ctx.resume().catch(() => undefined); };
      await ctx.resume().catch(() => undefined);
      document.addEventListener("visibilitychange", this.onVisible);
    } catch {
      await this.teardown();
      this.set("error");
      return "error";
    }
    this.connect();
    this.set(this.muted ? "muted" : "on");
    return this.state;
  }

  private onVisible = () => { if (document.visibilityState === "visible") void this.ctx?.resume().catch(() => undefined); };

  private onFrame({ b, l }: { b: ArrayBuffer; l: number }) {
    this.lvl = this.lvl * 0.5 + Math.min(1, l * 4) * 0.5;
    const gated = this.muted || (this.opts.gate?.() ?? false);
    const payload = gated ? new ArrayBuffer(b.byteLength) : b;
    const ws = this.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(payload); } catch { if (!gated) this.pending.push(payload); }
    } else if (!gated) {
      this.pending.push(payload);
      if (this.pending.length > MAX_PENDING) this.pending = this.pending.slice(-MAX_PENDING);
    }
  }

  private connect() {
    if (this.closed) return;
    const path = this.opts.path ?? "/api/interview/live/stt";
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      for (const chunk of this.pending.splice(0)) { try { ws.send(chunk); } catch { /* канал снова закрылся */ } }
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws || this.closed) return;
      try {
        const e = JSON.parse(String(ev.data)) as SttEvent;
        if (e.type === "ready") { this.attempt = 0; this.readyOnce = true; }
        this.opts.onEvent(e);
      } catch { /* битое сообщение — пропускаем */ }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.closed) return;
      const now = Date.now();
      this.reconnects = this.reconnects.filter((t) => now - t < 60000);
      if (this.reconnects.length >= 5 || (!this.readyOnce && this.attempt >= 2)) {
        this.set("error");
        this.opts.onEvent({ type: "error", message: "stt_closed" });
        return;
      }
      this.reconnects.push(now);
      this.reconnectTimer = window.setTimeout(() => this.connect(), 300 * 2 ** this.attempt++);
    };
    ws.onerror = () => { /* onclose переподключит */ };
  }

  /** Выключить/включить микрофон (кнопка «без звука»), канал остаётся открытым. */
  setMuted(m: boolean) {
    this.muted = m;
    this.stream?.getAudioTracks().forEach((t) => { t.enabled = !m; });
    if (this.state === "on" || this.state === "muted") this.set(m ? "muted" : "on");
  }

  /** Попросить сервер дослать распознанное сразу (конец хода без ожидания паузы). */
  finalize() {
    try { this.node?.port.postMessage("flush"); } catch { /* ignore */ }
    try { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "finalize" })); } catch { /* ignore */ }
  }

  resume() { void this.ctx?.resume().catch(() => undefined); }

  private async teardown() {
    document.removeEventListener("visibilitychange", this.onVisible);
    if (this.node) { this.node.port.onmessage = null; try { this.node.disconnect(); } catch { /* ignore */ } }
    this.node = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    const ctx = this.ctx;
    this.ctx = null;
    await ctx?.close().catch(() => undefined);
  }

  stop() {
    if (this.closed) return;
    this.closed = true;
    window.clearTimeout(this.reconnectTimer);
    const ws = this.ws;
    this.ws = null;
    try { ws?.close(); } catch { /* ignore */ }
    void this.teardown();
    this.set("off");
  }
}
