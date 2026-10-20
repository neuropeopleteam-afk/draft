// Настя — живой проводник «как по видеосвязи». Один микрофон на весь разговор (LiveListener), голос — в видеопоток
// аватара (Voice), решения по ходу разговора — сервер (/api/interview/concierge/turn, поток NDJSON: модель с базой
// знаний, памятью разговора и фоновым наставником), постоянные фразы и реплики обзора — из кэша, заранее загруженные
// в память (переходы без пауз).
//
// Устройство разговора — полудуплекс, как у работающих живых стендов:
//  • пока Настя думает или говорит, микрофон закрыт (в распознавание идёт тишина) и открывается через ~0,45 с после
//    конца её фразы — нет эха, фантомных реплик и перебивания; её не перебивают голосом, только кнопкой паузы;
//  • микрофон открыт ровно в двух состояниях — «слушаю» (listening) и «пауза» (paused): после её вопроса, в окне между
//    экранами обзора и когда обзор остановлен; индикатор на кнопке микрофона показывает, слышит ли она сейчас;
//  • конец хода собеседника — по паузе в речи (поставщик ждёт 0,7 с; дальше своя пауза по виду фразы: команда — быстро,
//    незаконченная мысль — дольше); пока человек говорит, новую реплику Настя не начинает;
//  • спросила — ждёт ответа и сама дальше не идёт (одно короткое напоминание через 25 с; долгое молчание — прощается
//    и уходит в угол, чтобы не жечь минуты видеопотока);
//  • обзор: шаг = экран, на каждую короткую реплику — свой блок (подсветка, прокрутка, «нажатие» в нужный момент);
//    после каждого экрана — короткое окно для реплики человека; между разделами (кандидат → работодатель → Федерация →
//    жюри) — вопрос «Есть вопросы?» и ожидание; после ответа на вопрос посреди обзора — «Продолжаем?»;
//  • «покажи …» посреди обзора — экран дальше по обзору: идём вперёд с него; другой экран — показать и спросить,
//    вернуться ли к обзору; «пропусти» — к следующему разделу;
//  • каждая встреча пишется в стенограмму на сервере (реплики, шаги, решения).
//
// Один «эпизод» (ep) — одна линия действий (ход, обзор, пауза): новая линия обрывает старую, поэтому состояний мало:
// pos — где обзор говорит сейчас, resumeAt — где его продолжить после вопроса/паузы/отхода, awaiting — чего Настя ждёт.
import { apiUrl, tokenStore, type MeOut } from "../../lib/api";
import type { Persona } from "../../lib/jury";
import type { AnamHandle } from "../voice/AnamAvatar";
import { LiveListener, liveSttSupported, type MicState, type SttEvent } from "../voice/live/listener";
import { SpeechBuffer, isBackchannel, words } from "../voice/live/turns";
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
  /** Микрофон открыт — Настя слышит собеседника (между экранами, после своего вопроса, на паузе). */
  hearing: boolean;
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
  /** Без видеопотока (проверки, экономия минут): голос — через Web Audio, портрет статичный. */
  noVideo?: boolean;
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
  /** Потолок одного разговора, минут (минуты видеопотока платные): по истечении Настя прощается и закрывается. */
  max_minutes?: number;
}

interface Meta {
  action?: string;
  role?: string | null;
  step?: string | null;
  point?: string | null;
  user_name?: string | null;
  text?: string;
  kind?: string;
  phrase?: string | null;
}

interface Pos { ids: string[]; track: TourTrack | null; i: number; b: number }

const RATE = 24000;
const BYTES_PER_MS = (RATE * 2) / 1000;
const PIPE_MS = 650;               // звук из видеопотока звучит примерно через столько после отправки
const REMIND_AFTER_MS = 25000;     // спросила и ждёт: одно короткое напоминание, потом просто ждёт
const IDLE_CLOSE_MS = 120000;      // после напоминания никто не ответил — прощается и закрывается (минуты видеопотока)
const IDLE_FREE_MS = 180000;       // свободное ожидание без вопроса (обзор закончен) — дольше
const FILLER_AFTER_MS = 1500;      // модель думает дольше — короткая связка («Секунду.»), быстрые ответы без неё
const STALE_INTERIM_MS = 2600;     // промежуточный текст не меняется — считаем фразу законченной
const LOOKAHEAD_MS = 4500;         // звук в видеопоток — с запасом: подвисание страницы при переходе не рвёт фразу
const GATE_AFTER_SPEECH_MS = 450;  // микрофон открывается через столько после конца её фразы (хвост из динамиков)
const GATE_TAIL_IGNORE_MS = 250;   // текст, пришедший сразу после открытия микрофона, — хвост её голоса
const WINDOW_MS = 1700;            // окно для реплики человека после экрана обзора (с учётом GATE_AFTER_SPEECH_MS)
const WINDOW_MAX_WAIT_MS = 7000;   // речь началась, а слов нет (шум) — обзор продолжается
const BEAT_GAP_MS = 380;           // пауза между репликами обзора — спокойный темп без «провалов»
const POINT_HOLD_MS = 6000;
const REPEAT_IF_HEARD_LESS = 0.6;
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

