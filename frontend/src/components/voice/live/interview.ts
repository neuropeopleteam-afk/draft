// Устная защита «как по видеосвязи»: микрофон включается один раз в начале разговора, вопросы звучат голосом
// интервьюера (потоком, первый звук ≈ 1 с), ответ уходит сам, когда кандидат договорил (пауза ~2 с, «я закончил» — сразу).
// Можно перебить вопрос и начать отвечать; «повторите вопрос» — повтор без отправки ответа.
// Пока ответ записывается, звучит короткое «Спасибо.» — без мёртвой тишины.
import { apiUrl } from "../../../lib/api";
import type { AnamHandle } from "../AnamAvatar";
import { LiveListener, liveSttSupported, type MicState, type SttEvent } from "./listener";
import { SpeechBuffer, bargeIn, endDelay, isEcho, stripEndMarker, words } from "./turns";
import { Voice } from "./voice";

export type LivePhase = "starting" | "speaking" | "listening" | "thinking" | "off";
export interface LiveView { phase: LivePhase; mic: MicState; talking: boolean }

export interface LiveInterviewDeps {
  avatar: () => AnamHandle | null;
  /** Адрес голоса текущего вопроса (или прощания, если разговор закрыт): PCM 24 кГц потоком. */
  speechUrl: () => string;
  headers: () => Record<string, string>;
  onView: (v: LiveView) => void;
  /** Отправить ответ; true — принят (следующий вопрос придёт с обновлением сессии). */
  onAnswer: (text: string) => Promise<boolean>;
  onRepeat: () => void;
  /** Живой микрофон недоступен — экран переходит на кнопку «Ответить» или чат. */
  onUnavailable: (why: MicState) => void;
}

const RATE = 24000;
const STALE_MS = 3500;
const REPEAT_RX = /^(?:повтори(?:те)?|ещё раз|еще раз|не расслышал\w*|не понял\w*|можно ещё раз|можно еще раз|что вы сказали)/u;
const FILLERS = ["Спасибо.", "Понятно, спасибо."];
const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

export function liveInterviewSupported(): boolean { return liveSttSupported(); }

export class LiveInterview {
  readonly voice: Voice;
  private listener: LiveListener | null = null;
  private buf = new SpeechBuffer();
  private view: LiveView = { phase: "starting", mic: "off", talking: false };
  private closed = false;
  private busy = false;
  private asking = 0;
  private endTimer = 0;
  private staleTimer = 0;
  private firstAsk = true;
  private fillerN = 0;
  private fillers = new Map<string, Promise<Uint8Array | null>>();

  constructor(private d: LiveInterviewDeps) {
    this.voice = new Voice(d.avatar);
  }

  private set(p: Partial<LiveView>) {
    if (this.closed) return;
    this.view = { ...this.view, ...p };
    this.d.onView(this.view);
  }

  micLevel(): number { return this.listener?.level() ?? 0; }
  level(): number { return this.voice.level(); }
  isMuted(): boolean { return this.listener?.isMuted() ?? false; }

