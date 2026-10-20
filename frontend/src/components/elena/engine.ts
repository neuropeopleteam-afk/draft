// Елена — живой проводник «как по видеосвязи». Один микрофон на весь разговор (LiveListener), голос — в видеопоток
// аватара (Voice), решения по ходу разговора — сервер (/api/interview/concierge/turn, поток NDJSON: сильная модель
// с базой знаний, памятью разговора и фоновым наставником), постоянные фразы и реплики обзора — из кэша, заранее
// загруженные в память (переходы без пауз).
//
// Правила разговора:
//  • знакомство: спрашивает, как обращаться, запоминает имя (и в следующий визит здоровается по имени; имя с прошлого
//    визита сервер проверяет — служебное слово вроде «Сразу» не имя);
//  • Елену не перебивают: фразу она всегда договаривает; сказанное поверх неё слышит и отвечает, договорив (эхо и
//    «угу» — не реплики); обзор при этом дальше не идёт;
//  • она не перебивает человека: конец хода — только после паузы (длиннее для незаконченной мысли, короче для команд),
//    пока человек говорит — новую реплику не начинает;
//  • спросила — ждёт ответа и сама дальше не идёт (одно короткое напоминание через 25 с, потом просто ждёт);
//  • между разделами обзора (кандидат → работодатель → Федерация → жюри) спрашивает, есть ли вопросы, и ждёт;
//    после ответа на вопрос посреди обзора спрашивает «Продолжаем?»; «пропусти» — к следующему разделу;
//  • модель думает дольше 0,45 с — короткая связка («Секунду.»), ответ встаёт сразу за ней;
//  • обзор: шаг = экран, на каждую короткую реплику — свой блок (подсветка, прокрутка, «нажатие» в нужный момент);
//  • «покажи …» посреди обзора — экран дальше по обзору: идём вперёд с него; другой экран — показать и спросить,
//    вернуться ли к обзору;
//  • каждая встреча пишется в стенограмму на сервере (реплики, шаги, решения).
import { apiUrl, tokenStore, type MeOut } from "../../lib/api";
import type { Persona } from "../../lib/jury";
import type { AnamHandle } from "../voice/AnamAvatar";
import { LiveListener, liveSttSupported, type MicState, type SttEvent } from "../voice/live/listener";
import { SpeechBuffer, isBackchannel, isEcho, words } from "../voice/live/turns";
import { Voice, type SayResult, type Utterance } from "../voice/live/voice";
import { fetchPhrasePcm } from "../voice/live/decode";
import { STEPS, TRACKS, type Beat, type Cabinet, type TourStep, type TourTrack } from "./steps";

export type Phase = "idle" | "connecting" | "greeting" | "listening" | "thinking" | "answering" | "touring" | "paused";
export type Stage = "large" | "corner";

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
  /** Окно: большое по центру (знакомство) или в углу (обзор). */
  stage: Stage;
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

interface Bridge { first?: string; first_named?: string; next?: string }

interface Script {
  name_ok?: string | null;
  greeting: string;
  greeting_back?: string;
  nudge: string;
  nudge_role?: string;
  bridges: Record<string, Bridge | string>;
  phrases: Record<string, string>;
  phrases_named?: Record<string, string>;
  fillers: string[];
  beats?: Record<string, string[]>;
  steps: Record<string, string>;
}

interface Meta {
  action?: string;
  role?: string | null;
  step?: string | null;
  point?: string | null;
  user_name?: string | null;
  text?: string;
  kind?: string;
}

interface Pos { ids: string[]; track: TourTrack | null; i: number; b: number }

const RATE = 24000;
const BYTES_PER_MS = (RATE * 2) / 1000;
const PIPE_MS = 650;               // звук из видеопотока звучит примерно через столько после отправки
const REMIND_AFTER_MS = 25000;     // спросила и ждёт: одно короткое напоминание, потом просто ждёт
const FILLER_AFTER_MS = 450;
const STALE_INTERIM_MS = 2600;     // промежуточный текст не меняется — считаем фразу законченной
const LOOKAHEAD_MS = 4500;         // звук в видеопоток — с запасом: подвисание страницы при переходе не рвёт фразу
const REPEAT_IF_HEARD_LESS = 0.6;
const BEAT_GAP_MS = 420;           // пауза между репликами обзора — спокойный темп без «провалов»
const POINT_HOLD_MS = 6000;
const NAME_KEY = "draft.elena.name";
const OLD_NAME_KEY = "draft.concierge.name";

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

type Awaiting = "start" | "checkin" | "continue" | "detour" | "answer" | null;

// Конец хода собеседника: сколько ждать тишины после окончательного сегмента распознавания (поставщик уже выждал
// ~0,7 с). Незаконченная мысль («и», «а можно», «потому что») — долго; короткая команда — быстро.
const UNFINISHED_END = /(?:^|\s)(и|а|но|или|что|чтобы|потому|поэтому|если|когда|как|это|ну|вот|например|то есть|типа|в|на|с|по|для|из|от|к|у|о|об|про|за|который|которая|которые|можно|мне|я|так|значит|подожди|подождите|слушай|смотри|э+|м+)$/u;
const COMMAND = /^(стоп|стой|дальше|да|нет|неа|пауза|назад|повтори|повторите|давай|давайте|продолжай|продолжаем|продолжим|поехали|хорошо|ага|угу|нету|нет вопросов|вопросов нет|да давай|давай дальше|нет дальше|пропусти|пропустим|спасибо|понятно|ясно)$/u;

export function guideDelay(text: string): number {
  const w = words(text);
  const t = w.join(" ");
  if (!w.length) return 900;
  if (UNFINISHED_END.test(t)) return 2400;
  if (w.length <= 3 && COMMAND.test(t)) return 350;
  if (/[?]\s*$/.test(text.trim())) return 700;
  if (w.length <= 3) return 950;
  return 1150;
}

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

const norm = (t: string | null | undefined) => (t ?? "").replace(/\s+/g, " ").trim();

