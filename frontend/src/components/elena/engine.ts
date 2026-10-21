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
import { SpeechBuffer, hasStopWord, isBackchannel, isEcho, words } from "../voice/live/turns";
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
  /** Чего ждёт Настя: start — «кто вы?» в знакомстве (окно показывает кнопки ролей); null — ничего особенного. */
  awaiting: Awaiting;
  /** Как слушает: wake — только «Настя …» (и короткие команды, когда молчит); open — любой ответ (она спросила). */
  listen: "wake" | "open";
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
  /** Проверки без микрофона: считать микрофон включённым, реплики человека — текстом через injectUser(). */
  fakeMic?: boolean;
  /** Сравнение губ (?elena_lips=1): мелкая ровная подача звука в поток — куски 100 мс, опережение 1,2 с. */
  lips?: boolean;
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
  dir?: string | null;
  /** start_tour: регистрацию первым актом пропустить (явное «кабинет», «сразу», вторая роль в разговоре). */
  skip_reg?: boolean | null;
  /** resume со стоящей регистрации — к следующему шагу (кабинет). */
  skip_now?: boolean | null;
}

interface Pos { ids: string[]; track: TourTrack | null; i: number; b: number }

const RATE = 24000;
const BYTES_PER_MS = (RATE * 2) / 1000;
const PIPE_MS = 650;               // звук из видеопотока звучит примерно через столько после отправки
const REMIND_AFTER_MS = 25000;     // спросила и ждёт: одно короткое напоминание, потом просто ждёт
const IDLE_CLOSE_MS = 120000;      // после напоминания никто не ответил — прощается и закрывается (минуты видеопотока)
const IDLE_FREE_MS = 180000;       // свободное ожидание без вопроса (обзор закончен) — дольше
const FILLER_AFTER_MS = 3000;      // модель думает дольше — короткая связка; обычные ответы (1,5–2,5 с) без неё
const STALE_INTERIM_MS = 2600;     // промежуточный текст не меняется — считаем фразу законченной
const LOOKAHEAD_MS = 4500;         // звук в видеопоток — с запасом: подвисание страницы при переходе не рвёт фразу
const GATE_AFTER_SPEECH_MS = 450;  // микрофон открывается через столько после конца её фразы (хвост из динамиков)
const GATE_TAIL_IGNORE_MS = 250;   // текст, пришедший сразу после открытия микрофона, — хвост её голоса
const BEAT_GAP_MS = 650;           // пауза между репликами обзора — спокойный темп, не «тараторит»
const BARGE_FINAL_WORDS = 2;       // законченный сегмент распознавания из стольких слов — тоже перебивание
const ALL_TRACK_MAX_BEATS = 3;     // обзор всего сайта — не больше стольких реплик на экран (подробно — обзор роли)
// Экскурсовод не стоит молча: каждый её вопрос по ходу показа ждёт ответа ограниченно и сам продолжается.
const HAND_WAIT_MS = 9000;         // «подняли руку» (пробел) и молчат — продолжает показ
const LLM_Q_WAIT_MS = 20000;       // Настя сама задала вопрос (модель) — ждёт ответа дольше
// Перебивание — только по имени (решение владельца 21.10): пока Настя говорит или ждёт, она реагирует на «Настя …»;
// без имени, когда молчит, — только короткие команды («дальше», «стоп», «назад»); спросила сама — любой ответ.
// Пауз между экранами и вопросов «Продолжаем?» нет: показ идёт подряд, после перебивания ждёт «дальше».
const WAKE = /(?:^|[^а-яё])(?:наст(?:я|ь|енька|юша|ен|ю)|анастаси[а-яё]*)(?=$|[^а-яё])/iu;
const QUIET_COMMAND = /^(?:(?:ну|так|давай|давайте|хорошо|ок)\s+)?(?:дальше|продолж[а-яё]*|поехали|идем дальше|стоп|стой|пауза|подожди[а-яё]*|назад|повтори[а-яё]*|пропусти[а-яё]*|вернись[а-яё]*)$/u;
const WAKE_OPEN_MS = 8000;         // после «Настя» столько слушает просьбу без имени
const WAKE_ONLY_END_MS = 1800;     // сказали только «Настя» — ждём продолжения фразы чуть дольше
const RESUME_AFTER_MS = 15000;     // после ответа или экрана по просьбе: тишина столько — продолжает показ сама

/** Текст после обращения «Настя» (обращение и знаки после него убраны); без обращения — как есть. */
export function stripWake(text: string): string {
  const m = WAKE.exec(text);
  if (!m) return text.trim();
  return text.slice(m.index + m[0].length).replace(/^[\s,.!?:;—-]+/u, "").trim();
}
const SCROLL_STEP = 0.75;          // «ниже» — на столько высоты окна
const START_REMIND_MS = 12000;     // знакомство: ждём ответа столько, потом короткое напоминание
const START_DEFAULT_MS = 20000;    // после напоминания молчат — начинает с кабинета кандидата
const SOFT_STOP_MAX_MS = 2600;     // перебили — договаривает до ближайшей границы предложения, если она не дальше этого
const USER_NAV_GRACE_MS = 1800;    // переход по сайту позже этого после её собственного перехода — сделал человек
const POINT_HOLD_MS = 6000;
const REPEAT_IF_HEARD_LESS = 0.35;   // перебили позже трети фразы — продолжаем со следующей, не повторяем
const NAME_KEY = "draft.elena.name";          // прежнее хранение имени между визитами — больше не используется, только чистим
const OLD_NAME_KEY = "draft.concierge.name";
let nameInTab: string | null = null;           // имя собеседника — до перезагрузки страницы

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

export type Awaiting = "start" | "checkin" | "continue" | "detour" | "answer" | null;

// Конец хода собеседника: сколько ждать тишины после окончательного сегмента распознавания (поставщик уже выждал
// ~0,7 с). Незаконченная мысль («и», «а можно», «потому что») — долго; короткая команда — быстро.
const UNFINISHED_END = /(?:^|\s)(и|а|но|или|что|чтобы|потому|поэтому|если|когда|как|это|ну|вот|например|то есть|типа|в|на|с|по|для|из|от|к|у|о|об|про|за|который|которая|которые|можно|мне|я|так|значит|подожди|подождите|слушай|смотри|тут|здесь|там|сейчас|допустим|скажи|скажите|пожалуйста|вот тут|смотрите|э+|м+)$/u;
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