/** Что сейчас на экране — заголовок и видимые надписи (Настя отвечает «по экрану» и может показать элемент). */
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
    phase: "idle", mic: "off", speaking: false, userTalking: false, hearing: false, track: null, stepNo: 0, stepTotal: 0,
    target: null, click: null, canPause: false, stage: "corner",
  };
  private closed = false;
  private ep = 0;                       // текущая «линия» действий; новая линия (ход, пауза, закрытие) обрывает старую
  private buf = new SpeechBuffer();
  private turnCtl: AbortController | null = null;
  private endTimer = 0;
  private staleTimer = 0;
  private remindTimer = 0;
  private idleTimer = 0;
  private clickTimer = 0;
  private pointTimer = 0;
  private tick = 0;
  private history: { who: "elena" | "user"; text: string }[] = [];
  private userName: string | null = null;
  // микрофон
  private thinking = false;             // ход ушёл на сервер, ответ ещё не зазвучал — микрофон закрыт
  private gateUntil = 0;                // микрофон закрыт до этого момента после конца её фразы
  private gateOpenedAt = 0;
  private gated = true;
  private wasSpeaking = false;
  private lastSpeechStart = 0;          // человек начал говорить (событие поставщика) при открытом микрофоне
  // обзор
  private pos: Pos | null = null;       // где обзор говорит сейчас (реплика)
  private lastBeat: Pos | null = null;  // последняя прозвучавшая реплика обзора («повтори», «назад»)
  private resumeAt: Pos | null = null;  // где продолжить прерванный обзор (вопрос, пауза, отход)
  private tourTrack: TourTrack | null = null;   // обзор начат и не закончен (идёт, ждёт или на паузе)
  private paused = false;               // пауза по просьбе человека или кнопкой
  private curStep: string | null = null;        // последний открытый экран обзора (для сервера)
  private lastCabinet: Cabinet | null = null;   // связка этого раздела уже звучала
  private lastTrack: TourTrack | null = null;   // последний завершённый обзор («дальше» после конца)
  private shownSteps = new Set<string>();
  private lastSaid = "";
  private lastAsked = false;            // ответ закончился вопросом — Настя ждёт ответа
  private lastFiller = "";
  private stepUtter: Utterance | null = null;
  private awaiting: Awaiting = null;    // чего ждёт после своей реплики (уходит на сервер вместе с ходом)
  private noMic = false;                // микрофона нет — ведёт сама, без окон и вопросов между разделами
  private pendingBridge: string | null = null;  // короткая связка перед продолжением обзора («Продолжаю.»)
  private timeUpTimer = 0;              // потолок разговора
  private startedAt = performance.now();
  private micKnown: Promise<MicState> | null = null;
  private lastMicLogged: MicState | null = null;
  private viewSeq = 0;

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
    this.ui.canPause = !!this.tourTrack;
    this.d.onUi(this.ui);
  }

  getUi(): ElenaUi { return this.ui; }
  micLevel(): number { return this.gated ? 0 : this.listener?.level() ?? 0; }
  isMuted(): boolean { return this.listener?.isMuted() ?? false; }
  /** Кнопка «развернуть / в угол». */
  setStage(stage: Stage) { this.set({ stage }); }

  /** Микрофон закрыт: Настя думает, говорит, только что договорила или занята переходом; открыт — только когда слушает. */
  private micGated(): boolean {
    if (this.closed || this.thinking || this.voice.speaking()) return true;
    if (performance.now() < this.gateUntil) return true;
    return this.ui.phase !== "listening" && this.ui.phase !== "paused";
  }

  /** Такт 100 мс: индикатор «говорит», открытие микрофона после её фразы, сброс накопленного при закрытом микрофоне. */
  private watch() {
    window.clearInterval(this.tick);
    this.tick = window.setInterval(() => {
      if (this.closed) return;
      const s = this.voice.speaking();
      if (s !== this.ui.speaking) this.set({ speaking: s });
      if (this.wasSpeaking && !s) this.gateUntil = performance.now() + GATE_AFTER_SPEECH_MS;
      this.wasSpeaking = s;
      const g = this.micGated();
      if (g !== this.gated) {
        this.gated = g;
        if (!g) { this.buf.reset(); this.gateOpenedAt = performance.now(); }
        else if (this.ui.userTalking) this.set({ userTalking: false });
      }
      const hearing = !g && this.ui.mic === "on";
      if (hearing !== this.ui.hearing) this.set({ hearing });
    }, 100);
  }

  // ------------------------------------------------------------------ стенограмма

  private post(type: "open" | "say" | "step" | "close" | "mic" | "point", extra: { text?: string; step?: string | null } = {}) {
    const body = JSON.stringify({
      session_id: this.sid, type, text: (extra.text ?? "").slice(0, 1200), step: extra.step ?? null,
      path: this.d.path().slice(0, 200), name: this.userName, role: this.tourTrack ?? null,
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

  private remember(who: "elena" | "user", text: string) {
    if (!text) return;
    this.history.push({ who, text });
    if (this.history.length > 12) this.history.splice(0, this.history.length - 12);
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
    if (log) this.post("say", { text, step: this.pos ? this.pos.ids[this.pos.i] : this.curStep });
    if (!pcm) {
      onStart?.({ text, startedAt: performance.now(), durationMs: 0, push: () => undefined, end: async () => "done", progress: () => 1 } as Utterance, 0);
      await sleep(Math.min(6000, 900 + text.length * 45));
      return this.alive(ep) ? "done" : "aborted";
    }
    const total = pcm.byteLength / BYTES_PER_MS;
    return this.voice.say(text, pcm, RATE, (u) => onStart?.(u, total));
  }

  private phrase(key: string): string {
    const sc = this.script;
    if (!sc) return "";
    const n = sc.phrases_named?.[key];
    return n && this.userName ? this.named(n) : sc.phrases[key] ?? "";
  }

  private bridgeText(cab: Cabinet, first: boolean, withName: boolean): string | null {
    const b = this.script?.bridges[cab];
    if (!b) return null;
    if (typeof b === "string") return first ? null : b;
    if (first) return (withName && this.userName && b.first_named ? this.named(b.first_named) : b.first) || null;
    return b.next || null;
  }

  // ------------------------------------------------------------------ запуск и закрытие

  /** Вызывать прямо из обработчика нажатия: звук и микрофон разрешаются жестом пользователя. */
  start(track?: TourTrack, stepIndex = 0) {
    this.voice.unlock();
    this.watch();
    if (liveSttSupported()) {
      this.listener = new LiveListener({
        path: "/api/interview/live/stt?p=guide",
        gate: () => this.micGated(),
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
    if (this.d.noVideo) return false;
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

  private async boot(track?: TourTrack, stepIndex = 0) {
    const ep = ++this.ep;
    this.set({ phase: "connecting" });
    if (!this.d.noVideo) this.d.avatar()?.connect();
    const sc = await this.loadScript();
    if (!this.alive(ep)) return;
    if (!sc) { this.close(); return; }
    this.script = sc;
    this.armTimeUp(sc.max_minutes);
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
    const rest = [sc.nudge, sc.nudge_role, ...this.linesOf(firstIds[stepIndex] ?? ""),
      this.bridgeText("candidate", true, false), sc.phrases.ask_role, sc.phrases.pause, sc.phrases.goto,
      sc.phrases.continue, sc.phrases.listen, sc.phrases.checkin_candidate, sc.phrases.continue_employer,
      ...this.linesOf(firstIds[stepIndex + 1] ?? ""), ...sc.fillers.slice(0, 2), sc.phrases.nomic, sc.phrases.back_to_tour,
      sc.phrases.remind_start, sc.phrases.no_more, sc.phrases.idle_bye, sc.phrases.sorry, sc.phrases.resume_tour,
      sc.phrases.back_tour, sc.phrases.time_up];
    void Promise.race([greet, sleep(2500)]).then(() => { if (!this.closed) this.prefetch(rest); });
    // поток аватара и звук приветствия — параллельно; ждём не дольше 6 с, иначе говорим запасным голосом
    await Promise.race([Promise.all([this.waitAvatar(6000), greet]), sleep(6500)]);
    if (!this.alive(ep)) return;
    if (track) {
      this.tourTrack = track;
      void this.runTour({ ids: TRACKS[track], track, i: stepIndex, b: 0 }, ep, { bridge: true, named: true });
      return;
    }
    const mic = this.listener?.getState() ?? "error";
    if (mic === "denied" || mic === "nodevice" || mic === "error") {
      this.noMic = true;
      this.set({ phase: "greeting" });
      if ((await this.sayText(sc.phrases.nomic, ep)) !== "done") return;
      this.tourTrack = "all";
      void this.runTour({ ids: TRACKS.all, track: "all", i: 0, b: 0 }, ep, { bridge: true, named: true });
      return;
    }
    this.set({ phase: "greeting" });
    const r = await this.sayText(greetText, ep);
    if (r !== "done" || !this.alive(ep)) return;
    this.remember("elena", greetText);
    // разрешение на микрофон ещё не дано — ждём решения (до 10 с), потом решаем, слушать или вести самой
    const st = await Promise.race([this.micKnown ?? Promise.resolve<MicState>("error"), sleep(10000).then(() => "connecting" as MicState)]);
    if (!this.alive(ep)) return;
    if (st !== "on" && st !== "muted") {
      this.noMic = true;
      const nudge = this.userName ? (sc.nudge_role ?? sc.nudge) : sc.nudge;
      if ((await this.sayText(nudge, ep)) !== "done") return;
      this.tourTrack = "all";
      void this.runTour({ ids: TRACKS.all, track: "all", i: 0, b: 0 }, ep, { bridge: true, named: true });
      return;
    }
    // спросила (имя или что показать) — ждёт ответа; сама обзор не начинает
    this.lastAsked = true;
    this.waitFor("start", ep, "remind_start");
  }

  close() {
    if (this.closed) return;
    this.post("close");
    this.ep++;
    this.clearTimers();
    window.clearTimeout(this.timeUpTimer);
    this.turnCtl?.abort();
    this.voice.close();
    this.listener?.stop();
    window.clearInterval(this.tick);
    this.set({ phase: "idle", target: null, click: null, stepNo: 0, speaking: false, hearing: false });
    this.closed = true;
    this.d.onClose();
  }

  toggleMute() {
    if (!this.listener) return;
    this.listener.setMuted(!this.listener.isMuted());
    this.set({ mic: this.listener.getState() });
  }

  /** Кнопка паузы: остановить обзор (и её фразу) сейчас же / продолжить с того же места. */
  togglePause() {
    if (this.paused) {
      this.paused = false;
      const ep = ++this.ep;
      this.clearTimers();
      this.pendingBridge = this.phrase("resume_tour") || null;
      if (this.resumeAt) void this.runTour(this.resumeAt, ep, { bridge: true });
      else if (this.tourTrack) void this.finishTour(this.tourTrack, ep);
      else this.waitFor(null, ep, null);
      return;
    }
    if (!this.tourTrack) return;
    const heard = this.stepUtter ? this.stepUtter.progress() : 1;
    this.ep++;
    this.clearTimers();
    this.turnCtl?.abort();
    this.turnCtl = null;
    this.thinking = false;
    this.voice.stop();
    if (this.pos) this.resumeAt = this.advance(this.pos, heard);
    this.pos = null;
    this.stepUtter = null;
    this.paused = true;
    this.awaiting = null;
    this.set({ phase: "paused", click: null });
  }

  /** Для проверок без микрофона (window.__elena.say): реплика собеседника текстом. */
  injectUser(text: string) {
    if (this.closed || !text.trim()) return;
    this.buf.reset();
    void this.runTurn(text.trim());
  }

  // ------------------------------------------------------------------ таймеры и ожидание

  /** Потолок разговора: минуты видеопотока платные — по истечении Настя договаривает фразу, прощается и закрывается. */
  private armTimeUp(minutes: number | undefined) {
    window.clearTimeout(this.timeUpTimer);
    const ms = Math.max(1, Number(minutes) || 9) * 60000 - (performance.now() - this.startedAt);
    this.timeUpTimer = window.setTimeout(() => void this.timeUp(), Math.max(1000, ms));
  }

  private async timeUp() {
    if (this.closed) return;
    // дождаться конца текущей фразы (не рвём её), потом попрощаться
    const t0 = performance.now();
    while (!this.closed && (this.voice.speaking() || this.thinking) && performance.now() - t0 < 15000) await sleep(150);
    if (this.closed) return;
    const ep = ++this.ep;
    this.clearTimers();
    this.turnCtl?.abort();
    this.turnCtl = null;
    this.thinking = false;
    this.pos = null;
    this.set({ phase: "answering", click: null, target: null });
    await this.sayText(this.phrase("time_up"), ep);
    if (this.alive(ep)) this.close();
  }

  private clearTimers() {
    for (const t of [this.endTimer, this.staleTimer, this.remindTimer, this.idleTimer, this.clickTimer, this.pointTimer]) window.clearTimeout(t);
    this.endTimer = this.staleTimer = this.remindTimer = this.idleTimer = this.clickTimer = this.pointTimer = 0;
  }

  private clearWait() {
    window.clearTimeout(this.remindTimer); window.clearTimeout(this.idleTimer);
    this.remindTimer = this.idleTimer = 0;
  }

  /** Человек что-то говорит или его ход в работе — Настя сама ничего не начинает. */
  private userBusy(): boolean {
    return !!this.buf.read() || this.ui.userTalking || this.thinking || this.voice.speaking()
      || performance.now() - this.lastSpeechStart < 1500;
  }

  /** Настя сказала своё и ждёт: микрофон открыт. kind — чего ждёт (уходит на сервер). Одно напоминание через 25 с,
   *  при долгом молчании — прощается и закрывается. */
  private waitFor(kind: Awaiting, ep: number, remindKey: string | null) {
    this.awaiting = kind;
    this.clearWait();
    this.set({ phase: this.paused ? "paused" : "listening", click: null });
    if (this.noMic) return;
    if (remindKey) {
      this.remindTimer = window.setTimeout(() => {
        this.remindTimer = 0;
        if (!this.alive(ep) || this.userBusy()) return;
        const t = this.phrase(remindKey);
        if (t) void this.sayText(t, ep).then(() => { if (this.alive(ep)) this.set({ phase: this.paused ? "paused" : "listening" }); });
      }, REMIND_AFTER_MS);
    }
    this.idleTimer = window.setTimeout(async () => {
      this.idleTimer = 0;
      if (!this.alive(ep) || this.userBusy()) return;
      await this.sayText(this.phrase("idle_bye"), ep);
      if (this.alive(ep)) this.close();
    }, kind ? IDLE_CLOSE_MS : IDLE_FREE_MS);
  }

  // ------------------------------------------------------------------ распознавание: ход собеседника

  private onStt(e: SttEvent) {
    if (this.closed) return;
    if (e.type === "ready") return;
    if (e.type === "error") { this.set({ mic: "error" }); return; }
    if (this.micGated()) return;       // микрофон закрыт — всё пришедшее не реплика (хвосты её голоса)
    if (e.type === "speech_started") {
      this.lastSpeechStart = performance.now();
      this.clearWait();
      // человек снова заговорил, пока ждём конца хода, — подождать ещё
      if (this.endTimer && this.buf.read()) this.armEnd(900);
      return;
    }
    if (e.type === "interim" || e.type === "final") {
      const text = e.text.trim();
      if (!text) return;
      if (performance.now() - this.gateOpenedAt < GATE_TAIL_IGNORE_MS && !this.buf.read()) return;
      this.clearWait();
      if (this.buf.accept(e)) {
        if (!this.ui.userTalking) this.set({ userTalking: true });
        window.clearTimeout(this.endTimer);
        this.endTimer = 0;
        this.armStale();
      }
      if (e.type === "final") this.armEnd(e.speech_final ? 0 : 700);
      return;
    }
    if (e.type === "speech_final_empty" || e.type === "utterance_end") {
      // тишина уже выждана поставщиком — конец хода, но незаконченную мысль всё равно даём договорить
      if (this.buf.read()) this.armEnd(e.type === "utterance_end" ? -1200 : 0);
    }
  }

  private armStale() {
    window.clearTimeout(this.staleTimer);
    const v = this.buf.version;
    this.staleTimer = window.setTimeout(() => {
      if (this.buf.version === v && this.buf.read() && !this.endTimer) this.armEnd(-600);
    }, STALE_INTERIM_MS);
  }

  private armEnd(extra = 0) {
    const text = this.buf.read();
    if (!text) return;
    window.clearTimeout(this.endTimer);
    const v = this.buf.version;
    const delay = Math.max(250, guideDelay(text) + extra);
    this.endTimer = window.setTimeout(() => {
      this.endTimer = 0;
      if (this.buf.version === v) this.submit();
    }, delay);
  }

  private submit() {
    window.clearTimeout(this.staleTimer);
    const text = this.buf.take();
    this.set({ userTalking: false });
    if (!text) return;
    // «угу» в окне между экранами, когда Настя ни о чём не спрашивала, — не реплика
    if (isBackchannel(text) && words(text).length <= 1 && !this.awaiting && !this.paused) return;
    void this.runTurn(text);
  }

  // ------------------------------------------------------------------ ход: сервер решает, Настя отвечает

  /** Следующая реплика после прерванной: та же, если прозвучало мало, иначе следующая; null — обзор закончен. */
  private advance(p: Pos, heard: number): Pos | null {
    let { i, b } = p;
    if (heard >= REPEAT_IF_HEARD_LESS) b += 1;
    if (b >= this.linesOf(p.ids[i]).length) { i += 1; b = 0; }
    return i < p.ids.length ? { ...p, i, b } : null;
  }

  private async runTurn(text: string) {
    const ep = ++this.ep;
    this.clearTimers();
    this.thinking = true;
    if (this.pos) this.resumeAt = this.advance(this.pos, this.stepUtter ? this.stepUtter.progress() : 1);
    this.pos = null;
    this.stepUtter = null;
    this.voice.stop();
    const ctl = new AbortController();
    this.turnCtl = ctl;
    // ответ сервера завис (связь) — не ждём вечно: через 10 с без решения — короткая просьба повторить
    let timedOut = false;
    const killer = window.setTimeout(() => { timedOut = true; ctl.abort(); }, 10000);
    this.set({ phase: "thinking", click: null, userTalking: false });
    let filler = 0;
    let utter: Utterance | null = null;
    let meta: Meta | null = null;
    let nav: Promise<boolean> | null = null;
    const finish = () => {
      window.clearTimeout(filler);
      window.clearTimeout(killer);
      if (this.turnCtl === ctl) this.turnCtl = null;
      this.thinking = false;
    };
    try {
      const token = tokenStore.get();
      const r = await fetch(apiUrl("/interview/concierge/turn"), {
        method: "POST",
        signal: ctl.signal,
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          message: text, user_name: this.userName, role: this.tourTrack ?? this.lastTrack, current_path: this.d.path(),
          step_id: this.curStep, touring: !!this.tourTrack && !this.paused, paused: this.paused,
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
          this.awaiting = null;              // ответ на вопрос Насти получен — дальше решает действие
          this.remember("user", text);
          if (meta.user_name) this.setName(meta.user_name);
          nav = this.prepare(meta, ep);      // экран начинает открываться, пока Настя говорит ответ
        } else if (item.t === "pcm" && typeof item.b64 === "string") {
          if (!utter) {
            window.clearTimeout(filler);
            utter = this.voice.begin(meta?.text ?? "", RATE);
            this.lastSaid = meta?.text ?? "";
            this.set({ phase: "answering" });
          }
          utter.push(b64bytes(item.b64));
          this.thinking = false;             // звук пошёл — микрофон держит закрытым сама речь
        } else if (item.t === "end") {
          break;
        }
      }
    } catch (e) {
      finish();
      if (((e as { name?: string })?.name === "AbortError" && !timedOut) || !this.alive(ep)) return;
      // сеть или сервер подвели — короткая просьба повторить; обзор (если шёл) продолжится после ответа
      this.remember("user", text);
      this.set({ phase: "answering" });
      await this.sayText(this.phrase("sorry"), ep);
      this.lastAsked = true;
      if (this.alive(ep)) this.afterAnswer(ep);
      return;
    }
    finish();
    if (!this.alive(ep) || !meta) return;
    if (meta.text) this.remember("elena", meta.text);
    if (utter) {
      const res = await utter.end();
      if (res === "aborted" || !this.alive(ep)) return;
    } else if (meta.text) {
      // голос ответа не пришёл потоком — пробуем обычной загрузкой
      this.set({ phase: "answering" });
      const res = await this.sayText(meta.text, ep, undefined, false);
      if (res === "aborted" || !this.alive(ep)) return;
    }
    this.lastAsked = /\?\s*$/.test(meta.text ?? "");
    await this.act(meta, ep, nav);
  }

  private playFiller(ep: number) {
    const fl = this.script?.fillers ?? [];
    if (!this.alive(ep) || !this.thinking || this.voice.speaking() || !fl.length) return;
    const pool = fl.filter((f) => f !== this.lastFiller);
    const f = pool[Math.floor(Math.random() * pool.length)] ?? fl[0];
    this.lastFiller = f;
    void this.pcm(f).then((pcm) => {
      if (!pcm || !this.alive(ep) || !this.thinking) return;
      void this.voice.say(f, pcm, RATE);
    });
  }

  private roleOf(meta: Meta): TourTrack {
    return (meta.role && meta.role in TRACKS ? meta.role : "all") as TourTrack;
  }

  /** Начало следующего раздела обзора (другой кабинет) относительно последнего открытого экрана; null — его нет. */
  private nextSectionPos(): Pos | null {
    const track = this.tourTrack;
    const cur = this.curStep;
    if (!track || !cur) return null;
    const ids = TRACKS[track];
    const k = ids.indexOf(cur);
    if (k < 0) return null;
    const cab = STEPS[cur]?.cabinet;
    let j = k + 1;
    while (j < ids.length && STEPS[ids[j]]?.cabinet === cab) j++;
    return j < ids.length ? { ids, track, i: j, b: 0 } : null;
  }

  /** Куда ведёт «goto» посреди обзора: вперёд по обзору (продолжаем с этого экрана) или в сторону (показать и вернуться). */
  private forwardPos(step: string): Pos | null {
    const r = this.resumeAt;
    if (!r || !r.track) return null;
    const k = r.ids.indexOf(step);
    return k >= r.i ? { ...r, i: k, b: 0 } : null;
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
    return this.enter(STEPS[step], ep, null);
  }

  private async act(meta: Meta, ep: number, nav: Promise<boolean> | null) {
    const a = meta.action ?? "answer";
    if (a === "start_tour") {
      const role = this.roleOf(meta);
      this.tourTrack = role;
      this.resumeAt = null;
      this.paused = false;
      this.pendingBridge = null;
      if (nav) await nav;
      if (!this.alive(ep)) return;
      void this.runTour({ ids: TRACKS[role], track: role, i: 0, b: 0 }, ep, { bridge: true, named: false });
      return;
    }
    if (a === "goto" && meta.step && STEPS[meta.step]) {
      const fwd = this.forwardPos(meta.step);
      if (nav) await nav;
      if (!this.alive(ep)) return;
      this.paused = false;
      if (fwd) { void this.runTour(fwd, ep, { bridge: true }); return; }
      // экран не по порядку обзора (или обзора нет) — показать его одного; этот экран уже показывали — без вступления
      const b0 = this.shownSteps.has(meta.step) && this.linesOf(meta.step).length > 1 ? 1 : 0;
      void this.runTour({ ids: [meta.step], track: null, i: 0, b: b0 }, ep, { bridge: false, single: true });
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
      if (nav) await nav;
      if (!this.alive(ep)) return;
      if (ns) {
        this.lastCabinet = STEPS[ns.ids[ns.i]]?.cabinet ?? this.lastCabinet;
        void this.runTour(ns, ep, { bridge: true });
        return;
      }
      // в этом обзоре следующего раздела нет (обзор одной роли) — по связке сервера идём в другой обзор
      const nextTrack: TourTrack | null = meta.phrase === "skip_employer" ? "employer" : meta.phrase === "skip_fsp" ? "fsp"
        : meta.phrase === "skip_public" ? "all" : null;
      this.tourTrack = null;
      this.resumeAt = null;
      this.paused = false;
      if (nextTrack) {
        this.tourTrack = nextTrack;
        const from = nextTrack === "all" ? TRACKS.all.indexOf("warroom") : 0;
        this.lastCabinet = STEPS[TRACKS[nextTrack][from]]?.cabinet ?? null;
        void this.runTour({ ids: TRACKS[nextTrack], track: nextTrack, i: from, b: 0 }, ep, { bridge: true });
        return;
      }
      this.set({ target: null, click: null, stepNo: 0, stepTotal: 0 });
      this.waitFor(null, ep, null);
      return;
    }
    if (a === "listen") {
      // «Есть вопросы?» — «Да» → «Слушаю вас.»; после ответа на вопрос спросит, продолжать ли
      this.waitFor(null, ep, "remind");
      return;
    }
    if (a === "pause") {
      this.paused = !!this.tourTrack;
      this.waitFor(null, ep, this.paused ? null : null);
      return;
    }
    if (a === "resume") {
      this.paused = false;
      if (this.resumeAt) {
        if (meta.text) await sleep(150);
        else this.pendingBridge = this.phrase("resume_tour") || null;   // «дальше» без ответа — короткое «Продолжаю.»
        if (!this.alive(ep)) return;
        void this.runTour(this.resumeAt, ep, { bridge: true });
        return;
      }
      if (this.tourTrack) { void this.finishTour(this.tourTrack, ep); return; }
      this.startNext(ep);
      return;
    }
    if (a === "repeat") {
      const lb = this.lastBeat;
      if (this.tourTrack && lb) {
        this.paused = false;
        void this.runTour({ ...lb }, ep, { bridge: false });
        return;
      }
      if (this.lastSaid) { this.set({ phase: "answering" }); await this.sayText(this.lastSaid, ep, undefined, false); }
      if (this.alive(ep)) this.afterAnswer(ep);
      return;
    }
    if (a === "prev") {
      const base = this.lastBeat ?? this.resumeAt;
      if (this.tourTrack && base && base.track) {
        this.paused = false;
        void this.runTour({ ...base, i: Math.max(0, base.i - 1), b: 0 }, ep, { bridge: true });
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
      this.tourTrack = null;
      this.resumeAt = null;
      this.paused = false;
      this.set({ stepNo: 0, stepTotal: 0, target: null });
      this.lastAsked = true;
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
    this.holdPoint();
  }

  /** Рамка вокруг показанного элемента держится ещё несколько секунд после ответа. */
  private holdPoint() {
    const sel = this.ui.target;
    if (!sel || !sel.startsWith("text:")) return;
    window.clearTimeout(this.pointTimer);
    this.pointTimer = window.setTimeout(() => {
      this.pointTimer = 0;
      if (this.ui.target === sel && !this.pos) this.set({ target: null });
    }, POINT_HOLD_MS);
  }

  /** После ответа: Настя сама дальше не идёт. Спросила — ждёт ответа; посреди обзора — спрашивает «Продолжаем?». */
  private afterAnswer(ep: number) {
    if (this.paused) { this.waitFor(null, ep, null); return; }
    if (this.lastAsked) { this.waitFor("answer", ep, this.resumeAt ? "remind" : null); return; }
    if (this.resumeAt) { void this.askContinue(ep); return; }
    if (this.tourTrack) { void this.finishTour(this.tourTrack, ep); return; }
    this.waitFor(null, ep, null);
  }

  /** «Продолжаем обзор?» / «Переходим к работодателю?» — и ждать ответа. */
  private async askContinue(ep: number) {
    const next = this.resumeAt;
    const cab = next ? STEPS[next.ids[next.i]]?.cabinet : null;
    const key = cab && this.lastCabinet && cab !== this.lastCabinet ? `continue_${cab}` : "continue";
    const q = this.phrase(key) || this.phrase("continue");
    this.set({ phase: "answering", click: null });
    await sleep(300);
    if (!this.alive(ep)) return;
    if (q && (await this.sayText(q, ep)) !== "done") return;
    if (!this.alive(ep)) return;
    this.remember("elena", q);
    this.lastAsked = true;
    this.waitFor("continue", ep, "remind");
  }

  /** Посмотрели экран не по порядку обзора — спросить, вернуться ли к обзору, и ждать. */
  private async askDetourBack(ep: number) {
    const q = this.phrase("back_to_tour");
    this.set({ phase: "answering", click: null });
    if (q && (await this.sayText(q, ep)) !== "done") return;
    if (!this.alive(ep)) return;
    this.remember("elena", q);
    this.lastAsked = true;
    this.pendingBridge = this.phrase("back_tour") || null;
    this.waitFor("detour", ep, "remind");
  }

  /** «Дальше», когда обзора нет: следующая сторона платформы после законченной — или весь сайт с начала. */
  private startNext(ep: number) {
    const last = this.lastTrack;
    const go = (track: TourTrack, from = 0) => {
      this.tourTrack = track;
      void this.runTour({ ids: TRACKS[track], track, i: from, b: 0 }, ep, { bridge: true, named: false });
    };
    if (last === "candidate") go("employer");
    else if (last === "employer") go("fsp");
    else if (last === "fsp") go("all", TRACKS.all.indexOf("warroom"));
    else if (!last) go("all");
    else this.waitFor(null, ep, null);
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
  private async enter(step: TourStep, ep: number, bridge: string | null): Promise<boolean> {
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
    await this.waitEl(step.selector, ep, 2500);
    const b = await bridgeDone;
    return this.alive(ep) && b !== "aborted";
  }

  /** После реплики-перехода («Открою …» с нажатием) — дать странице перейти; не перешла — откроет следующий шаг. */
  private async settleLead(leadId: string, ep: number) {
    const lead = STEPS[leadId];
    if (!lead) return;
    const t0 = performance.now();
    while (this.alive(ep) && performance.now() - t0 < 1500) {
      if (this.onScreen(lead)) return;
      await sleep(90);
    }
  }

  /** Блок — в кадр: ждём, пока раскладка устоится (над блоком догружаются карточки), и ставим блок в верхнюю часть
   *  экрана под закреплённой шапкой (внизу справа — окно Насти). Новый вызов отменяет прошлый (без «перетягивания»). */
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

  /** Окно между экранами: микрофон открыт ~1 с; человек заговорил — ждём его ход (новая линия обрывает обзор). */
  private async listenWindow(ep: number) {
    this.set({ phase: "listening", click: null });
    const t0 = performance.now();
    for (;;) {
      if (!this.alive(ep)) return;
      const el = performance.now() - t0;
      const busy = !!this.buf.read() || this.ui.userTalking || performance.now() - this.lastSpeechStart < 1500;
      if (el >= WINDOW_MS && !busy) return;
      if (el >= WINDOW_MS + WINDOW_MAX_WAIT_MS && !this.buf.read()) return;   // речь без слов (шум) — идём дальше
      await sleep(60);
    }
  }

  /** Основной цикл обзора: шаг за шагом, реплика за репликой. single — показать один экран («покажи …»). */
  private async runTour(start: Pos, ep: number, opts: { bridge: boolean; named?: boolean; single?: boolean }) {
    const sc = this.script;
    if (!sc || !this.alive(ep)) return;
    const { ids, track } = start;
    this.paused = false;
    this.awaiting = null;
    this.clearWait();
    if (!opts.single) { this.resumeAt = null; this.tourTrack = track; }
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
          this.resumeAt = { ids, track, i, b: 0 };
          this.pos = null;
          this.set({ phase: "answering", target: null, click: null });
          await sleep(250);
          if (!this.alive(ep)) return;
          if ((await this.sayText(q, ep)) !== "done" || !this.alive(ep)) return;
          this.remember("elena", q);
          this.lastAsked = true;
          this.waitFor("checkin", ep, "remind_checkin");
          return;
        }
      }
      this.pos = { ids, track, i, b: b0 };
      this.curStep = step.id;
      this.prefetchFrom(ids, i + 1);
      this.set({ phase: "touring", track, stepNo: track ? i + 1 : 0, stepTotal: track ? ids.length : 0 });
      let bridge = prevCab !== step.cabinet ? this.bridgeText(step.cabinet, firstBridge, !!opts.named) : null;
      if (bridge) firstBridge = false;   // главная без связки — «Начнём со стороны кандидата» звучит на первом кабинете
      if (i === start.i) {
        if (!bridge && !opts.single && this.pendingBridge) bridge = this.pendingBridge;   // «Продолжаю.» / «Возвращаюсь к обзору.»
        this.pendingBridge = null;
      }
      const ok = await this.enter(step, ep, bridge);
      if (!this.alive(ep) || !ok) return;
      prevCab = step.cabinet;
      this.lastCabinet = step.cabinet;     // связка раздела прозвучала — при продолжении не повторяется
      if (b0 === 0) this.post("step", { step: step.id });
      this.shownSteps.add(step.id);
      for (let b = b0; b < lines.length; b++) {
        if (!this.alive(ep)) return;
        const beat = step.beats[b] ?? step.beats[step.beats.length - 1] ?? { target: step.selector };
        // реплика-переход («Открою …» с нажатием) — только если следующий шаг обзора именно туда
        if (beat.lead && (opts.single || ids[i + 1] !== beat.lead)) continue;
        const target = beat.target ?? step.selector;
        this.pos = { ids, track, i, b };
        this.lastBeat = this.pos;
        this.set({ target, click: null });
        void this.bringIntoView(target, ep);   // прокрутка идёт вместе с началом реплики — без пауз
        await sleep(140);
        if (!this.alive(ep)) return;
        const res = await this.sayText(lines[b], ep, (u, total) => { this.stepUtter = u; this.planClick(beat, u, total, ep); });
        this.stepUtter = null;
        if (res === "aborted" || !this.alive(ep)) return;
        if (beat.lead) await this.settleLead(beat.lead, ep);
        if (!this.alive(ep)) return;
        await sleep(b < lines.length - 1 ? BEAT_GAP_MS : 200);
      }
      if (opts.single) break;
      // окно для реплики человека — между экранами одного раздела (перед сменой раздела будет вопрос)
      const nextStep = STEPS[ids[i + 1] ?? ""];
      if (!this.noMic && track && nextStep && nextStep.cabinet === step.cabinet) {
        this.resumeAt = { ids, track, i: i + 1, b: 0 };
        this.pos = null;
        await this.listenWindow(ep);
        if (!this.alive(ep)) return;           // человек заговорил — его ход в работе, обзор продолжится с resumeAt
        this.resumeAt = null;
      }
    }
    if (!this.alive(ep)) return;
    this.pos = null;
    if (opts.single) {
      this.set({ stepNo: 0, stepTotal: 0, click: null });
      if (this.resumeAt) { void this.askDetourBack(ep); return; }
      window.clearTimeout(this.pointTimer);
      this.pointTimer = window.setTimeout(() => { this.pointTimer = 0; if (!this.pos) this.set({ target: null }); }, 2500);
      if (this.tourTrack) { void this.finishTour(this.tourTrack, ep); return; }
      this.waitFor(null, ep, null);
      return;
    }
    if (track) await this.finishTour(track, ep);
  }

  private async finishTour(track: TourTrack, ep: number) {
    this.tourTrack = null;
    this.resumeAt = null;
    this.pos = null;
    this.paused = false;
    this.set({ phase: "answering", target: null, click: null, stepNo: 0, stepTotal: 0 });
    const done = this.phrase(`done_${track}`) || this.phrase("done_all");
    await this.sayText(done, ep);
    if (!this.alive(ep)) return;
    this.remember("elena", done);
    this.lastTrack = track;
    this.lastAsked = false;
    this.set({ track: null });
    this.waitFor(null, ep, null);
  }
}