/** Кнопка, ссылка, вкладка или заголовок с такой надписью (точное совпадение, потом начало, потом вхождение). */
function byText(label: string): HTMLElement | null {
  const want = norm(label).toLowerCase().replace(/[«»"]/g, "");
  if (!want) return null;
  const root = document.querySelector("main") ?? document.body;
  const all = Array.from(root.querySelectorAll<HTMLElement>("button, a[href], [role='tab'], h1, h2, h3, label, summary"))
    .filter(visible);
  const text = (el: HTMLElement) => norm(el.textContent).toLowerCase().replace(/[«»"]/g, "");
  return all.find((el) => text(el) === want) ?? all.find((el) => text(el).startsWith(want))
    ?? all.find((el) => want.length >= 4 && text(el).includes(want)) ?? null;
}

/** Первый видимый элемент из списка селекторов через запятую (по порядку списка); «text:Надпись» — по надписи. */
export function findTarget(selector: string): HTMLElement | null {
  for (const part of selector.split(",").map((s) => s.trim()).filter(Boolean)) {
    if (part.startsWith("text:")) {
      const el = byText(part.slice(5));
      if (el) return el;
      continue;
    }
    try {
      for (const el of Array.from(document.querySelectorAll(part))) if (visible(el)) return el as HTMLElement;
    } catch { /* неверный селектор — следующий */ }
  }
  return null;
}

/** Высота закреплённой шапки страницы (блок не должен прятаться под ней). */
export function topInset(): number {
  let inset = 0;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("header, nav, [class*='sticky'], [class*='fixed']"))) {
    if (el.closest("[data-testid=interactive-avatar-tour]")) continue;
    const cs = getComputedStyle(el);
    if (cs.position !== "sticky" && cs.position !== "fixed") continue;
    const r = el.getBoundingClientRect();
    if (r.top <= 4 && r.bottom > 0 && r.height < window.innerHeight * 0.4 && r.width > window.innerWidth * 0.4) inset = Math.max(inset, r.bottom);
  }
  return Math.round(inset || 64);
}

/** Что сейчас на экране — заголовок и видимые надписи (Елена отвечает «по экрану» и может показать элемент). */
function screenSnapshot(): { title: string; items: string[] } {
  const root = document.querySelector("main") ?? document.body;
  const title = norm(root.querySelector("h1")?.textContent) || document.title;
  const items: string[] = [];
  for (const el of Array.from(root.querySelectorAll<HTMLElement>("h2, h3, button, a[href], [role='tab']"))) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.bottom < 0 || r.top > window.innerHeight) continue;
    const t = norm(el.textContent);
    if (t && t.length <= 60 && !items.includes(t)) items.push(t);
    if (items.length >= 30) break;
  }
  return { title, items };
}

