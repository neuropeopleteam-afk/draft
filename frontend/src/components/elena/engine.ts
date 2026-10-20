// Елена — живой проводник «как по видеосвязи». Один микрофон на весь разговор (LiveListener), голос — в видеопоток
// аватара (Voice), решения по ходу разговора — сервер (/api/interview/concierge/turn, поток NDJSON), постоянные фразы
// и реплики шагов — из кэша, заранее загруженные в память (переходы без пауз).
//
// Правила разговора:
//  • человек говорит, когда хочет: явная реплика перебивает Елену сразу (эхо её голоса и «угу» — нет);
//  • конец хода — пауза после фразы (короче для команд и вопросов, длиннее для незаконченной мысли);
//  • человек продолжил мысль, пока Елена ещё не ответила, — ход склеивается, ответ один;
//  • модель думает дольше 0,45 с — короткая связка («Секунду.»), ответ встаёт сразу за ней;
//  • обзор: подсветка, прокрутка, «нажатие» в нужный момент реплики; следующий экран готовится, пока звучит текущий;
//  • перебили посреди шага — после ответа обзор продолжается сам (шаг повторяется, если прозвучало меньше 60 %).
import { apiUrl, tokenStore, type MeOut } from "../../lib/api";
import type { Persona } from "../../lib/jury";
import type { AnamHandle } from "../voice/AnamAvatar";
import { LiveListener, liveSttSupported, type MicState, type SttEvent } from "../voice/live/listener";
import { SpeechBuffer, bargeIn, endDelay, isBackchannel, isEcho, words } from "../voice/live/turns";
import { Voice, type SayResult, type Utterance } from "../voice/live/voice";
import { STEPS, TRACKS, trackFor, type TourStep, type TourTrack } from "./steps";

export type Phase = "idle" | "connecting" | "greeting" | "listening" | "thinking" | "answering" | "touring" | "paused";

export interface ElenaUi {
  phase: Phase;
  mic: MicState;
  speaking: boolean;
  userTalking: boolean;
  track: TourTrack | null;
  /** Номер шага обзора (с 1); 0 — обзор не идёт. */
  stepNo: number;
  stepTotal: number;
  /** Что подсвечено на экране. */
  target: string | null;
  /** Куда и когда (performance.now) «нажмёт» курсор. */
  click: { selector: string; at: number } | null;
  canPause: boolean;
}

export interface ElenaDeps {
  avatar: () => AnamHandle | null;
  navigate: (to: string) => void;
  path: () => string;
  me: () => MeOut | null;
  login: (p: Persona, next: string) => Promise<string>;
  onUi: (ui: ElenaUi) => void;
  onClose: () => void;
}

interface Script {
  greeting: string;
  nudge: string;
  bridges: Record<string, string>;
  phrases: Record<string, string>;
  fillers: string[];
  steps: Record<string, string>;
}

interface Meta {
  action?: string;
  role?: string | null;
  step?: string | null;
  user_name?: string | null;
  text?: string;
  kind?: string;
}

const RATE = 24000;
const BYTES_PER_MS = (RATE * 2) / 1000;
const PIPE_MS = 650;               // звук из видеопотока звучит примерно через столько после отправки
const IDLE_AFTER_GREETING_MS = 7000;
const IDLE_AFTER_QUESTION_MS = 9000;
const RESUME_AFTER_ANSWER_MS = 1300;
const FILLER_AFTER_MS = 450;
const STALE_INTERIM_MS = 2200;     // промежуточный текст не меняется — считаем фразу законченной
const REPEAT_IF_HEARD_LESS = 0.6;
const NAME_KEY = "draft.concierge.name";

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