  /** Звать из обработчика нажатия «Начать разговор»: звук и микрофон разрешаются этим жестом. */
  start() {
    this.voice.unlock();
    this.listener = new LiveListener({
      onEvent: (e) => this.onStt(e),
      onState: (s) => {
        this.set({ mic: s });
        if (s === "denied" || s === "nodevice" || s === "error") this.d.onUnavailable(s);
      },
      gate: () => this.busy,
    });
    void this.listener.start();
    for (const f of FILLERS) {
      this.fillers.set(f, fetch(apiUrl("/interview/concierge/speech"), {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: f, format: "pcm24" }),
      }).then(async (r) => (r.ok ? new Uint8Array(await r.arrayBuffer()) : null)).catch(() => null));
    }
  }

  toggleMute() {
    if (!this.listener) return;
    this.listener.setMuted(!this.listener.isMuted());
    this.set({ mic: this.listener.getState() });
  }

  private clearTimers() {
    window.clearTimeout(this.endTimer);
    window.clearTimeout(this.staleTimer);
    this.endTimer = this.staleTimer = 0;
  }

  /** Задать текущий вопрос голосом (новый вопрос или «повторить»). */
  async ask(question: string): Promise<void> {
    if (this.closed) return;
    const my = ++this.asking;
    this.voice.stop();
    this.clearTimers();
    this.buf.reset();
    this.busy = false;
    this.set({ phase: "speaking", talking: false });
    if (this.firstAsk) {
      this.firstAsk = false;
      const a = this.d.avatar();
      if (a) await Promise.race([a.waitReady(5000), sleep(5200)]);
    }
    if (my !== this.asking || this.closed) return;
    try {
      const r = await fetch(this.d.speechUrl(), { headers: this.d.headers() });
      if (!r.ok || !r.body) throw new Error(String(r.status));
      if (my !== this.asking || this.closed) { void r.body.cancel().catch(() => undefined); return; }
      await this.voice.say(question, r.body, RATE);
    } catch { /* голос недоступен — текст вопроса открывается ссылкой, слушаем ответ */ }
    if (my !== this.asking || this.closed) return;
    this.set({ phase: "listening" });
  }

  /** Прощание тем же голосом (разговор закрыт), затем микрофон выключается. */
  async closing(): Promise<void> {
    if (this.closed) return;
    const my = ++this.asking;
    this.busy = true;
    this.clearTimers();
    this.set({ phase: "speaking", talking: false });
    try {
      const r = await fetch(this.d.speechUrl(), { headers: this.d.headers() });
      if (r.ok && r.body && my === this.asking) await this.voice.say("", r.body, RATE);
    } catch { /* прощание уже на экране текстом */ }
    this.stop();
  }

  private onStt(e: SttEvent) {
    if (this.closed || this.busy) return;
    if (e.type === "interim" || e.type === "final") {
      const text = e.text.trim();
      if (!text) return;
      const her = this.voice.echoText();
      if (this.voice.speaking()) {
        const heard = (this.buf.read() + " " + text).trim();
        if (!bargeIn(heard, her, this.voice.sinceStart(), 3)) return;
        this.asking++;          // вопрос перебили — дальше слушаем ответ
        this.voice.stop();
        this.set({ phase: "listening" });
      } else if (her && isEcho(text, her)) {
        return;
      }
      if (this.buf.accept(e)) {
        if (!this.view.talking) this.set({ talking: true, phase: "listening" });
        window.clearTimeout(this.endTimer);
        this.endTimer = 0;
        this.armStale();
      }
      if (e.type === "final" && e.speech_final) this.armEnd();
      return;
    }
    if (e.type === "speech_final_empty" || e.type === "utterance_end") {
      if (this.buf.read() && !this.endTimer) this.armEnd();
    }
  }

  private armStale() {
    window.clearTimeout(this.staleTimer);
    const v = this.buf.version;
    this.staleTimer = window.setTimeout(() => {
      if (this.buf.version === v && this.buf.read() && !this.endTimer) this.armEnd();
    }, STALE_MS);
  }

  private armEnd() {
    const text = this.buf.read();
    if (!text) return;
    window.clearTimeout(this.endTimer);
    const v = this.buf.version;
    this.endTimer = window.setTimeout(() => {
      this.endTimer = 0;
      if (this.buf.version === v) void this.submit();
    }, endDelay(text, "answer"));
  }

  private async submit() {
    window.clearTimeout(this.staleTimer);
    const raw = this.buf.take();
    this.set({ talking: false });
    const text = stripEndMarker(raw);
    const n = words(text).length;
    if (n <= 5 && REPEAT_RX.test(text.toLowerCase())) { this.d.onRepeat(); return; }
    if (n < 2) return;   // одиночное «э», «да» — ещё не ответ
    this.busy = true;
    this.set({ phase: "thinking" });
    const f = FILLERS[this.fillerN++ % FILLERS.length];
    void this.fillers.get(f)?.then((pcm) => { if (pcm && this.busy && !this.closed && !this.voice.speaking()) void this.voice.say(f, pcm, RATE); });
    let ok = false;
    try { ok = await this.d.onAnswer(text); } catch { ok = false; }
    if (!ok && !this.closed) { this.busy = false; this.set({ phase: "listening" }); }
    // принят — следующий вопрос придёт с обновлением сессии (ask), до тех пор микрофон молчит
  }

  stop() {
    if (this.closed) return;
    this.asking++;
    this.clearTimers();
    this.voice.close();
    this.listener?.stop();
    this.set({ phase: "off", talking: false });
    this.closed = true;
  }
}