/** Высота нижней панели навигации кабинетов на телефоне (--mobile-tabbar-h на documentElement; 0 — панели нет). */
export function tabbarInset(): number {
  try {
    const n = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--mobile-tabbar-h").trim());
    return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
  } catch { return 0; }
}

/** Заголовки блоков экрана (h2/h3 и подписи групп) с положением — для «ниже/выше» и для ответов по блоку. */
function sectionHeads(): { el: HTMLElement; text: string; top: number; bottom: number }[] {
  const root = document.querySelector("main") ?? document.body;
  const out: { el: HTMLElement; text: string; top: number; bottom: number }[] = [];
  for (const el of Array.from(root.querySelectorAll<HTMLElement>("h2, h3, p.label, [aria-label] > h2"))) {
    if (el.closest("[data-testid=interactive-avatar-tour]")) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const t = norm(el.textContent).replace(/\s*[·•].*$/, "");
    if (!t || t.length > 70 || out.some((x) => x.text === t)) continue;
    out.push({ el, text: t, top: r.top, bottom: r.bottom });
  }
  return out;
}

/** Текст блока под заголовком (до следующего заголовка того же уровня), коротко. */
function sectionText(head: HTMLElement, max = 700): string {
  const sec = head.closest("section, .card, article, fieldset, [role='group']") as HTMLElement | null;
  const src = sec && sec.textContent && sec.textContent.length > head.textContent!.length + 20 ? sec : head.parentElement;
  return norm(src?.textContent).slice(0, max);
}

/** Что сейчас на экране — заголовок и видимые надписи (Настя отвечает «по экрану» и может показать элемент); query —
 *  реплика человека: если в ней есть слова заголовка блока, добавляем текст этого блока (ответ по существу). */