function newSid(): string {
  try {
    const u = crypto.randomUUID?.();
    if (u) return u;
  } catch { /* старый браузер */ }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
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
  readonly sid = newSid();
  private listener: LiveListener | null = null;
  private script: Script | null = null;
  private cache = new Map<string, Promise<Uint8Array | null>>();
  private queue: string[] = [];
  private loading = 0;
  private ui: ElenaUi = {
    phase: "idle", mic: "off", speaking: false, userTalking: false, track: null, stepNo: 0, stepTotal: 0,
    target: null, click: null, canPause: false, stage: "corner",
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
  private clickTimer = 0;
  private pointTimer = 0;
  private speakTick = 0;
  private history: { who: "elena" | "user"; text: string }[] = [];
  private userName: string | null = null;
  // обзор
  private pos: Pos | null = null;       // где обзор сейчас (шаг и реплика)
  private touring = false;              // идёт обзор (реплика или переход к ней)
  private paused = false;               // пауза по просьбе человека
  private resumePending = false;        // обзор прерван вопросом — продолжить после ответа
  private detour: Pos | null = null;    // «покажи …» посреди обзора — куда вернуться
  private heard = 1;                    // какая доля прерванной реплики прозвучала
  private stepUtter: Utterance | null = null;
  private lastCabinet: Cabinet | null = null;
  private lastTrack: TourTrack | null = null;
  private lastSaid = "";
  private lastFiller = "";
  private micKnown: Promise<MicState> | null = null;
  private lastMicLogged: MicState | null = null;
  private viewSeq = 0;
  private submitWait = 0;               // реплика человека ждёт, пока Елена договорит фразу
  private replyBusy = false;            // ответ прозвучал, но его действие (обзор, переход) ещё не началось
  private shownSteps = new Set<string>();
  private lastAsked = false;            // ответ закончился вопросом — Елена ждёт ответа
  private awaiting: Awaiting = null;    // чего ждёт после своей реплики (уходит на сервер вместе с ходом)
  private reminded = false;             // напоминание в этом ожидании уже звучало
  private noMic = false;                // микрофона нет — ведёт сама, без вопросов между разделами

  constructor(private d: ElenaDeps) {
    this.voice = new Voice(d.avatar, { lookaheadMs: LOOKAHEAD_MS });
    try {
      this.userName = localStorage.getItem(NAME_KEY) || sessionStorage.getItem(OLD_NAME_KEY) || null;
    } catch { this.userName = null; }
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
  /** Кнопка «развернуть / в угол». */
  setStage(stage: Stage) { this.set({ stage }); }

  /** Индикатор «Елена говорит» — по фактическому звуку (видеопоток или запасной голос). */
  private watchSpeaking() {
    window.clearInterval(this.speakTick);
    this.speakTick = window.setInterval(() => {
      const s = this.voice.speaking();
      if (s !== this.ui.speaking) this.set({ speaking: s });
    }, 150);
  }

  // ------------------------------------------------------------------ стенограмма

  private post(type: "open" | "say" | "step" | "close" | "mic" | "point", extra: { text?: string; step?: string | null } = {}) {
    const body = JSON.stringify({
      session_id: this.sid, type, text: (extra.text ?? "").slice(0, 1200), step: extra.step ?? null,
      path: this.d.path().slice(0, 200), name: this.userName, role: this.pos?.track ?? null,
    });
    const url = apiUrl("/interview/concierge/event");
    try {
      if (type === "close" && navigator.sendBeacon) {
        navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
        return;
      }
      void fetch(url, { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body }).catch(() => undefined);
    } catch { /* стенограмма не важнее разговора */ }
  }

  private setName(name: string) {
    if (!name || name === this.userName) return;
    this.userName = name;
    try { localStorage.setItem(NAME_KEY, name); } catch { /* ignore */ }
  }

  private named(text: string | undefined): string {
    return (text ?? "").replace("{name}", this.userName ?? "").trim();
  }

  // ------------------------------------------------------------------ голос

  /** Звук фразы: из памяти, иначе загрузка (сразу, вне очереди предзагрузки; low — фоновая предзагрузка). */
  private pcm(text: string, low = false): Promise<Uint8Array | null> {
    let p = this.cache.get(text);
    if (!p) {
      p = fetchPhrasePcm(apiUrl("/interview/concierge/speech"), text, low);
      this.cache.set(text, p);
      void p.then((v) => { if (!v) this.cache.delete(text); });
    }
    return p;
  }

  /** Предзагрузка по три фразы одновременно (сервер не перегружается на холодном кэше). */
  private prefetch(texts: (string | undefined | null)[]) {
    for (const t of texts) if (t && !this.cache.has(t) && !this.queue.includes(t)) this.queue.push(t);
    const next = () => {
      while (this.loading < 3 && this.queue.length && !this.closed) {
        const t = this.queue.shift()!;
        if (this.cache.has(t)) continue;
        this.loading++;
        void this.pcm(t, true).finally(() => { this.loading--; next(); });
      }
    };
    next();
  }

  private linesOf(stepId: string): string[] {
    const sc = this.script;
    if (!sc) return [];
    const b = sc.beats?.[stepId];
    if (b && b.length) return b;
    const one = sc.steps[stepId];
    return one ? [one] : [];
  }

  private prefetchFrom(ids: string[], i: number) {
    const out: string[] = [];
    for (const id of ids.slice(i, i + 2)) out.push(...this.linesOf(id));
    this.prefetch(out);
  }

  private alive(ep: number) { return !this.closed && ep === this.ep; }

  /** Сказать фразу (из памяти). Нет звука — пауза на время чтения, чтобы экран не «пролетал». log — в стенограмму. */
  private async sayText(text: string, ep: number, onStart?: (u: Utterance, totalMs: number) => void, log = true): Promise<SayResult> {
    if (!text) return "done";
    const pcm = await this.pcm(text);
    if (!this.alive(ep)) return "aborted";
    this.lastSaid = text;
    if (log) this.post("say", { text, step: this.pos ? this.pos.ids[this.pos.i] : null });
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
        path: "/api/interview/live/stt?p=guide",
        onEvent: (e) => this.onStt(e),
        onState: (s) => {
          this.set({ mic: s });
          if ((s === "on" || s === "denied" || s === "nodevice" || s === "error") && s !== this.lastMicLogged) {
            this.lastMicLogged = s;
            this.post("mic", { text: s });
          }
        },
      });
      this.micKnown = this.listener.start();
    } else {
      this.set({ mic: "error" });
      this.micKnown = Promise.resolve<MicState>("error");
    }
    this.post("open");
    void this.boot(track, stepIndex);
  }

  private async loadScript(): Promise<Script | null> {
    for (let i = 0; i < 2; i++) {
      try {
        const ctl = new AbortController();
        const t = window.setTimeout(() => ctl.abort(), 5000);
        const q = this.userName ? `?name=${encodeURIComponent(this.userName.slice(0, 40))}` : "";
        const r = await fetch(apiUrl(`/interview/concierge/script${q}`), { signal: ctl.signal });
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

  private greetingText(sc: Script): string {
    if (this.userName && sc.greeting_back) return this.named(sc.greeting_back);
    return sc.greeting;
  }

  private bridgeText(cab: Cabinet, first: boolean, withName: boolean): string | null {
    const b = this.script?.bridges[cab];
    if (!b) return null;
    if (typeof b === "string") return first ? null : b;
    if (first) return (withName && this.userName && b.first_named ? this.named(b.first_named) : b.first) || null;
    return b.next || null;
  }

  private phrase(key: string): string {
    const sc = this.script;
    if (!sc) return "";
    const n = sc.phrases_named?.[key];
    return n && this.userName ? this.named(n) : sc.phrases[key] ?? "";
  }

  private async boot(track?: TourTrack, stepIndex = 0) {
    const ep = ++this.ep;
    this.set({ phase: "connecting" });
    this.d.avatar()?.connect();
    const sc = await this.loadScript();
    if (!this.alive(ep)) return;
    if (!sc) { this.close(); return; }
    this.script = sc;
    if (this.userName && sc.name_ok !== undefined && sc.name_ok !== this.userName) {
      // имя с прошлого визита не похоже на имя («Сразу») — знакомимся заново; похоже — в правильной форме
      this.userName = sc.name_ok || null;
      try {
        if (this.userName) localStorage.setItem(NAME_KEY, this.userName);
        else { localStorage.removeItem(NAME_KEY); sessionStorage.removeItem(OLD_NAME_KEY); }
      } catch { /* ignore */ }
    }
    const greetText = this.greetingText(sc);
    const greet = track ? Promise.resolve(null) : this.pcm(greetText);
    const firstIds = TRACKS[track ?? "all"];
    // остальное — в фоне после приветствия: на медленной связи приветствие не делит канал с предзагрузкой
    const rest = [sc.nudge, sc.nudge_role, ...sc.fillers.slice(0, 3), ...this.linesOf(firstIds[stepIndex] ?? ""),
      this.bridgeText("candidate", true, false), sc.phrases.ask_role, sc.phrases.pause, sc.phrases.goto,
      sc.phrases.continue, sc.phrases.listen, sc.phrases.checkin_candidate, sc.phrases.continue_employer,
      ...this.linesOf(firstIds[stepIndex + 1] ?? ""), ...sc.fillers.slice(3), sc.phrases.nomic, sc.phrases.back_to_tour,
      sc.phrases.remind_start, sc.phrases.no_more];
    void Promise.race([greet, sleep(2500)]).then(() => { if (!this.closed) this.prefetch(rest); });
    // поток аватара и звук приветствия — параллельно; ждём не дольше 6 с, иначе говорим запасным голосом
    await Promise.race([Promise.all([this.waitAvatar(6000), greet]), sleep(6500)]);
    if (!this.alive(ep)) return;
    if (track) { void this.runTour(track, stepIndex, 0, ep, { bridge: true, named: true }); return; }
    const mic = this.listener?.getState() ?? "error";
    if (mic === "denied" || mic === "nodevice" || mic === "error") {
      this.noMic = true;
      this.set({ phase: "greeting" });
      if ((await this.sayText(sc.phrases.nomic, ep)) !== "done") return;
      void this.runTour("all", 0, 0, ep, { bridge: true, named: true });
      return;
    }
    this.set({ phase: "greeting" });
    const r = await this.sayText(greetText, ep);
    if (r !== "done" || !this.alive(ep)) return;
    this.remember("elena", greetText);
    this.set({ phase: "listening" });
    // разрешение на микрофон ещё не дано — ждём решения (до 10 с), потом решаем, слушать или вести самой
    const st = await Promise.race([this.micKnown ?? Promise.resolve<MicState>("error"), sleep(10000).then(() => "connecting" as MicState)]);
    if (!this.alive(ep)) return;
    const nudge = this.userName ? (sc.nudge_role ?? sc.nudge) : sc.nudge;
    if (st !== "on" && st !== "muted") {
      this.noMic = true;
      if ((await this.sayText(nudge, ep)) !== "done") return;
      void this.runTour("all", 0, 0, ep, { bridge: true, named: true });
      return;
    }
    // спросила (имя или что показать) — ждёт ответа; сама обзор не начинает
    this.waitFor("start", ep, "remind_start");
  }

  close() {
    if (this.closed) return;
    this.post("close");
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
      const ep = ++this.ep;
      void this.resumeTour(ep);
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
    for (const t of [this.endTimer, this.staleTimer, this.idleTimer, this.resumeTimer, this.clickTimer, this.pointTimer]) window.clearTimeout(t);
    window.clearInterval(this.submitWait);
    this.endTimer = this.staleTimer = this.idleTimer = this.resumeTimer = this.clickTimer = this.pointTimer = this.submitWait = 0;
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

  /** Елена спросила и ждёт ответа: сама дальше не идёт; одно короткое напоминание, если человек долго молчит. */
  private waitFor(kind: Awaiting, ep: number, remindKey: string | null) {
    this.awaiting = kind;
    this.reminded = false;
    this.set({ phase: this.paused ? "paused" : "listening", click: null });
    if (!remindKey || this.noMic) return;
    this.armIdle(ep, REMIND_AFTER_MS, () => {
      if (this.reminded || this.userBusy()) return;
      this.reminded = true;
      const t = this.phrase(remindKey);
      if (t) void this.sayText(t, ep);
    });
  }

  // ------------------------------------------------------------------ распознавание: ход собеседника

  private onStt(e: SttEvent) {
    if (this.closed) return;
    if (e.type === "ready") return;
    if (e.type === "speech_started") {
      // человек снова заговорил, пока ждём конца хода, — подождать ещё (Елену при этом не перебивают и не приглушают)
      if (this.endTimer && !this.voice.speaking() && this.buf.read()) this.armEnd(false, 900);
      return;
    }
    if (e.type === "error") { this.set({ mic: "error" }); return; }
    if (e.type === "interim" || e.type === "final") {
      const text = e.text.trim();
      if (!text) return;
      const her = this.voice.echoText();
      if (her && isEcho(text, her)) return;       // её голос из динамиков
      if (this.voice.speaking() && !this.buf.read() && isBackchannel(text)) return;   // «угу», «ага» поверх её фразы
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
      if (e.type === "final") this.armEnd(false, e.speech_final ? 0 : 700);
      return;
    }
    if (e.type === "speech_final_empty" || e.type === "utterance_end") {
      // тишина уже выждана поставщиком — конец хода, но незаконченную мысль всё равно даём договорить
      if (this.buf.read()) this.armEnd(false, e.type === "utterance_end" ? -1200 : 0);
    }
  }

  /** Человек что-то сказал или ждёт ответа — обзор дальше не идёт. */
  private userBusy(): boolean {
    return !!this.buf.read() || this.ui.userTalking || !!this.submitWait || !!this.turnCtl || !!this.carry;
  }

  /** Обзор встаёт и ждёт: реплика человека будет обработана, потом обзор продолжится со следующей реплики. */
  private holdForUser(heard = 1) {
    this.touring = false;
    this.resumePending = true;
    this.heard = heard;
    this.set({ phase: "listening", click: null });
  }

  private armStale() {
    window.clearTimeout(this.staleTimer);
    const v = this.buf.version;
    this.staleTimer = window.setTimeout(() => {
      if (this.buf.version === v && this.buf.read() && !this.endTimer) this.armEnd(false, -600);
    }, STALE_INTERIM_MS);
  }

  private armEnd(force: boolean, extra = 0) {
    const text = this.buf.read();
    if (!text) return;
    window.clearTimeout(this.endTimer);
    const v = this.buf.version;
    const delay = force ? 120 : Math.max(250, guideDelay(text) + extra);
    this.endTimer = window.setTimeout(() => {
      this.endTimer = 0;
      if (this.buf.version === v) this.submit();
    }, delay);
  }

  private submit() {
    // Елена договаривает фразу — реплика ждёт её конца (её не перебивают), потом сразу ответ
    if (this.voice.speaking()) {
      if (!this.submitWait) {
        let quiet = 0;   // два тихих такта подряд: Елена договорила, следующий шаг (обзор, переход) уже начался
        this.submitWait = window.setInterval(() => {
          if (this.closed) return;
          if (this.voice.speaking() || this.replyBusy) { quiet = 0; return; }
          if (++quiet < 2) return;
          window.clearInterval(this.submitWait);
          this.submitWait = 0;
          if (this.touring) this.holdForUser(this.stepUtter ? this.stepUtter.progress() : this.heard);
          this.submit();
        }, 120);
      }
      return;
    }
    window.clearTimeout(this.staleTimer);
    const said = this.buf.take();
    const text = (this.carry + " " + said).trim();
    this.carry = "";
    this.set({ userTalking: false });
    if (!text) return;
    // «угу» посреди обзора, когда Елена ни о чём не спрашивала, — не реплика: обзор продолжается; на вопрос
    // («Есть вопросы?», «Продолжаем?») любой ответ решает сервер
    if (isBackchannel(text) && words(text).length <= 1 && !this.awaiting) {
      if (this.resumePending) { const ep = ++this.ep; this.scheduleResume(ep, 200); return; }
      const asked = /[?]\s*$/.test(this.lastSaid.trim());
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

  private stepNow(): string | null {
    return this.pos ? this.pos.ids[this.pos.i] ?? null : null;
  }

  private async runTurn(text: string) {
    const ep = ++this.ep;
    this.clearIdle();
    window.clearTimeout(this.clickTimer);
    this.pendingText = text;
    this.replyStarted = false;
    const ctl = new AbortController();
    this.turnCtl = ctl;
    // ответ сервера завис (связь) — не ждём вечно: через 10 с без решения — короткая просьба повторить
    let timedOut = false;
    const killer = window.setTimeout(() => { timedOut = true; ctl.abort(); }, 10000);
    this.set({ phase: "thinking", click: null });
    let filler = 0;
    let utter: Utterance | null = null;
    let meta: Meta | null = null;
    let nav: Promise<boolean> | null = null;
    try {
      const token = tokenStore.get();
      const r = await fetch(apiUrl("/interview/concierge/turn"), {
        method: "POST",
        signal: ctl.signal,
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          message: text, user_name: this.userName, role: this.pos?.track ?? this.lastTrack, current_path: this.d.path(),
          step_id: this.stepNow(), touring: this.touring || this.resumePending, paused: this.paused,
          history: this.history.slice(-8), session_id: this.sid, screen: screenSnapshot(), last_said: this.lastSaid.slice(0, 600),
          awaiting: this.awaiting,
        }),
      });
      for await (const item of ndjson(r)) {
        if (!this.alive(ep)) throw new DOMException("stale", "AbortError");
        if (item.t === "ack") {
          if (item.kind === "llm") filler = window.setTimeout(() => this.playFiller(ep), FILLER_AFTER_MS);
        } else if (item.t === "meta") {
          window.clearTimeout(killer);
          meta = item as Meta;
          this.awaiting = null;              // ответ на вопрос Елены получен — дальше решает действие
          this.replyBusy = true;
          this.remember("user", text);
          this.pendingText = "";
          if (meta.user_name) this.setName(meta.user_name);
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
      this.replyBusy = false;
      window.clearTimeout(filler);
      window.clearTimeout(killer);
      if (this.turnCtl === ctl) this.turnCtl = null;
      if (((e as { name?: string })?.name === "AbortError" && !timedOut) || !this.alive(ep)) return;
      // сеть или сервер подвели — короткая просьба повторить, обзор (если шёл) продолжится
      this.remember("user", text);
      this.pendingText = "";
      await this.sayText(this.script?.phrases.sorry ?? "", ep);
      this.lastAsked = true;
      if (this.alive(ep)) this.afterAnswer(ep);
      return;
    }
    window.clearTimeout(filler);
    window.clearTimeout(killer);
    if (this.turnCtl === ctl) this.turnCtl = null;
    if (!this.alive(ep) || !meta) { this.replyBusy = false; return; }
    if (meta.text) this.remember("elena", meta.text);
    if (utter) {
      const res = await utter.end();
      if (res === "aborted" || !this.alive(ep)) { this.replyBusy = false; return; }
    } else if (meta.text) {
      // голос ответа не пришёл потоком — пробуем обычной загрузкой
      const res = await this.sayText(meta.text, ep, undefined, false);
      if (res === "aborted" || !this.alive(ep)) { this.replyBusy = false; return; }
    }
    this.lastAsked = /\?\s*$/.test(meta.text ?? "");
    const acting = this.act(meta, ep, nav);
    this.replyBusy = false;          // действие запущено синхронно (обзор уже «начат») — отложенная реплика может идти
    await acting;
  }

  private playFiller(ep: number) {
    const fl = this.script?.fillers ?? [];
    if (!this.alive(ep) || this.replyStarted || this.voice.speaking() || !fl.length) return;
    const pool = fl.filter((f) => f !== this.lastFiller);
    const f = pool[Math.floor(Math.random() * pool.length)] ?? fl[0];
    this.lastFiller = f;
    void this.pcm(f).then((pcm) => {
      if (!pcm || !this.alive(ep) || this.replyStarted) return;
      void this.voice.say(f, pcm, RATE);
    });
  }

  /** По решению сервера — сразу начать переход (вход в роль, открытие экрана), не дожидаясь конца ответа. */
  private prepare(meta: Meta, ep: number): Promise<boolean> | null {
    if (meta.action === "point" && meta.point) { this.showPoint(meta.point, ep); return null; }  // рамка — сразу с ответом
    const ns = meta.action === "next_section" ? this.nextSectionPos() : null;
    const step = meta.action === "start_tour" ? TRACKS[this.roleOf(meta)][0]
      : meta.action === "goto" && meta.step && STEPS[meta.step] ? meta.step
      : ns ? ns.ids[ns.i] : null;
    if (!step) return null;
    this.set({ stage: "corner" });
    this.prefetch(this.linesOf(step));
    return this.enter(STEPS[step], ep, null, false);
  }

  private roleOf(meta: Meta): TourTrack {
    return (meta.role && meta.role in TRACKS ? meta.role : "all") as TourTrack;
  }

  /** Начало следующего раздела обзора (другой кабинет) или null — раздел последний / обзора нет. */
  private nextSectionPos(): Pos | null {
    const p = this.pos;
    if (!p || !p.track) return null;
    const cab = STEPS[p.ids[p.i]]?.cabinet;
    let j = p.i + 1;
    while (j < p.ids.length && STEPS[p.ids[j]]?.cabinet === cab) j++;
    return j < p.ids.length ? { ...p, i: j, b: 0 } : null;
  }

  /** Где продолжить прерванный обзор: та же реплика, если прозвучало мало, иначе следующая. */
  private resumePos(): Pos | null {
    const p = this.pos;
    if (!p) return null;
    let { i, b } = p;
    if (this.heard >= REPEAT_IF_HEARD_LESS) b += 1;
    if (b >= this.linesOf(p.ids[i]).length) { i += 1; b = 0; }
    if (i >= p.ids.length) return null;
    return { ...p, i, b };
  }

  private async act(meta: Meta, ep: number, nav: Promise<boolean> | null) {
    const a = meta.action ?? "answer";
    if (a === "start_tour") {
      const role = this.roleOf(meta);
      // обзор уже «начат»: если человек заговорит, пока открывается экран, — обзор подождёт и продолжится с начала
      this.pos = { ids: TRACKS[role], track: role, i: 0, b: 0 };
      this.heard = 0;
      this.touring = true;
      this.paused = false;
      this.detour = null;
      if (nav) await nav;
      if (!this.alive(ep)) return;
      void this.runTour(role, 0, 0, ep, { bridge: true, named: false });
      return;
    }
    if (a === "goto" && meta.step && STEPS[meta.step]) {
      // посреди обзора: этот же экран — просто продолжаем; экран дальше по обзору — идём вперёд с него;
      // экран не из обзора или уже пройденный — показать и вернуться. Без обзора — показать и слушать дальше.
      const p = this.pos;
      if (p && (this.resumePending || this.paused || this.touring)) {
        const k = p.track ? p.ids.indexOf(meta.step) : -1;
        if (k === p.i) {
          if (nav) await nav;
          if (!this.alive(ep)) return;
          this.paused = false;
          void this.resumeTour(ep);
          return;
        }
        if (k > p.i) {
          if (nav) await nav;
          if (!this.alive(ep)) return;
          void this.runSteps({ ...p, i: k, b: 0 }, ep, { bridge: true });
          return;
        }
        if (p.track) this.detour = this.resumePos();   // идёт обзор — вернёмся к нему; показ одного экрана — нет
      }
      if (nav) await nav;
      if (!this.alive(ep)) return;
      this.paused = false;
      this.resumePending = false;
      // этот экран уже показывали — без вступительной реплики
      const b0 = this.shownSteps.has(meta.step) && this.linesOf(meta.step).length > 1 ? 1 : 0;
      void this.runSteps({ ids: [meta.step], track: null, i: 0, b: b0 }, ep, { bridge: false, single: true });
      return;
    }
    if (a === "point" && meta.point) {
      this.holdPoint();
      this.afterAnswer(ep);
      return;
    }
    if (a === "next_section") {
      // «пропусти» — к следующему разделу без вопросов (связку уже сказала в ответе)
      const ns = this.nextSectionPos();
      if (!ns) {
        this.touring = false;
        this.resumePending = false;
        this.paused = false;
        this.pos = null;
        this.set({ phase: "listening", target: null, click: null, stepNo: 0 });
        return;
      }
      if (nav) await nav;
      if (!this.alive(ep)) return;
      this.lastCabinet = STEPS[ns.ids[ns.i]]?.cabinet ?? this.lastCabinet;
      void this.runSteps(ns, ep, { bridge: true });
      return;
    }
    if (a === "listen") {
      // «Есть вопросы?» — «Да» → «Слушаю вас.»; после ответа на вопрос спросит, продолжать ли
      this.waitFor(null, ep, "remind");
      return;
    }
    if (a === "pause") {
      this.paused = this.paused || this.touring || this.resumePending || !!this.pos;
      this.resumePending = false;
      this.touring = false;
      this.awaiting = null;
      this.set({ phase: this.paused ? "paused" : "listening" });
      return;
    }
    if (a === "resume") {
      const wasPaused = this.paused;
      this.paused = false;
      if (!this.pos) { this.startNext(ep); return; }
      if (!wasPaused && !this.resumePending) this.heard = 1;   // «дальше» посреди реплики — следующая реплика
      if (meta.text) await sleep(200);
      if (!this.alive(ep)) return;
      void this.resumeTour(ep);
      return;
    }
    if (a === "repeat") {
      if (this.pos && (this.resumePending || this.touring || this.paused)) {
        this.paused = false;
        this.heard = 0;
        void this.resumeTour(ep);
        return;
      }
      if (this.lastSaid) await this.sayText(this.lastSaid, ep, undefined, false);
      if (this.alive(ep)) this.afterAnswer(ep);
      return;
    }
    if (a === "prev") {
      if (this.pos) {
        this.paused = false;
        this.resumePending = false;
        const p = { ...this.pos, i: Math.max(0, this.pos.i - 1), b: 0 };
        void this.runSteps(p, ep, { bridge: true });
        return;
      }
      this.afterAnswer(ep);
      return;
    }
    if (a === "end") {
      await sleep(250);
      if (this.alive(ep)) this.close();
      return;
    }
    if (a === "ask_role") {
      // новый вопрос «что показать?» — прежний недосмотренный обзор не продолжаем сами; ждём ответа
      this.resumePending = false;
      this.touring = false;
      this.pos = null;
      this.set({ stepNo: 0, stepTotal: 0 });
      this.waitFor("start", ep, "remind_start");
      return;
    }
    this.afterAnswer(ep);
  }

  /** Показать элемент экрана, о котором спросили: рамка на несколько секунд. */
  private showPoint(label: string, ep: number) {
    const sel = `text:${label}`;
    if (!findTarget(sel)) return;
    this.set({ stage: "corner", target: sel, click: null });
    this.post("point", { text: label });
    void this.bringIntoView(sel, ep);
    window.clearTimeout(this.pointTimer);
    this.pointTimer = window.setTimeout(() => {
      this.pointTimer = 0;
      if (this.ui.target === sel && !this.touring) this.set({ target: null });
    }, POINT_HOLD_MS);
  }

  /** Рамка вокруг показанного элемента держится ещё несколько секунд после ответа. */
  private holdPoint() {
    const sel = this.ui.target;
    if (!sel || !sel.startsWith("text:")) return;
    window.clearTimeout(this.pointTimer);
    this.pointTimer = window.setTimeout(() => {
      this.pointTimer = 0;
      if (this.ui.target === sel && !this.touring) this.set({ target: null });
    }, POINT_HOLD_MS);
  }

  /** После ответа: Елена сама дальше не идёт. Спросила — ждёт ответа; посреди обзора — спрашивает «Продолжаем?». */
  private afterAnswer(ep: number) {
    if (this.paused) { this.set({ phase: "paused" }); return; }
    if (this.lastAsked) { this.waitFor("answer", ep, this.resumePending ? "remind" : null); return; }
    if (this.resumePending) { void this.askContinue(ep); return; }
    this.awaiting = null;
    this.set({ phase: "listening" });
  }

  /** «Продолжаем обзор?» / «Переходим к работодателю?» — и ждать ответа. */
  private async askContinue(ep: number) {
    const next = this.resumePos();
    const cab = next ? STEPS[next.ids[next.i]]?.cabinet : null;
    const key = cab && this.lastCabinet && cab !== this.lastCabinet ? `continue_${cab}` : "continue";
    const q = this.phrase(key) || this.phrase("continue");
    this.set({ phase: "listening", click: null });
    await sleep(350);
    if (!this.alive(ep) || this.userBusy()) return;
    if (q && (await this.sayText(q, ep)) !== "done") return;
    if (!this.alive(ep)) return;
    this.remember("elena", q);
    this.lastAsked = true;
    this.waitFor("continue", ep, "remind");
  }

  /** Посмотрели экран не по порядку обзора — спросить, вернуться ли к обзору, и ждать. */
  private async askDetourBack(back: Pos, ep: number) {
    this.pos = back;
    this.heard = 0;
    this.touring = false;
    this.resumePending = true;
    this.lastCabinet = STEPS[back.ids[back.i]]?.cabinet ?? this.lastCabinet;   // возврат — без связки раздела
    this.set({ phase: "listening", click: null });
    const q = this.phrase("back_to_tour");
    if (q && (await this.sayText(q, ep)) !== "done") return;
    if (!this.alive(ep)) return;
    this.remember("elena", q);
    this.lastAsked = true;
    this.waitFor("detour", ep, "remind");
  }

  /** «Дальше», когда обзор роли уже закончен: следующая сторона платформы. */
  private startNext(ep: number) {
    const last = this.lastTrack;
    if (last === "candidate") void this.runTour("employer", 0, 0, ep, { bridge: true });
    else if (last === "employer") void this.runTour("fsp", 0, 0, ep, { bridge: true });
    else if (last === "fsp") void this.runTour("all", TRACKS.all.indexOf("warroom"), 0, ep, { bridge: true });
    else if (!last) void this.runTour("all", 0, 0, ep, { bridge: true, named: false });
    else this.set({ phase: "listening" });
  }

  private scheduleResume(ep: number, ms: number) {
    this.set({ phase: "listening" });
    window.clearTimeout(this.resumeTimer);
    this.resumeTimer = window.setTimeout(() => {
      this.resumeTimer = 0;
      if (!this.alive(ep) || this.buf.read() || this.voice.speaking() || this.turnCtl || this.paused) return;
      void this.resumeTour(ep);
    }, ms);
  }

  private async resumeTour(ep: number) {
    this.resumePending = false;
    const p = this.resumePos();
    if (!p) {
      if (this.pos && this.pos.track) { void this.finishTour(this.pos.track, ep); return; }
      const back = this.detour;
      if (back) {   // «покажи …» досмотрен — спросить, вернуться ли к обзору
        this.detour = null;
        void this.askDetourBack(back, ep);
        return;
      }
      this.pos = null;
      this.touring = false;
      this.set({ phase: "listening", target: null, stepNo: 0 });
      return;
    }
    void this.runSteps(p, ep, { bridge: true });
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
    const el = await this.waitEl(step.selector, ep, 2500);
    const b = await bridgeDone;
    if (!this.alive(ep) || b === "aborted") return false;
    if (el && scroll) await this.bringIntoView(step.selector, ep);
    return this.alive(ep);
  }

  /** Блок — в кадр: ждём, пока раскладка устоится (над блоком догружаются карточки), и ставим блок в верхнюю часть
   *  экрана под закреплённой шапкой (внизу справа — окно Елены). Новый вызов отменяет прошлый (без «перетягивания»). */
  private async bringIntoView(selector: string, ep: number) {
    const my = ++this.viewSeq;
    const live = () => this.alive(ep) && my === this.viewSeq;
    let prev = NaN;
    for (let i = 0; i < 6; i++) {
      const el = findTarget(selector);
      if (!el || !live()) return;
      const top = el.getBoundingClientRect().top + window.scrollY;
      if (Math.abs(top - prev) < 2) break;
      prev = top;
      await sleep(90);
    }
    for (let k = 0; k < 2; k++) {
      const el = findTarget(selector);
      if (!el || !live()) return;
      const inset = topInset();
      const r = el.getBoundingClientRect();
      const fits = r.top >= inset + 8 && r.top <= window.innerHeight * 0.5 && r.bottom <= window.innerHeight - 24;
      if (fits) return;
      const dy = r.top - (inset + 20);
      if (Math.abs(dy) < 4) return;
      window.scrollTo({ top: Math.max(0, window.scrollY + dy), behavior: "smooth" });
      await sleep(480);
    }
  }

  private planClick(beat: Beat, u: Utterance, totalMs: number, ep: number) {
    window.clearTimeout(this.clickTimer);
    if (!beat.click) { this.set({ click: null }); return; }
    const lead = this.d.avatar()?.live() ? PIPE_MS : 80;
    const at = performance.now() + lead + Math.max(1200, totalMs) * (beat.clickAt ?? 0.5);
    this.set({ click: { selector: beat.click, at } });
    const sel = beat.click;
    this.clickTimer = window.setTimeout(() => {
      this.clickTimer = 0;
      if (!this.alive(ep) || this.stepUtter !== u) return;
      const el = findTarget(sel);
      if (el) { try { el.click(); } catch { /* блок пропал */ } }
    }, Math.max(0, at - performance.now()));
  }

  private runTour(track: TourTrack, from: number, beat: number, ep: number, opts: { bridge: boolean; named?: boolean }) {
    this.detour = null;
    return this.runSteps({ ids: TRACKS[track], track, i: from, b: beat }, ep, opts);
  }

  /** Основной цикл обзора: шаг за шагом, реплика за репликой. single — показать один экран («покажи …»). */
  private async runSteps(start: Pos, ep: number, opts: { bridge: boolean; named?: boolean; single?: boolean }) {
    const sc = this.script;
    if (!sc || !this.alive(ep)) return;
    const { ids, track } = start;
    this.paused = false;
    this.resumePending = false;
    this.awaiting = null;
    this.touring = true;
    window.clearTimeout(this.pointTimer);
    this.set({ stage: "corner" });
    let prevCab: Cabinet | null = opts.bridge ? this.lastCabinet : STEPS[ids[start.i]]?.cabinet ?? null;
    let firstBridge = opts.bridge && !this.lastCabinet;
    for (let i = Math.max(0, start.i); i < ids.length; i++) {
      if (!this.alive(ep)) return;
      const step = STEPS[ids[i]];
      if (!step) continue;
      const lines = this.linesOf(step.id);
      const b0 = i === start.i ? Math.min(start.b, Math.max(0, lines.length - 1)) : 0;
      if (i > start.i && track && !opts.single && !this.noMic && prevCab && step.cabinet !== prevCab) {
        // раздел закончился — спросить, есть ли вопросы, и ждать ответа (дальше — только после ответа)
        const q = this.phrase(`checkin_${prevCab}`);
        if (q) {
          this.pos = { ids, track, i, b: 0 };
          this.heard = 0;
          this.touring = false;
          this.resumePending = true;
          this.set({ phase: "listening", target: null, click: null });
          await sleep(300);
          if (!this.alive(ep)) return;
          if (this.userBusy()) return;
          if ((await this.sayText(q, ep)) !== "done" || !this.alive(ep)) return;
          this.remember("elena", q);
          this.lastAsked = true;
          this.waitFor("checkin", ep, "remind_checkin");
          return;
        }
      }
      this.pos = { ids, track, i, b: b0 };
      this.heard = 0;
      this.prefetchFrom(ids, i + 1);
      this.set({ phase: "touring", track, stepNo: track ? i + 1 : 0, stepTotal: track ? ids.length : 0 });
      const bridge = prevCab !== step.cabinet ? this.bridgeText(step.cabinet, firstBridge, !!opts.named) : null;
      firstBridge = false;
      const ok = await this.enter(step, ep, bridge, false);
      if (!this.alive(ep) || !ok) return;
      prevCab = step.cabinet;
      this.lastCabinet = step.cabinet;     // связка раздела прозвучала — при продолжении не повторяется
      if (this.userBusy()) { this.holdForUser(); return; }
      if (b0 === 0) this.post("step", { step: step.id });
      this.shownSteps.add(step.id);
      for (let b = b0; b < lines.length; b++) {
        if (!this.alive(ep)) return;
        const beat = step.beats[b] ?? step.beats[step.beats.length - 1] ?? { target: step.selector };
        // реплика-переход («Открою …» с нажатием) — только если следующий шаг обзора именно туда
        if (beat.lead && (opts.single || ids[i + 1] !== beat.lead)) continue;
        const target = beat.target ?? step.selector;
        this.pos = { ids, track, i, b };
        this.heard = 0;
        this.set({ target, click: null });
        void this.bringIntoView(target, ep);   // прокрутка идёт вместе с началом реплики — без пауз
        await sleep(140);
        if (!this.alive(ep)) return;
        const res = await this.sayText(lines[b], ep, (u, total) => { this.stepUtter = u; this.planClick(beat, u, total, ep); });
        this.stepUtter = null;
        if (res === "aborted" || !this.alive(ep)) return;
        this.heard = 1;
        await sleep(b < lines.length - 1 ? BEAT_GAP_MS : 260);
        if (!this.alive(ep)) return;
        if (this.userBusy()) { this.holdForUser(); return; }
      }
      if (opts.single) break;
    }
    if (!this.alive(ep)) return;
    if (!track) {
      const back = this.detour;
      this.detour = null;
      if (back) {
        void this.askDetourBack(back, ep);
        return;
      }
      this.touring = false;
      this.pos = null;
      this.set({ phase: "listening", click: null, stepNo: 0, stepTotal: 0 });
      window.clearTimeout(this.pointTimer);
      this.pointTimer = window.setTimeout(() => { this.pointTimer = 0; if (!this.touring) this.set({ target: null }); }, 2500);
      return;
    }
    if (track) await this.finishTour(track, ep);
  }

  private async finishTour(track: TourTrack, ep: number) {
    this.touring = false;
    this.set({ phase: "listening", target: null, click: null, stepNo: 0 });
    const done = this.phrase(`done_${track}`) || this.phrase("done_all");
    await this.sayText(done, ep);
    if (this.alive(ep)) {
      this.remember("elena", done);
      this.pos = null;
      this.lastTrack = track;
      this.set({ phase: "listening", track: null });
    }
  }
}