function b64bytes(b64: string): Uint8Array {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

function visible(el: Element): boolean {
  const r = (el as HTMLElement).getBoundingClientRect?.();
  return !!r && r.width > 0 && r.height > 0;
}

/** Первый видимый элемент из списка селекторов через запятую (по порядку списка, а не документа). */
export function findTarget(selector: string): HTMLElement | null {
  for (const part of selector.split(",").map((s) => s.trim()).filter(Boolean)) {
    try {
      for (const el of Array.from(document.querySelectorAll(part))) if (visible(el)) return el as HTMLElement;
    } catch { /* неверный селектор — следующий */ }
  }
  return null;
}

async function* ndjson(r: Response): AsyncGenerator<Record<string, unknown>> {
  if (!r.ok || !r.body) throw new Error(`turn_${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (line) yield JSON.parse(line) as Record<string, unknown>;
      }
    }
    if (buf.trim()) yield JSON.parse(buf) as Record<string, unknown>;
  } finally {
    try { reader.releaseLock(); } catch { /* ignore */ }
  }
}

export class ElenaEngine {
  readonly voice: Voice;
  private listener: LiveListener | null = null;
  private script: Script | null = null;
  private cache = new Map<string, Promise<Uint8Array | null>>();
  private queue: string[] = [];
  private loading = 0;
  private ui: ElenaUi = {
    phase: "idle", mic: "off", speaking: false, userTalking: false, track: null, stepNo: 0, stepTotal: 0,
    target: null, click: null, canPause: false,
  };
  private closed = false;
  private ep = 0;                       // текущая «линия» действий; новая линия (ход, пауза, закрытие) обрывает старую
  private buf = new SpeechBuffer();
  private carry = "";                   // ход, отправленный, но ещё без ответа, — склеивается с продолжением фразы
  private pendingText = "";
  private turnCtl: AbortController | null = null;
  private replyStarted = false;
  private endTimer = 0;
  private staleTimer = 0;
  private idleTimer = 0;
  private resumeTimer = 0;
  private duckTimer = 0;
  private clickTimer = 0;
  private speakTick = 0;
  private history: { who: "elena" | "user"; text: string }[] = [];
  private userName: string | null = null;
  // обзор
  private track: TourTrack | null = null;
  private idx = 0;
  private touring = false;              // идёт шаг обзора (или переход к нему)
  private paused = false;               // пауза по просьбе человека
  private resumePending = false;        // обзор прерван вопросом — продолжить после ответа
  private heard = 1;                    // какая доля прерванного шага прозвучала
  private stepUtter: Utterance | null = null;
  private lastCabinet: string | null = null;
  private lastTrack: TourTrack | null = null;
  private lastSaid = "";
  private micKnown: Promise<MicState> | null = null;

  constructor(private d: ElenaDeps) {
    this.voice = new Voice(d.avatar);
    try { this.userName = sessionStorage.getItem(NAME_KEY); } catch { this.userName = null; }
  }

  // ------------------------------------------------------------------ состояние для экрана

  private set(p: Partial<ElenaUi>) {
    if (this.closed) return;
    this.ui = { ...this.ui, ...p };
    this.ui.canPause = this.touring || this.paused || this.resumePending;
    this.d.onUi(this.ui);
  }

  getUi(): ElenaUi { return this.ui; }
  micLevel(): number { return this.listener?.level() ?? 0; }
  isMuted(): boolean { return this.listener?.isMuted() ?? false; }

  /** Индикатор «Елена говорит» — по фактическому звуку (видеопоток или запасной голос). */
  private watchSpeaking() {
    window.clearInterval(this.speakTick);
    this.speakTick = window.setInterval(() => {
      const s = this.voice.speaking();
      if (s !== this.ui.speaking) this.set({ speaking: s });
    }, 150);
  }

  // ------------------------------------------------------------------ голос

  private fetchPcm(text: string): Promise<Uint8Array | null> {
    return fetch(apiUrl("/interview/concierge/speech"), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, format: "pcm24" }),
    }).then(async (r) => (r.ok ? new Uint8Array(await r.arrayBuffer()) : null)).catch(() => null);
  }

  /** Звук фразы: из памяти, иначе загрузка (сразу, вне очереди предзагрузки). */
  private pcm(text: string): Promise<Uint8Array | null> {
    let p = this.cache.get(text);
    if (!p) {
      p = this.fetchPcm(text);
      this.cache.set(text, p);
      void p.then((v) => { if (!v) this.cache.delete(text); });
    }
    return p;
  }

  /** Предзагрузка по три фразы одновременно (сервер не перегружается на холодном кэше). */
  private prefetch(texts: string[]) {
    for (const t of texts) if (t && !this.cache.has(t) && !this.queue.includes(t)) this.queue.push(t);
    const next = () => {
      while (this.loading < 3 && this.queue.length && !this.closed) {
        const t = this.queue.shift()!;
        if (this.cache.has(t)) continue;
        this.loading++;
        void this.pcm(t).finally(() => { this.loading--; next(); });
      }
    };
    next();
  }

  private prefetchSteps(from: number) {
    if (!this.track || !this.script) return;
    const ids = TRACKS[this.track].slice(from, from + 3);
    this.prefetch(ids.map((id) => this.script!.steps[id]).filter(Boolean));
  }

  private alive(ep: number) { return !this.closed && ep === this.ep; }

  /** Сказать постоянную фразу (из памяти). Нет звука — пауза на время чтения, чтобы экран не «пролетал». */
  private async sayText(text: string, ep: number, onStart?: (u: Utterance, totalMs: number) => void): Promise<SayResult> {
    if (!text) return "done";
    const pcm = await this.pcm(text);
    if (!this.alive(ep)) return "aborted";
    this.lastSaid = text;
    if (!pcm) {
      onStart?.({ text, startedAt: performance.now(), durationMs: 0, push: () => undefined, end: async () => "done", progress: () => 1 } as Utterance, 0);
      await sleep(Math.min(6000, 900 + text.length * 45));
      return this.alive(ep) ? "done" : "aborted";
    }
    const total = pcm.byteLength / BYTES_PER_MS;
    return this.voice.say(text, pcm, RATE, (u) => onStart?.(u, total));
  }

  // ------------------------------------------------------------------ запуск и закрытие

  /** Вызывать прямо из обработчика нажатия: звук и микрофон разрешаются жестом пользователя. */
  start(track?: TourTrack, stepIndex = 0) {
    this.voice.unlock();
    this.watchSpeaking();
    if (liveSttSupported()) {
      this.listener = new LiveListener({
        onEvent: (e) => this.onStt(e),
        onState: (s) => this.set({ mic: s }),
      });
      this.micKnown = this.listener.start();
    } else {
      this.set({ mic: "error" });
      this.micKnown = Promise.resolve<MicState>("error");
    }
    void this.boot(track, stepIndex);
  }

  private async loadScript(): Promise<Script | null> {
    for (let i = 0; i < 2; i++) {
      try {
        const ctl = new AbortController();
        const t = window.setTimeout(() => ctl.abort(), 5000);
        const r = await fetch(apiUrl("/interview/concierge/script"), { signal: ctl.signal });
        window.clearTimeout(t);
        if (r.ok) return (await r.json()) as Script;
      } catch { /* повтор */ }
      await sleep(700);
    }
    return null;
  }

  private async waitAvatar(ms: number): Promise<boolean> {
    const t0 = performance.now();
    while (!this.d.avatar() && performance.now() - t0 < 600) await sleep(30);
    const a = this.d.avatar();
    if (!a) return false;
    return a.waitReady(Math.max(500, ms - (performance.now() - t0)));
  }

  private async boot(track?: TourTrack, stepIndex = 0) {
    const ep = ++this.ep;
    this.set({ phase: "connecting" });
    this.d.avatar()?.connect();
    const sc = await this.loadScript();
    if (!this.alive(ep)) return;
    if (!sc) { this.close(); return; }
    this.script = sc;
    const greet = this.pcm(sc.greeting);
    const firstSteps = TRACKS[track ?? "all"].slice(stepIndex, stepIndex + 2).map((id) => sc.steps[id]);
    this.prefetch([sc.phrases.nomic, sc.nudge, ...sc.fillers.slice(0, 2), ...firstSteps, sc.bridges.candidate,
      sc.phrases.hello, sc.phrases.pause, ...Object.values(sc.bridges), ...sc.fillers.slice(2)]);
    // поток аватара и звук приветствия — параллельно; ждём не дольше 6 с, иначе говорим запасным голосом
    await Promise.race([Promise.all([this.waitAvatar(6000), greet]), sleep(6500)]);
    if (!this.alive(ep)) return;
    if (track) { void this.runTour(track, stepIndex, ep, { bridge: true }); return; }
    const mic = this.listener?.getState() ?? "error";
    if (mic === "denied" || mic === "nodevice" || mic === "error") {
      this.set({ phase: "greeting" });
      if ((await this.sayText(sc.phrases.nomic, ep)) !== "done") return;
      void this.runTour("all", 0, ep, { bridge: true });
      return;
    }
    this.set({ phase: "greeting" });
    const r = await this.sayText(sc.greeting, ep);
    if (r !== "done" || !this.alive(ep)) return;
    this.remember("elena", sc.greeting);
    this.set({ phase: "listening" });
    // разрешение на микрофон ещё не дано — ждём решения (до 10 с), потом решаем, слушать или вести самой
    const st = await Promise.race([this.micKnown ?? Promise.resolve<MicState>("error"), sleep(10000).then(() => "connecting" as MicState)]);
    if (!this.alive(ep)) return;
    if (st !== "on" && st !== "muted") {
      if ((await this.sayText(sc.nudge, ep)) !== "done") return;
      void this.runTour("all", 0, ep, { bridge: true });
      return;
    }
    this.armIdle(ep, IDLE_AFTER_GREETING_MS, async () => {
      if ((await this.sayText(sc.nudge, ep)) !== "done") return;
      void this.runTour("all", 0, ep, { bridge: true });
    });
  }

  close() {
    if (this.closed) return;
    this.ep++;
    this.clearAll();
    this.turnCtl?.abort();
    this.voice.close();
    this.listener?.stop();
    window.clearInterval(this.speakTick);
    this.set({ phase: "idle", target: null, click: null, stepNo: 0, speaking: false });
    this.closed = true;
    this.d.onClose();
  }

  toggleMute() {
    if (!this.listener) return;
    this.listener.setMuted(!this.listener.isMuted());
    this.set({ mic: this.listener.getState() });
  }

  /** Кнопка паузы: остановить обзор / продолжить с того же места. */
  togglePause() {
    if (this.paused) {
      this.paused = false;
      const from = this.heard < REPEAT_IF_HEARD_LESS ? this.idx : this.idx + 1;
      const ep = ++this.ep;
      void this.resumeTour(from, ep);
      return;
    }
    if (!this.touring && !this.resumePending) return;
    this.heard = this.stepUtter ? this.stepUtter.progress() : 1;
    this.ep++;
    this.clearAll();
    this.turnCtl?.abort();
    this.voice.stop();
    this.touring = false;
    this.resumePending = false;
    this.paused = true;
    this.set({ phase: "paused", click: null });
  }

  // ------------------------------------------------------------------ таймеры

  private clearAll() {
    for (const t of [this.endTimer, this.staleTimer, this.idleTimer, this.resumeTimer, this.duckTimer, this.clickTimer]) window.clearTimeout(t);
    this.endTimer = this.staleTimer = this.idleTimer = this.resumeTimer = this.duckTimer = this.clickTimer = 0;
  }

  private armIdle(ep: number, ms: number, fn: () => void) {
    window.clearTimeout(this.idleTimer);
    this.idleTimer = window.setTimeout(() => {
      this.idleTimer = 0;
      if (!this.alive(ep) || this.buf.read() || this.voice.speaking() || this.turnCtl) return;
      fn();
    }, ms);
  }

  private clearIdle() { window.clearTimeout(this.idleTimer); this.idleTimer = 0; window.clearTimeout(this.resumeTimer); this.resumeTimer = 0; }

  // ------------------------------------------------------------------ распознавание: ход собеседника

  private onStt(e: SttEvent) {
    if (this.closed) return;
    if (e.type === "ready" || e.type === "speech_started") return;
    if (e.type === "error") { this.set({ mic: "error" }); return; }
    if (e.type === "interim" || e.type === "final") {
      const text = e.text.trim();
      if (!text) return;
      const her = this.voice.echoText();
      if (this.voice.speaking()) {
        const heard = (this.buf.read() + " " + text).trim();
        if (!bargeIn(heard, her, this.voice.sinceStart(), 2)) {
          // похоже на начало реплики — приглушаем голос, пока не станет ясно (эхо и «угу» не приглушают)
          if (!isEcho(heard, her) && !isBackchannel(heard)) this.duckFor(1200);
          return;
        }
        this.interruptForUser();
      } else if (her && isEcho(text, her)) {
        return;                                   // хвост её реплики из динамиков
      }
      this.clearIdle();
      if (this.turnCtl && !this.replyStarted) {   // человек продолжил мысль, пока Елена ещё не ответила, — склеиваем
        this.turnCtl.abort();
        this.turnCtl = null;
        this.carry = (this.carry + " " + this.pendingText).trim();
        this.pendingText = "";
      }
      if (this.buf.accept(e)) {
        if (!this.ui.userTalking) this.set({ userTalking: true });
        window.clearTimeout(this.endTimer);
        this.endTimer = 0;
        this.armStale();
      }
      if (e.type === "final" && e.speech_final) this.armEnd(false);
      return;
    }
    if (e.type === "speech_final_empty" || e.type === "utterance_end") {
      if (this.buf.read()) this.armEnd(e.type === "utterance_end");
    }
  }

  private duckFor(ms: number) {
    this.voice.duck(true);
    window.clearTimeout(this.duckTimer);
    this.duckTimer = window.setTimeout(() => this.voice.duck(false), ms);
  }

  /** Человек перебил: голос — сразу стоп, обзор встаёт на паузу до конца его реплики и ответа. */
  private interruptForUser() {
    if (this.touring) {
      this.heard = this.stepUtter ? this.stepUtter.progress() : 1;
      this.resumePending = true;
      this.touring = false;
    }
    window.clearTimeout(this.duckTimer);
    this.voice.duck(false);
    this.voice.stop();
    this.ep++;
    window.clearTimeout(this.clickTimer);
    if (this.turnCtl && !this.replyStarted) {
      this.turnCtl.abort();
      this.turnCtl = null;
      this.carry = (this.carry + " " + this.pendingText).trim();
      this.pendingText = "";
    }
    this.set({ phase: "listening", click: null });
  }

  private armStale() {
    window.clearTimeout(this.staleTimer);
    const v = this.buf.version;
    this.staleTimer = window.setTimeout(() => {
      if (this.buf.version === v && this.buf.read() && !this.endTimer) this.armEnd(true);
    }, STALE_INTERIM_MS);
  }

  private armEnd(force: boolean) {
    const text = this.buf.read();
    if (!text) return;
    window.clearTimeout(this.endTimer);
    const v = this.buf.version;
    const delay = force ? 120 : endDelay(text, "guide");
    this.endTimer = window.setTimeout(() => {
      this.endTimer = 0;
      if (this.buf.version === v) this.submit();
    }, delay);
  }

  private submit() {
    window.clearTimeout(this.staleTimer);
    const said = this.buf.take();
    const text = (this.carry + " " + said).trim();
    this.carry = "";
    this.set({ userTalking: false });
    if (!text) return;
    // «угу», «да» посреди прерванного обзора — просто продолжаем; без вопроса к человеку — не отвечаем
    if (isBackchannel(text) && words(text).length <= 1) {
      if (this.resumePending) { const ep = ++this.ep; this.scheduleResume(ep, 200); return; }
      const asked = /[?]\s*$/.test(this.lastSaid.trim()) || this.lastSaid.includes("весь сайт");
      if (!asked) { this.set({ phase: this.paused ? "paused" : "listening" }); return; }
    }
    void this.runTurn(text);
  }

  private remember(who: "elena" | "user", text: string) {
    if (!text) return;
    this.history.push({ who, text });
    if (this.history.length > 12) this.history.splice(0, this.history.length - 12);
  }

  // ------------------------------------------------------------------ ход: сервер решает, Елена отвечает

  private async runTurn(text: string) {
    const ep = ++this.ep;
    this.clearIdle();
    window.clearTimeout(this.clickTimer);
    this.pendingText = text;
    this.replyStarted = false;
    const ctl = new AbortController();
    this.turnCtl = ctl;
    this.set({ phase: "thinking", click: null });
    let filler = 0;
    let utter: Utterance | null = null;
    let meta: Meta | null = null;
    let nav: Promise<boolean> | null = null;
    const stepNow = this.track ? TRACKS[this.track][this.idx] ?? null : null;
    try {
      const token = tokenStore.get();
      const r = await fetch(apiUrl("/interview/concierge/turn"), {
        method: "POST",
        signal: ctl.signal,
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          message: text, user_name: this.userName, role: this.track, current_path: this.d.path(), step_id: stepNow,
          touring: this.touring || this.resumePending, paused: this.paused, history: this.history.slice(-8),
        }),
      });
      for await (const item of ndjson(r)) {
        if (!this.alive(ep)) throw new DOMException("stale", "AbortError");
        if (item.t === "ack") {
          if (item.kind === "llm") filler = window.setTimeout(() => this.playFiller(ep), FILLER_AFTER_MS);
        } else if (item.t === "meta") {
          meta = item as Meta;
          this.remember("user", text);
          this.pendingText = "";
          if (meta.user_name && meta.user_name !== this.userName) {
            this.userName = meta.user_name;
            try { sessionStorage.setItem(NAME_KEY, meta.user_name); } catch { /* ignore */ }
          }
          nav = this.prepare(meta, ep);      // экран начинает открываться, пока Елена говорит ответ
        } else if (item.t === "pcm" && typeof item.b64 === "string") {
          if (!utter) {
            window.clearTimeout(filler);
            this.replyStarted = true;
            utter = this.voice.begin(meta?.text ?? "", RATE);
            this.lastSaid = meta?.text ?? "";
            this.set({ phase: "answering" });
          }
          utter.push(b64bytes(item.b64));
        } else if (item.t === "end") {
          break;
        }
      }
    } catch (e) {
      window.clearTimeout(filler);
      if (this.turnCtl === ctl) this.turnCtl = null;
      if ((e as { name?: string })?.name === "AbortError" || !this.alive(ep)) return;
      // сеть или сервер подвели — короткая просьба повторить, обзор (если шёл) продолжится
      this.remember("user", text);
      this.pendingText = "";
      await this.sayText(this.script?.phrases.sorry ?? "", ep);
      if (this.alive(ep)) this.afterAnswer(ep);
      return;
    }
    window.clearTimeout(filler);
    if (this.turnCtl === ctl) this.turnCtl = null;
    if (!this.alive(ep) || !meta) return;
    if (meta.text) this.remember("elena", meta.text);
    if (utter) {
      const res = await utter.end();
      if (res === "aborted" || !this.alive(ep)) return;
    } else if (meta.text) {
      // голос ответа не пришёл потоком — пробуем обычной загрузкой
      const res = await this.sayText(meta.text, ep);
      if (res === "aborted" || !this.alive(ep)) return;
    }
    await this.act(meta, ep, nav);
  }

  private playFiller(ep: number) {
    if (!this.alive(ep) || this.replyStarted || this.voice.speaking() || !this.script?.fillers.length) return;
    const f = this.script.fillers[Math.floor(Math.random() * Math.min(2, this.script.fillers.length))];
    void this.pcm(f).then((pcm) => {
      if (!pcm || !this.alive(ep) || this.replyStarted) return;
      void this.voice.say(f, pcm, RATE);
    });
  }

  /** По решению сервера — сразу начать переход (вход в роль, открытие экрана), не дожидаясь конца ответа. */
  private prepare(meta: Meta, ep: number): Promise<boolean> | null {
    const target = this.targetOf(meta);
    if (!target) return null;
    this.prefetchStepsOf(target.track, target.index);
    return this.enter(STEPS[TRACKS[target.track][target.index]], ep, null, false);
  }

  private targetOf(meta: Meta): { track: TourTrack; index: number } | null {
    if (meta.action === "start_tour") {
      const role = (meta.role && meta.role in TRACKS ? meta.role : "all") as TourTrack;
      return { track: role, index: 0 };
    }
    if (meta.action === "goto" && meta.step && STEPS[meta.step]) {
      const tr = trackFor(meta.step, this.track);
      return { track: tr, index: Math.max(0, TRACKS[tr].indexOf(meta.step)) };
    }
    return null;
  }

  private prefetchStepsOf(track: TourTrack, index: number) {
    if (!this.script) return;
    this.prefetch(TRACKS[track].slice(index, index + 3).map((id) => this.script!.steps[id]).filter(Boolean));
  }

  private async act(meta: Meta, ep: number, nav: Promise<boolean> | null) {
    const a = meta.action ?? "answer";
    const sc = this.script!;
    if (a === "start_tour" || a === "goto") {
      const t = this.targetOf(meta);
      if (!t) { this.afterAnswer(ep); return; }
      if (nav) await nav;
      if (!this.alive(ep)) return;
      this.paused = false;
      void this.runTour(t.track, t.index, ep, { bridge: false });
      return;
    }
    if (a === "pause") {
      this.paused = true;
      this.resumePending = false;
      this.touring = false;
      this.set({ phase: "paused" });
      return;
    }
    if (a === "resume") {
      // после паузы — с того же места; «дальше» посреди шага — следующий шаг
      const wasPaused = this.paused;
      this.paused = false;
      if (!this.track) { this.startNext(ep); return; }
      const from = wasPaused ? (this.heard < REPEAT_IF_HEARD_LESS ? this.idx : this.idx + 1) : this.idx + 1;
      void this.resumeTour(from, ep);
      return;
    }
    if (a === "repeat") {
      if (this.track && (this.resumePending || this.touring || this.paused)) { this.paused = false; void this.resumeTour(this.idx, ep); return; }
      if (this.lastSaid) await this.sayText(this.lastSaid, ep);
      if (this.alive(ep)) this.afterAnswer(ep);
      return;
    }
    if (a === "prev") {
      if (this.track) { this.paused = false; void this.resumeTour(Math.max(0, this.idx - 1), ep); return; }
      this.afterAnswer(ep);
      return;
    }
    if (a === "end") {
      await sleep(250);
      if (this.alive(ep)) this.close();
      return;
    }
    if (a === "ask_role") {
      this.set({ phase: "listening" });
      this.armIdle(ep, IDLE_AFTER_QUESTION_MS, async () => {
        if ((await this.sayText(sc.nudge, ep)) !== "done") return;
        void this.runTour("all", 0, ep, { bridge: true });
      });
      return;
    }
    this.afterAnswer(ep);
  }

  /** После ответа на вопрос: прерванный обзор продолжается сам, если человек молчит. */
  private afterAnswer(ep: number) {
    if (this.resumePending && !this.paused) { this.scheduleResume(ep, RESUME_AFTER_ANSWER_MS); return; }
    this.set({ phase: this.paused ? "paused" : "listening" });
    if (!this.paused && !this.track && !this.lastTrack && this.script) {
      const sc = this.script;
      this.armIdle(ep, IDLE_AFTER_QUESTION_MS, async () => {
        if ((await this.sayText(sc.nudge, ep)) !== "done") return;
        void this.runTour("all", 0, ep, { bridge: true });
      });
    }
  }

  /** «Дальше», когда обзор роли уже закончен: следующая сторона платформы. */
  private startNext(ep: number) {
    const last = this.lastTrack;
    if (last === "candidate") void this.runTour("employer", 0, ep, { bridge: true });
    else if (last === "employer") void this.runTour("fsp", 0, ep, { bridge: true });
    else if (last === "fsp") void this.runTour("all", TRACKS.all.indexOf("val-arena"), ep, { bridge: true });
    else if (!last) void this.runTour("all", 0, ep, { bridge: true });
    else this.set({ phase: "listening" });
  }

  private scheduleResume(ep: number, ms: number) {
    this.set({ phase: "listening" });
    window.clearTimeout(this.resumeTimer);
    this.resumeTimer = window.setTimeout(() => {
      this.resumeTimer = 0;
      if (!this.alive(ep) || this.buf.read() || this.voice.speaking() || this.turnCtl || this.paused) return;
      const from = this.heard < REPEAT_IF_HEARD_LESS ? this.idx : this.idx + 1;
      void this.resumeTour(from, ep);
    }, ms);
  }

  private async resumeTour(from: number, ep: number) {
    if (!this.track) { void this.runTour("all", 0, ep, { bridge: true }); return; }
    this.resumePending = false;
    void this.runTour(this.track, from, ep, { bridge: true });
  }

  // ------------------------------------------------------------------ обзор

  private needLogin(step: TourStep): boolean {
    if (!step.persona) return false;
    const role = this.d.me()?.role;
    const want = step.persona === "fsp" ? "fsp_analyst" : step.persona === "employer" ? "employer" : step.persona === "expert" ? "expert" : "candidate";
    return role !== want;
  }

  private onScreen(step: TourStep): boolean {
    if (this.needLogin(step)) return false;
    const p = this.d.path();
    return step.match ? step.match.test(p) : p === step.path || p === step.path + "/";
  }

  private async waitEl(selector: string, ep: number, ms: number): Promise<HTMLElement | null> {
    const t0 = performance.now();
    for (;;) {
      if (!this.alive(ep)) return null;
      const el = findTarget(selector);
      if (el) return el;
      if (performance.now() - t0 > ms) return null;
      await sleep(90);
    }
  }

  /** Открыть экран шага: вход в нужную роль, переход, ожидание нужного блока; связка звучит, пока экран грузится. */
  private async enter(step: TourStep, ep: number, bridge: string | null, scroll = true): Promise<boolean> {
    const bridgeDone = bridge ? this.sayText(bridge, ep) : Promise.resolve<SayResult>("done");
    if (!this.onScreen(step)) {
      try {
        if (this.needLogin(step)) {
          const dest = await this.d.login(step.persona!, step.path);
          if (!this.alive(ep)) return false;
          this.d.navigate(dest);
          if (step.resolve && dest === step.path) {
            const p = await step.resolve();
            if (!this.alive(ep)) return false;
            if (p && !(step.match?.test(this.d.path()))) this.d.navigate(p);
          }
        } else {
          const p = step.resolve ? ((await step.resolve()) ?? step.path) : step.path;
          if (!this.alive(ep)) return false;
          this.d.navigate(p);
        }
      } catch {
        if (!this.alive(ep)) return false;
        this.d.navigate(step.path);
      }
    }
    const el = await this.waitEl(step.selector, ep, 7000);
    const b = await bridgeDone;
    if (!this.alive(ep) || b === "aborted") return false;
    if (!el) return false;
    if (scroll) {
      const r = el.getBoundingClientRect();
      const fits = r.top >= 72 && r.bottom <= window.innerHeight - 24;
      if (!fits) {
        const top = r.height > window.innerHeight * 0.6 ? r.top - 88 : r.top - (window.innerHeight - r.height) / 2;
        window.scrollTo({ top: Math.max(0, window.scrollY + top), behavior: "smooth" });
        await sleep(380);
      }
    }
    return true;
  }

  private planClick(step: TourStep, u: Utterance, totalMs: number, ep: number) {
    window.clearTimeout(this.clickTimer);
    if (!step.click) { this.set({ click: null }); return; }
    const lead = this.d.avatar()?.live() ? PIPE_MS : 80;
    const at = performance.now() + lead + Math.max(1200, totalMs) * (step.clickAt ?? 0.5);
    this.set({ click: { selector: step.click, at } });
    this.clickTimer = window.setTimeout(() => {
      this.clickTimer = 0;
      if (!this.alive(ep) || this.stepUtter !== u) return;
      const el = findTarget(step.click!);
      if (el) { try { el.click(); } catch { /* блок пропал */ } }
    }, Math.max(0, at - performance.now()));
  }

  private async runTour(track: TourTrack, from: number, ep: number, opts: { bridge: boolean }) {
    const sc = this.script;
    if (!sc || !this.alive(ep)) return;
    const ids = TRACKS[track];
    this.track = track;
    this.paused = false;
    this.resumePending = false;
    this.touring = true;
    let prevCab: string | null = opts.bridge ? this.lastCabinet : STEPS[ids[from]]?.cabinet ?? null;
    for (let i = Math.max(0, from); i < ids.length; i++) {
      if (!this.alive(ep)) return;
      this.idx = i;
      this.heard = 0;
      const step = STEPS[ids[i]];
      this.prefetchSteps(i);
      this.set({ phase: "touring", track, stepNo: i + 1, stepTotal: ids.length });
      const bridge = prevCab !== step.cabinet ? sc.bridges[step.cabinet] ?? null : null;
      const ok = await this.enter(step, ep, bridge);
      if (!this.alive(ep)) return;
      prevCab = step.cabinet;
      this.lastCabinet = step.cabinet;
      if (!ok) continue;
      this.set({ target: step.selector, click: null });
      const text = sc.steps[step.id];
      const res = await this.sayText(text, ep, (u, total) => { this.stepUtter = u; this.planClick(step, u, total, ep); });
      this.stepUtter = null;
      if (res === "aborted" || !this.alive(ep)) return;
      this.heard = 1;
      await sleep(200);
    }
    if (!this.alive(ep)) return;
    this.touring = false;
    this.idx = ids.length - 1;
    this.set({ phase: "listening", target: null, click: null, stepNo: 0 });
    const done = sc.phrases[`done_${track}`] ?? sc.phrases.done_all;
    await this.sayText(done, ep);
    if (this.alive(ep)) { this.remember("elena", done); this.track = null; this.lastTrack = track; this.set({ phase: "listening", track: null }); }
  }
}