function screenSnapshot(query = ""): { title: string; items: string[]; focus?: { heading: string; text: string } } {
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
  let focus: { heading: string; text: string } | undefined;
  const qw = words(query.toLowerCase()).filter((w) => w.length >= 4).map((w) => w.slice(0, 5));
  if (qw.length) {
    let best: { score: number; head: { el: HTMLElement; text: string } } | null = null;
    for (const h of sectionHeads()) {
      const hw = words(h.text.toLowerCase()).map((w) => w.slice(0, 5));
      const score = qw.filter((w) => hw.some((x) => x.startsWith(w) || w.startsWith(x))).length;
      if (score > 0 && (!best || score > best.score)) best = { score, head: h };
    }
    if (best) focus = { heading: best.head.text, text: sectionText(best.head.el) };
  }
  return { title, items, ...(focus ? { focus } : {}) };
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
    target: null, click: null, canPause: false, stage: "large",   // знакомство — большое окно по центру, обзор — в углу
    awaiting: null, listen: "open",
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
  private doneSteps = new Set<string>();     // экраны, рассказанные до конца: при повторном обзоре — коротко, одной репликой
  private ducked = false;
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
  // экскурсовод: спросила — подождала — продолжила сама; перебили — договаривает предложение
  private autoTimer = 0;                // таймер самостоятельного продолжения после её вопроса
  private autoCfg: { ep: number; ms: number; run: () => void } | null = null;
  private softStopTimer = 0;            // отложенная остановка голоса на границе предложения
  private curUtter: Utterance | null = null;   // что звучит сейчас
  private curUtterMs = 0;
  private lastNavAt = 0;                // её собственный переход по сайту; переход позже — сделал человек
  private copilotHinted = false;        // подсказка «скажите «дальше» — продолжу» в режиме «ведёте вы» — один раз
  private wakeOpenUntil = 0;            // после «Настя» (или пробела) до этого момента слушает любую реплику
  private lastHeardAt = 0;              // последнее распознанное слово (даже не ей) — пока говорят, сама не продолжает

  constructor(private d: ElenaDeps) {
    this.voice = new Voice(d.avatar, d.lips ? { lookaheadMs: 1200, chunkBytes: 4800 } : { lookaheadMs: LOOKAHEAD_MS });
    try {
      this.userName = nameInTab;   // имя живёт только до перезагрузки страницы (решение владельца 21.10)
    } catch { this.userName = null; }
  }

  // ------------------------------------------------------------------ состояние для экрана

  private set(p: Partial<ElenaUi>) {
    if (this.closed) return;
    this.ui = { ...this.ui, ...p };
    this.ui.canPause = !!this.tourTrack;
    this.ui.awaiting = this.awaiting;
    this.d.onUi(this.ui);
  }

  getUi(): ElenaUi { return this.ui; }
  micLevel(): number { return this.gated ? 0 : this.listener?.level() ?? 0; }
  isMuted(): boolean { return this.listener?.isMuted() ?? false; }
  /** Кнопка «развернуть / в угол». */
  setStage(stage: Stage) { this.set({ stage }); }

  /** Микрофон закрыт: Настя думает, только что договорила (хвост из динамиков) или занята переходом. Открыт — когда
   *  слушает, и пока она говорит в обзоре или отвечает: несколько слов не из её текста — перебивание (эхо и «угу» отсекаются). */
  private micGated(): boolean {
    if (this.closed || this.thinking) return true;
    if (performance.now() < this.gateUntil && !this.buf.read()) return true;   // человек уже говорит — не закрываем
    const ph = this.ui.phase;
    if (ph === "listening" || ph === "paused") return false;
    if (this.voice.speaking() && (ph === "touring" || ph === "answering")) return false;
    return true;
  }

  /** Слушает ли любую реплику (open) или только «Настя …» и короткие команды (wake). Open — сразу после «Настя» или
   *  пробела, в знакомстве и когда Настя сама задала вопрос. */
  private listenOpen(): boolean {
    if (performance.now() < this.wakeOpenUntil) return true;
    if (this.awaiting === "start") return true;
    return this.awaiting === "answer" && this.lastAsked;
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
      const listen = !s && !this.thinking && this.listenOpen() ? "open" : "wake";
      if (listen !== this.ui.listen) this.set({ listen });
      if (this.ducked && (!s || !this.buf.read())) { this.ducked = false; this.voice.duck(false); }
    }, 100);
  }

  // ------------------------------------------------------------------ стенограмма

  private post(type: "open" | "say" | "step" | "close" | "mic" | "point" | "barge" | "hand" | "nav" | "auto", extra: { text?: string; step?: string | null } = {}) {
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
    nameInTab = name;
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
    return this.voice.say(text, pcm, RATE, (u) => { this.curUtter = u; this.curUtterMs = total; onStart?.(u, total); });
  }

  /** Через сколько мс замолчать, чтобы не рвать предложение: конец реплики или ближайшая граница предложения
   *  (оценка по доле текста), если она не дальше SOFT_STOP_MAX_MS; иначе — сразу. */
  private softStopDelay(): number {
    const u = this.curUtter;
    if (!u || !this.voice.speaking()) return 0;
    const total = this.curUtterMs || u.durationMs;
    if (!total) return 0;
    const p = Math.min(1, Math.max(0, u.progress()));
    const remain = (1 - p) * total;
    if (remain <= SOFT_STOP_MAX_MS) return Math.max(0, remain);
    const t = u.text;
    const L = t.length || 1;
    for (const re of [/[.!?…;]+(?=\s|$)/g, /\s[—–]\s|,\s/g]) {
      let m: RegExpExecArray | null;
      while ((m = re.exec(t))) {
        const dt = ((m.index + m[0].length) / L - p) * total;
        if (dt >= 120 && dt <= SOFT_STOP_MAX_MS) return dt;
      }
    }
    return 0;
  }

  /** Замолчать: сразу (delay 0) или договорив до границы предложения. Новая реплика ждёт этой остановки. */
  private stopVoice(delay: number) {
    window.clearTimeout(this.softStopTimer);
    this.softStopTimer = 0;
    if (delay <= 0 || !this.voice.speaking()) { this.voice.stop(); return; }
    this.softStopTimer = window.setTimeout(() => { this.softStopTimer = 0; this.voice.stop(); }, delay);
  }

  private async softStopSettled() {
    while (this.softStopTimer && !this.closed) await sleep(40);
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
    if (track) this.set({ stage: "corner" });   // запуск сразу с обзора — без большого окна
    if (this.d.fakeMic) {
      this.set({ mic: "on" });
      this.micKnown = Promise.resolve<MicState>("on");
    } else if (liveSttSupported()) {
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
        nameInTab = this.userName;
        try { localStorage.removeItem(NAME_KEY); sessionStorage.removeItem(OLD_NAME_KEY); } catch { /* старые записи */ }
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
    const mic: MicState = this.d.fakeMic ? "on" : this.listener?.getState() ?? "error";
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
    // спросила (имя или кто пришёл) — ждёт ответа; долго молчат — напоминает, потом начинает с кандидата
    this.lastAsked = true;
    this.waitStart(ep);
  }

  /** Ожидание в знакомстве (имя, «кто вы?»): напоминание через 12 с, ещё через 20 с — сама начинает кабинет кандидата. */
  private waitStart(ep: number) {
    this.waitFor("start", ep, "remind_start", {
      remindMs: START_REMIND_MS,
      auto: { ms: START_REMIND_MS + START_DEFAULT_MS, run: () => void this.defaultStart(ep) },
    });
  }

  private async defaultStart(ep: number) {
    const t = this.phrase("default_role");
    this.set({ phase: "answering" });
    if (t) {
      if ((await this.sayText(t, ep)) !== "done" || !this.alive(ep)) return;
      this.remember("elena", t);
    }
    this.lastAsked = false;
    this.tourTrack = "candidate";
    void this.runTour({ ids: TRACKS.candidate, track: "candidate", i: 0, b: 0 }, ep, { bridge: true, named: true });
  }

  close() {
    if (this.closed) return;
    this.clearTyped();
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
    this.clearTyped();
    this.awaiting = null;
    this.set({ phase: "paused", click: null });
  }

  /** Для проверок без микрофона (window.__elena.say): реплика собеседника текстом. */
  injectUser(text: string) {
    if (this.closed || !text.trim()) return;
    this.buf.reset();
    void this.runTurn(text.trim());
  }

  /** Для проверок: событие распознавания как от микрофона (перебивание, эхо, окна между экранами). */
  injectStt(e: SttEvent) { this.onStt(e); }

  /** Для проверок (window.__elena.hear): «произнести» фразу как собеседник — слово за словом, как присылает распознавание. */
  async hear(text: string, wordMs = 220) {
    const w = text.trim().split(/\s+/).filter(Boolean);
    if (!w.length) return;
    this.onStt({ type: "speech_started" });
    for (let i = 1; i <= w.length; i++) { await sleep(wordMs); this.onStt({ type: "interim", text: w.slice(0, i).join(" ") }); }
    await sleep(wordMs);
    this.onStt({ type: "final", text: w.join(" "), speech_final: true });
  }

  // ------------------------------------------------------------------ таймеры и ожидание

  /** Потолок разговора: минуты видеопотока платные — по истечении Настя договаривает фразу, прощается и закрывается. */
  private armTimeUp(minutes: number | undefined) {
    window.clearTimeout(this.timeUpTimer);
    const m = Number(minutes) || 0;
    if (m <= 0) return;   // без потолка (по умолчанию): разговор длится, сколько нужно; долгое молчание закрывает само
    const ms = m * 60000 - (performance.now() - this.startedAt);
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
    for (const t of [this.endTimer, this.staleTimer, this.remindTimer, this.idleTimer, this.clickTimer, this.pointTimer, this.autoTimer]) window.clearTimeout(t);
    this.endTimer = this.staleTimer = this.remindTimer = this.idleTimer = this.clickTimer = this.pointTimer = this.autoTimer = 0;
  }

  private armAuto(ms: number) {
    window.clearTimeout(this.autoTimer);
    const cfg = this.autoCfg;
    if (!cfg) return;
    const fire = () => {
      this.autoTimer = 0;
      if (!this.alive(cfg.ep) || this.autoCfg !== cfg) return;
      if (this.userBusy()) { this.autoTimer = window.setTimeout(fire, 1200); return; }
      this.autoCfg = null;
      this.post("auto", { text: this.awaiting ?? "" });
      cfg.run();
    };
    this.autoTimer = window.setTimeout(fire, ms);
  }

  private clearWait() {
    window.clearTimeout(this.remindTimer); window.clearTimeout(this.idleTimer); window.clearTimeout(this.autoTimer);
    this.remindTimer = this.idleTimer = this.autoTimer = 0;
  }

  /** Человек что-то говорит или его ход в работе — Настя сама ничего не начинает. */
  private userBusy(): boolean {
    return !!this.buf.read() || this.ui.userTalking || this.thinking || this.voice.speaking()
      || performance.now() - this.lastSpeechStart < 1500 || performance.now() - this.lastHeardAt < 1500;
  }

  /** Настя сказала своё и ждёт: микрофон открыт. kind — чего ждёт (уходит на сервер). Одно напоминание через 25 с,
   *  при долгом молчании — прощается и закрывается. */
  private waitFor(kind: Awaiting, ep: number, remindKey: string | null, opts: { remindMs?: number; auto?: { ms: number; run: () => void } } = {}) {
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
      }, opts.remindMs ?? REMIND_AFTER_MS);
    }
    // экскурсовод не ждёт вечно: молчат — продолжает сама (человек заговорил — ждём его ход; оказалось шумом — снова таймер)
    this.autoCfg = opts.auto ? { ep, ms: opts.auto.ms, run: opts.auto.run } : null;
    if (this.autoCfg) this.armAuto(this.autoCfg.ms);
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
      if (!this.buf.read() && !this.listenOpen()) return;   // ещё неизвестно, к ней ли — таймеры не трогаем
      this.clearWait();
      if (this.autoCfg && this.autoCfg.ep === this.ep) this.armAuto(3500);   // заговорил — ждём; слов не будет — продолжит сама
      // человек снова заговорил, пока ждём конца хода, — подождать ещё
      if (this.endTimer && this.buf.read()) this.armEnd(900);
      return;
    }
    if (e.type === "interim" || e.type === "final") {
      const text = e.text.trim();
      if (!text) return;
      if (!this.voice.speaking()) this.lastHeardAt = performance.now();
      if (performance.now() - this.gateOpenedAt < GATE_TAIL_IGNORE_MS && !this.buf.read()) return;
      const hers = this.voice.echoText();
      if (hers && !this.buf.read()) {
        // под её речь (и сразу после): её же слова из динамиков — эхо; «угу», «ага» — поддакивание, не реплика
        if (isEcho(text, hers)) return;
        if (isBackchannel(text) && !hasStopWord(text)) return;
      }
      if (!this.buf.read()) {
        // к ней обращаются по имени; без имени — только короткая команда, когда она молчит; спросила сама — любой ответ
        const busy = this.voice.speaking() || this.thinking || !!this.softStopTimer;
        if (busy || !this.listenOpen()) {
          const wake = !(busy && hers && /наст/i.test(hers)) && WAKE.test(text);
          const quiet = !busy && words(text).length <= 4 && QUIET_COMMAND.test(words(text).join(" "));
          if (!wake && !quiet) return;
          if (wake) this.onWake(text);
        }
      }
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

  /** «Настя …» — замолкает сразу и слушает просьбу (WAKE_OPEN_MS); прерванный показ продолжится с resumeAt. */
  private onWake(text: string) {
    this.wakeOpenUntil = performance.now() + WAKE_OPEN_MS;
    if (!(this.voice.speaking() || this.thinking || this.softStopTimer)) { this.post("barge", { text: `${text} | имя` }); return; }
    this.ep++;
    this.clearWait();
    window.clearTimeout(this.clickTimer); window.clearTimeout(this.pointTimer);
    this.clickTimer = this.pointTimer = 0;
    if (this.pos) this.resumeAt = this.advance(this.pos, this.stepUtter ? this.stepUtter.progress() : 1);
    this.pos = null;
    this.stepUtter = null;
    this.turnCtl?.abort();
    this.turnCtl = null;
    this.thinking = false;
    this.ducked = false;
    this.voice.duck(false);
    this.stopVoice(0);
    this.set({ phase: "listening", click: null });
    this.post("barge", { text: `${text} | имя` });
  }

  /** Кнопка «Поднять руку» (и пробел): Настя договаривает предложение и слушает; молчат — продолжает показ сама. */
  raiseHand() {
    if (this.closed || this.noMic) return;
    if (this.paused) { this.togglePause(); return; }
    const ep = ++this.ep;
    this.clearTimers();
    if (this.pos) this.resumeAt = this.advance(this.pos, this.stepUtter ? this.stepUtter.progress() : 1);
    this.pos = null;
    this.stepUtter = null;
    this.turnCtl?.abort();
    this.turnCtl = null;
    this.thinking = false;
    this.stopVoice(this.softStopDelay());
    this.wakeOpenUntil = performance.now() + HAND_WAIT_MS;
    this.post("hand");
    this.lastAsked = true;
    this.waitFor(this.resumeAt ? "continue" : "answer", ep, null, this.resumeAt
      ? { auto: { ms: HAND_WAIT_MS, run: () => this.autoResume(ep) } } : {});
  }

  /** Человек сам перешёл по сайту (меню, ссылка): режим «ведёте вы» — Настя доводит предложение, коротко говорит,
   *  что это за экран, и дальше не ведёт, пока не попросят «дальше». Вызывается из окна при смене адреса. */
  onPathChange(path: string) {
    if (this.closed || !this.script) return;
    if (performance.now() - this.lastNavAt < USER_NAV_GRACE_MS) return;   // это её переход
    const ph = this.ui.phase;
    if (ph === "idle" || ph === "connecting" || ph === "greeting" || ph === "thinking") return;
    const step = Object.values(STEPS).find((s) => (s.match ? s.match.test(path) : s.path === path));
    if (!step || step.id === this.curStep) return;
    const ep = ++this.ep;
    this.clearTimers();
    if (this.pos) this.resumeAt = this.advance(this.pos, this.stepUtter ? this.stepUtter.progress() : 1);
    this.pos = null;
    this.stepUtter = null;
    this.turnCtl?.abort();
    this.turnCtl = null;
    this.thinking = false;
    this.stopVoice(this.softStopDelay());
    this.post("nav", { text: path, step: step.id });
    void this.copilot(step, ep);
  }

  private async copilot(step: TourStep, ep: number) {
    await this.softStopSettled();
    if (!this.alive(ep)) return;
    this.curStep = step.id;
    this.set({ stage: "corner", phase: "answering", target: null, click: null, stepNo: 0, stepTotal: 0 });
    const first = this.linesOf(step.id)[0];
    const hint = !this.copilotHinted ? this.phrase("copilot_hint") : "";
    if (first) {
      const target = step.beats[0]?.target ?? step.selector;
      this.set({ target });
      void this.bringIntoView(target, ep);
      await sleep(300);
      if (!this.alive(ep)) return;
      if ((await this.sayText(first, ep)) !== "done" || !this.alive(ep)) return;
      this.shownSteps.add(step.id);
    }
    if (hint) {
      this.copilotHinted = true;
      if ((await this.sayText(hint, ep)) !== "done" || !this.alive(ep)) return;
      this.remember("elena", hint);
    }
    this.lastAsked = false;
    this.paused = !!this.tourTrack;      // обзор не продолжается сам, пока человек ходит по сайту
    this.waitFor(null, ep, null);
  }

  /** Молчание после её вопроса по ходу показа — продолжает с того же места (короткая связка «Идём дальше.»). */
  private autoResume(ep: number) {
    if (!this.alive(ep)) return;
    this.lastAsked = false;
    this.paused = false;
    if (this.resumeAt) {
      this.pendingBridge = this.pendingBridge || this.phrase("go_on") || this.phrase("resume_tour") || null;
      void this.runTour(this.resumeAt, ep, { bridge: true });
      return;
    }
    if (this.tourTrack) { void this.finishTour(this.tourTrack, ep); return; }
    this.waitFor(null, ep, null);
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
    const delay = !stripWake(text) ? WAKE_ONLY_END_MS : Math.max(250, guideDelay(stripWake(text)) + extra);
    this.endTimer = window.setTimeout(() => {
      this.endTimer = 0;
      if (this.buf.version === v) this.submit();
    }, delay);
  }

  private submit() {
    window.clearTimeout(this.staleTimer);
    const raw = this.buf.take();
    this.set({ userTalking: false });
    if (!raw) return;
    const text = stripWake(raw);
    if (!text) {
      // сказали только «Настя» — замолчала и слушает; просьбы нет — продолжит показ сама
      const ep = this.ep;
      this.lastAsked = false;
      this.waitFor(this.resumeAt ? "continue" : null, ep, null,
        this.resumeAt ? { auto: { ms: RESUME_AFTER_MS, run: () => this.autoResume(ep) } } : {});
      return;
    }
    // «угу» в окне между экранами, когда Настя ни о чём не спрашивала, — не реплика
    if (isBackchannel(text) && words(text).length <= 1 && !this.awaiting && !this.paused) return;
    // одно случайное слово под её речь (не «стоп», не имя) — не перебивание и не ход
    if (this.voice.speaking() && words(text).length < BARGE_FINAL_WORDS && !hasStopWord(text)) return;
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
    this.stopVoice(this.softStopDelay());   // если ещё говорит — договаривает предложение, ответ тем временем готовится
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
          history: this.history.slice(-8), session_id: this.sid, screen: screenSnapshot(text), last_said: this.lastSaid.slice(0, 600),
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
            await this.softStopSettled();
            if (!this.alive(ep)) throw new DOMException("stale", "AbortError");
            utter = this.voice.begin(meta?.text ?? "", RATE);
            this.curUtter = utter;
            this.curUtterMs = 0;
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
    if (!this.alive(ep) || !this.thinking || this.voice.speaking() || this.softStopTimer || !fl.length) return;
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
    const first = meta.action === "start_tour" ? TRACKS[this.roleOf(meta)] : null;
    const step = first ? (first[meta.skip_reg && first[0]?.endsWith("-register") ? 1 : 0] ?? first[0])
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
      if (meta.skip_reg && TRACKS[role][0]?.endsWith("-register")) {
        // «сразу кабинет», «без регистрации», вторая роль в разговоре — с экрана кабинета
        // связка «начнём с регистрации…» тут не к месту — ответ «открываю кабинет…» уже прозвучал
        this.lastCabinet = null;
        void this.runTour({ ids: TRACKS[role], track: role, i: 1, b: 0 }, ep, { bridge: false });
        return;
      }
      // ответ уже прозвучал («Покажу кабинет работодателя, начнём с регистрации») — связка раздела не дублирует его
      if (meta.text) this.lastCabinet = STEPS[TRACKS[role][0]]?.cabinet ?? this.lastCabinet;
      void this.runTour({ ids: TRACKS[role], track: role, i: 0, b: 0 }, ep, { bridge: !meta.text, named: false });
      return;
    }
    if (a === "goto" && meta.step && STEPS[meta.step]) {
      const fwd = this.forwardPos(meta.step);
      if (nav) await nav;
      if (!this.alive(ep)) return;
      this.paused = false;
      if (fwd) {
        // экран дальше по маршруту: показать его и ждать «дальше» (продолжит со следующего за ним) — человек ведёт
        this.pendingBridge = null;
        this.resumeAt = fwd.i + 1 < fwd.ids.length ? { ...fwd, i: fwd.i + 1, b: 0 } : null;
        if (this.shownSteps.has(meta.step)) { void this.showOnly(STEPS[meta.step], ep); return; }
        void this.runTour({ ids: [meta.step], track: null, i: 0, b: 0 }, ep, { bridge: false, single: true });
        return;
      }
      // экран не по порядку обзора (или обзора нет) — показать его одного; уже показывали — открыть и подсветить,
      // реплики сценария второй раз не звучат (ответ по существу уже прозвучал)
      if (this.shownSteps.has(meta.step)) { void this.showOnly(STEPS[meta.step], ep); return; }
      void this.runTour({ ids: [meta.step], track: null, i: 0, b: 0 }, ep, { bridge: false, single: true });
      return;
    }
    if (a === "point" && meta.point) {
      this.holdPoint();
      this.afterAnswer(ep);
      return;
    }
    if (a === "scroll") {
      if (nav) await nav;
      if (!this.alive(ep)) return;
      const dir = (["down", "up", "top", "bottom"] as const).find((d) => d === meta.dir) ?? "down";
      void this.scrollScreen(dir, ep, "");   // ответ (если был) уже прозвучал
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
    if (a === "resume" && meta.skip_now && this.resumeAt && this.resumeAt.ids[this.resumeAt.i]?.endsWith("-register")) {
      this.resumeAt = { ...this.resumeAt, i: this.resumeAt.i + 1, b: 0 };
      this.pendingBridge = null;
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
        void this.runTour({ ...lb }, ep, { bridge: false, detailed: true });
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
        void this.runTour({ ...base, i: Math.max(0, base.i - 1), b: 0 }, ep, { bridge: true, detailed: true });
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
      this.waitStart(ep);
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
    if (this.lastAsked) {
      // спросила посреди показа — ждёт ответа, но не вечно: молчат — продолжает показ
      this.waitFor("answer", ep, null, this.resumeAt ? { auto: { ms: LLM_Q_WAIT_MS, run: () => this.autoResume(ep) } } : {});
      return;
    }
    if (this.resumeAt) { void this.askContinue(ep); return; }
    if (this.tourTrack) { void this.finishTour(this.tourTrack, ep); return; }
    this.waitFor(null, ep, null);
  }

  /** Ответила посреди показа: короткая пауза для уточнения — и сама продолжает («Продолжаю.»). Перед другим разделом —
   *  вопрос «Переходим к работодателю?», но тоже без вечного ожидания. */
  private async askContinue(ep: number) {
    if (!this.onTourScreen()) { this.afterDetour(ep); return; }   // человек разбирается с экраном в стороне — не уводим
    // ответила посреди показа — ждёт «дальше» (без вопроса «Продолжаем?»); тишина — продолжает сама
    this.set({ phase: "listening", click: null });
    this.lastAsked = false;
    this.waitFor("continue", ep, null, { auto: { ms: RESUME_AFTER_MS, run: () => this.autoResume(ep) } });
  }

  /** Показала один экран по просьбе вне обзора — дальше ведёт по этому кабинету сама (короткий вопрос, молчат — идёт). */
  private async askAfterGoto(step: TourStep, ep: number) {
    const track = this.trackOf(step);
    const k = track ? TRACKS[track].indexOf(step.id) : -1;
    if (!track || k < 0 || k + 1 >= TRACKS[track].length) { this.waitFor(null, ep, null); return; }
    this.tourTrack = track;
    this.lastCabinet = step.cabinet;
    this.resumeAt = { ids: TRACKS[track], track, i: k + 1, b: 0 };
    await sleep(0);
    if (!this.alive(ep)) return;
    this.lastAsked = false;
    this.waitFor("continue", ep, null, { auto: { ms: RESUME_AFTER_MS, run: () => this.autoResume(ep) } });
  }

  /** Обзор какой роли продолжать после этого экрана. */
  private trackOf(step: TourStep): TourTrack | null {
    const cab = step.cabinet;
    const t: TourTrack | null = cab === "candidate" ? "candidate" : cab === "employer" ? "employer" : cab === "fsp" ? "fsp" : null;
    if (t && TRACKS[t].includes(step.id)) return t;
    return TRACKS.all.includes(step.id) ? "all" : null;
  }

  /** Человек ушёл в сторону от обзора (спросил, попросил экран, пролистал): остаёмся с ним. Молчим и слушаем 12 с,
   *  потом один раз «Продолжить показ?», и только после ещё 12 с тишины идём дальше («Возвращаюсь к обзору»). */
  private afterDetour(ep: number) {
    this.lastAsked = false;
    this.set({ phase: "listening", click: null });
    if (this.resumeAt) {
      this.pendingBridge = this.phrase("back_tour") || null;
      this.waitFor("detour", ep, null, { auto: { ms: RESUME_AFTER_MS, run: () => this.autoResume(ep) } });
      return;
    }
    this.waitFor(null, ep, null);
  }

  /** Экран обзора ли сейчас на виду (тогда после ответа можно скоро продолжить), или человек в стороне. */
  private onTourScreen(): boolean {
    const r = this.resumeAt;
    if (!r) return false;
    const cur = this.curStep ? STEPS[this.curStep] : null;
    const prevId = r.ids[Math.max(0, r.b > 0 ? r.i : r.i - 1)];
    return !!cur && (cur.id === prevId || cur.id === r.ids[r.i]);
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

  /** Её собственный переход по сайту (переходы человека отличаем по времени — режим «ведёте вы»). */
  private nav(to: string) {
    this.lastNavAt = performance.now();
    this.d.navigate(to);
  }

  /** Открыть экран шага: вход в нужную роль, переход, ожидание нужного блока; связка звучит, пока экран грузится. */
  private async enter(step: TourStep, ep: number, bridge: string | null): Promise<boolean> {
    const bridgeDone = bridge ? this.sayText(bridge, ep) : Promise.resolve<SayResult>("done");
    if (!this.onScreen(step)) {
      try {
        if (this.needLogin(step)) {
          const dest = await this.d.login(step.persona!, step.path);
          if (!this.alive(ep)) return false;
          this.nav(dest);
          if (step.resolve && dest === step.path) {
            const p = await step.resolve();
            if (!this.alive(ep)) return false;
            if (p && !(step.match?.test(this.d.path()))) this.nav(p);
          }
        } else {
          const p = step.resolve ? ((await step.resolve()) ?? step.path) : step.path;
          if (!this.alive(ep)) return false;
          this.nav(p);
        }
      } catch {
        if (!this.alive(ep)) return false;
        this.nav(step.path);
      }
    }
    await this.waitEl(step.selector, ep, 2500);
    const b = await bridgeDone;
    return this.alive(ep) && b !== "aborted";
  }

  /** Показ регистрации: набирает текст в поле по буквам в такт реплике (форма не отправляется). */
  private typed: HTMLInputElement[] = [];

  /** Очистить поля, в которые Настя печатала пример (регистрация): форма не уйдёт с примером почты. */
  private clearTyped() {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    for (const el of this.typed.splice(0)) {
      try {
        if (!el.isConnected) continue;
        if (setter) setter.call(el, ""); else el.value = "";
        el.dispatchEvent(new Event("input", { bubbles: true }));
      } catch { /* поле пропало */ }
    }
  }

  private async typeInto(t: { selector: string; text: string }, ep: number, totalMs: number) {
    const el = findTarget(t.selector) as HTMLInputElement | null;
    if (!el || typeof el.value !== "string") return;
    if (!this.typed.includes(el)) this.typed.push(el);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    const put = (v: string) => {
      if (setter) setter.call(el, v); else el.value = v;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    };
    try { el.focus({ preventScroll: true }); } catch { /* не важно */ }
    await sleep((this.d.avatar()?.live() ? PIPE_MS : 80) + 350);
    const per = Math.max(40, Math.min(110, (Math.max(totalMs, 1500) * 0.55) / Math.max(1, t.text.length)));
    for (let i = 1; i <= t.text.length; i++) {
      if (!this.alive(ep)) return;
      put(t.text.slice(0, i));
      await sleep(per);
    }
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
      const floor = window.innerHeight - tabbarInset();   // над нижней панелью навигации на телефоне
      const fits = r.top >= inset + 8 && r.top <= floor * 0.5 && r.bottom <= floor - 24;
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
      if (el) { this.lastNavAt = performance.now(); try { el.click(); } catch { /* блок пропал */ } }
    }, Math.max(0, at - performance.now()));
  }

  /** Какие реплики экрана звучат: реплика-переход — только если следующий шаг именно туда; на уже рассказанном экране
   *  (brief) — одна первая; в обзоре всего сайта — не больше ALL_TRACK_MAX_BEATS (подробности — в обзоре роли). */
  private beatPlan(step: TourStep, nextId: string | undefined, o: { single?: boolean; brief: boolean; cap: number }): number[] {
    const lines = this.linesOf(step.id);
    const plain: number[] = [];
    const leads: number[] = [];
    for (let b = 0; b < lines.length; b++) {
      const beat = step.beats[b];
      if (beat?.lead) { if (!o.single && !o.brief && nextId === beat.lead) leads.push(b); continue; }
      plain.push(b);
    }
    return [...plain.slice(0, o.brief ? 1 : o.cap), ...leads].sort((x, y) => x - y);
  }

  /** Основной цикл обзора: шаг за шагом, реплика за репликой. single — показать один экран («покажи …»);
   *  detailed — все реплики даже на уже рассказанном экране («повтори», «назад»). */
  private async runTour(start: Pos, ep: number, opts: { bridge: boolean; named?: boolean; single?: boolean; detailed?: boolean }) {
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
    const cap = track === "all" ? ALL_TRACK_MAX_BEATS : 99;
    // новый обзор уже рассказанного раздела — предупредить, что пройдём коротко
    if (!opts.single && !opts.detailed && start.b === 0 && this.doneSteps.has(ids[start.i]) && !this.pendingBridge
        && ids.slice(start.i, start.i + 3).every((id) => this.doneSteps.has(id))) {
      this.pendingBridge = this.phrase("again_brief") || null;
    }
    for (let i = Math.max(0, start.i); i < ids.length; i++) {
      if (!this.alive(ep)) return;
      const step = STEPS[ids[i]];
      if (!step) continue;
      const lines = this.linesOf(step.id);
      const b0 = i === start.i ? Math.min(start.b, Math.max(0, lines.length - 1)) : 0;
      const brief = !opts.single && !opts.detailed && this.doneSteps.has(step.id) && b0 === 0;
      const plan = this.beatPlan(step, ids[i + 1], { single: opts.single, brief, cap }).filter((b) => b >= b0);
      this.pos = { ids, track, i, b: b0 };
      this.curStep = step.id;
      this.prefetchFrom(ids, i + 1);
      this.set({ phase: "touring", track, stepNo: track ? i + 1 : 0, stepTotal: track ? ids.length : 0, target: null, click: null });
      let bridge = prevCab !== step.cabinet ? this.bridgeText(step.cabinet, firstBridge, !!opts.named) : null;
      if (bridge) firstBridge = false;   // главная без связки — «Начнём со стороны кандидата» звучит на первом кабинете
      if (i === start.i) {
        // «Продолжаю.» / «Возвращаюсь к обзору.» — если связки раздела нет; «уже смотрели — пройду коротко» — вместо неё
        if (!opts.single && this.pendingBridge && (!bridge || this.pendingBridge === this.phrase("again_brief"))) bridge = this.pendingBridge;
        this.pendingBridge = null;
      }
      // связка раздела считается прозвучавшей с момента, как начала звучать: перебили на ней — при продолжении она
      // не повторяется «впервые» (стенограмма 21.10 11:13 — «Начнём с регистрации» дважды)
      prevCab = step.cabinet;
      this.lastCabinet = step.cabinet;
      const ok = await this.enter(step, ep, bridge);
      if (!this.alive(ep) || !ok) return;
      if (b0 === 0) this.post("step", { step: step.id });
      this.shownSteps.add(step.id);
      for (let k = 0; k < plan.length; k++) {
        const b = plan[k];
        if (!this.alive(ep)) return;
        const beat = step.beats[b] ?? step.beats[step.beats.length - 1] ?? { target: step.selector };
        const target = beat.target ?? step.selector;
        this.pos = { ids, track, i, b };
        this.lastBeat = this.pos;
        this.set({ target, click: null });
        void this.bringIntoView(target, ep);   // прокрутка идёт вместе с началом реплики — без пауз
        await sleep(140);
        if (!this.alive(ep)) return;
        const res = await this.sayText(lines[b], ep, (u, total) => {
          this.stepUtter = u;
          this.planClick(beat, u, total, ep);
          if (beat.type) void this.typeInto(beat.type, ep, total);
        });
        this.stepUtter = null;
        if (res === "aborted" || !this.alive(ep)) return;
        if (beat.lead) await this.settleLead(beat.lead, ep);
        if (!this.alive(ep)) return;
        await sleep(k < plan.length - 1 ? BEAT_GAP_MS : 200);
      }
      if (!opts.single && !brief && !(await this.walkRest(step, ep))) return;
      this.doneSteps.add(step.id);
      if (opts.single) break;
      // между экранами одного раздела: каждые несколько экранов — короткий вопрос и ожидание ответа, иначе — окно для реплики
      const nextStep = STEPS[ids[i + 1] ?? ""];
      if (!this.noMic && track && nextStep && nextStep.cabinet === step.cabinet) {
        // показ идёт подряд, без окон и вопросов: перебить можно словом «Настя» в любой момент
        this.resumeAt = { ids, track, i: i + 1, b: 0 };
        this.pos = null;
        await sleep(BEAT_GAP_MS);
        if (!this.alive(ep)) return;
        this.resumeAt = null;
      }
    }
    if (!this.alive(ep)) return;
    this.pos = null;
    if (opts.single) {
      this.set({ stepNo: 0, stepTotal: 0, click: null });
      if (this.resumeAt) { this.afterDetour(ep); return; }
      window.clearTimeout(this.pointTimer);
      this.pointTimer = window.setTimeout(() => { this.pointTimer = 0; if (!this.pos) this.set({ target: null }); }, 2500);
      if (this.tourTrack) { void this.finishTour(this.tourTrack, ep); return; }
      // обзора не было — экскурсовод не замолкает: предлагает пройти кабинет дальше и сама идёт
      const one = STEPS[ids[Math.max(0, start.i)]];
      if (one && !this.noMic) { void this.askAfterGoto(one, ep); return; }
      this.waitFor(null, ep, null);
      return;
    }
    if (track) await this.finishTour(track, ep);
  }

  /** Открыть уже показанный экран ещё раз: переход, подсветка главного блока — без повтора реплик сценария. */
  private async showOnly(step: TourStep, ep: number) {
    this.set({ phase: "answering", stepNo: 0, stepTotal: 0, click: null });
    const ok = await this.enter(step, ep, null);
    if (!ok || !this.alive(ep)) return;
    this.curStep = step.id;
    this.post("step", { step: step.id });
    const target = step.beats[0]?.target ?? step.selector;
    this.set({ target });
    void this.bringIntoView(target, ep);
    window.clearTimeout(this.pointTimer);
    this.pointTimer = window.setTimeout(() => { this.pointTimer = 0; if (!this.pos && this.ui.target === target) this.set({ target: null }); }, POINT_HOLD_MS);
    if (this.tourTrack && !this.resumeAt) { this.waitFor(null, ep, null); return; }
    this.afterDetour(ep);
  }

  /** «Ниже», «ещё ниже», «наверх»: пролистать экран и назвать блоки, которые появились. Дальше ведёт человек. */
  private async scrollScreen(dir: "down" | "up" | "top" | "bottom", ep: number, reply: string) {
    const h = window.innerHeight;
    const inset = topInset();
    const floor = h - tabbarInset();
    const inView = (x: { top: number; bottom: number }) => x.bottom > inset + 4 && x.top < floor - 4;
    const before = sectionHeads().filter(inView).map((x) => x.text);
    const maxY = Math.max(0, document.documentElement.scrollHeight - h);
    const y0 = window.scrollY;
    const y = dir === "top" ? 0 : dir === "bottom" ? maxY
      : Math.min(maxY, Math.max(0, y0 + (dir === "up" ? -1 : 1) * Math.round(h * SCROLL_STEP)));
    this.set({ phase: "answering", click: null });
    window.scrollTo({ top: y, behavior: "smooth" });
    await sleep(650);
    if (!this.alive(ep)) return;
    const heads = sectionHeads().filter(inView);
    const fresh = heads.map((x) => x.text).filter((t) => !before.includes(t)).slice(0, 3);
    const moved = Math.abs(window.scrollY - y0) > 8;
    let text = reply.trim();
    if (!text) {
      if (fresh.length) text = (this.phrase("scroll_more") || "Вот {items}.").replace("{items}", fresh.map((t) => `«${t}»`).join(", "));
      else if (!moved && (dir === "down" || dir === "bottom")) text = this.phrase("scroll_end");
      else if (!moved) text = this.phrase("scroll_top");
    }
    if (fresh.length) this.set({ target: `text:${fresh[0]}` });
    this.post("nav", { text: `scroll ${dir} → ${fresh.join(" | ") || (moved ? "без новых блоков" : "край")}` });
    if (text) {
      if ((await this.sayText(text, ep)) !== "done" || !this.alive(ep)) return;
      this.remember("elena", text);
    }
    this.holdPoint();
    if (this.tourTrack && this.resumeAt) { this.afterDetour(ep); return; }
    this.lastAsked = false;
    this.waitFor(null, ep, null);
  }

  /** После реплик сценария — долистать экран: назвать блоки ниже, о которых сценарий не сказал («Ещё на этом экране — …»).
   *  Говорит сначала, прокручивает по ходу фразы; блоки, уже описанные сценарием другими словами, не называет. */
  private async walkRest(step: TourStep, ep: number): Promise<boolean> {
    const h = window.innerHeight;
    const floor = h - tabbarInset();
    const below = sectionHeads().filter((x) => x.top >= floor - 4).slice(0, 4);
    if (!below.length) return true;
    const said = this.linesOf(step.id).join(" ").toLowerCase();
    const stems = (t: string) => words(t.toLowerCase()).filter((w) => w.length >= 4).map((w) => w.slice(0, 5));
    const saidStems = new Set(stems(said));
    const covered = (t: string) => { const st = stems(t); return st.length > 0 && st.filter((w) => saidStems.has(w)).length / st.length >= 0.5; };
    const fresh = below.filter((x) => !covered(x.text)).slice(0, 3);
    if (!fresh.length) return true;
    const text = (this.phrase("scroll_more_tour") || "Ещё на этом экране — {items}.")
      .replace("{items}", fresh.map((x) => `«${x.text}»`).join(", "));
    const sel = `text:${fresh[0].text}`;
    const res = await this.sayText(text, ep, (u, total) => {
      this.stepUtter = u;
      window.setTimeout(() => { if (this.alive(ep)) { this.set({ target: sel }); void this.bringIntoView(sel, ep); } },
        Math.min(1400, Math.max(400, total * 0.3)));
    });
    this.stepUtter = null;
    if (res === "aborted" || !this.alive(ep)) return false;
    this.remember("elena", text);
    return true;
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
