// Живой видеоаватар (официальный JS SDK поставщика). Лицо — только наше: сгенерированный портрет несуществующего
// человека (frontend/public/avatar/PROVENANCE.md), загруженный как собственный аватар (ANAM_AVATAR_ID). Режим передачи
// звука: реплики озвучивает наш синтез (PCM s16le 16 или 24 кГц), поток только рисует лицо и движение губ; его LLM,
// голос и микрофон не используются (disableInputAudio).
//
// Надёжность — по эталону наших живых стендов:
//  • одна сессия на весь разговор, без пересоздания при перерисовках;
//  • звук реплики — createAgentAudioInputStream, конец реплики — endSequence(); перебивание — interruptPersona() и
//    endSequence(); новая реплика всегда начинается с новой последовательности и не раньше 200 мс после перебивания
//    (команда перебивания и звук идут разными каналами);
//  • 80 мс тишины перед первым звуком будят артикуляцию губ до первого слога;
//  • браузер запретил автозапуск звука — видео идёт без звука (губы видны), звук включается первым касанием страницы;
//  • обрыв потока, замершие кадры (5 с без нового кадра) или предел длительности сессии — тихая пересадка на свежую
//    сессию во втором <video>: переключение после первых кадров новой, старая гасится; голос в это время не теряется
//    (запасной вывод — components/voice/live/voice.ts);
//  • три неудачи подряд — свой портрет (InterviewerAvatar) с голосом, разговор продолжается.
import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState } from "react";
import { apiUrl, tokenStore } from "../../lib/api";
import { InterviewerAvatar } from "./InterviewerAvatar";
import { WAVE_LABEL, type WaveState } from "./VoiceWave";

type AnamSdk = typeof import("@anam-ai/js-sdk");
type AnamClient = ReturnType<AnamSdk["createClient"]>;
type AudioIn = ReturnType<AnamClient["createAgentAudioInputStream"]>;

interface TokenOut { session_token: string; max_seconds: number; ice_servers?: RTCIceServer[] | null; relay_only?: boolean; persona_name?: string }

export type AnamStatus = "idle" | "connecting" | "live" | "reconnecting" | "failed";

export interface AnamWriter {
  /** Можно слать звук в эту реплику (поток жив, реплику не перебили). */
  readonly ok: boolean;
  push(bytes: Uint8Array | ArrayBuffer): void;
  /** Конец реплики: endSequence() и ожидание, пока звук договорится. Обрыв потока — reject. */
  end(): Promise<void>;
  abort(): void;
}

export interface AnamHandle {
  /** Поток готов: можно отдавать звук реплики. */
  live(): boolean;
  /** Дождаться готовности потока (до timeoutMs мс): true — поток live. В режиме deferConnect запускает подключение. */
  waitReady(timeoutMs?: number): Promise<boolean>;
  /** Озвучить реплику целиком (pcm_s16le, по умолчанию 16 кГц): губы и звук — из потока. Сбой — reject. */
  speak(pcm: ArrayBuffer, opts?: { sampleRate?: number }): Promise<void>;
  /** Потоковая реплика: куски PCM по мере синтеза. null — поток не готов (звук пойдёт запасным путём). */
  open(opts?: { sampleRate?: number }): AnamWriter | null;
  /** Прервать текущую реплику (человек заговорил, «Закончить»). */
  stop(): void;
  /** Момент (performance.now), до которого ещё звучит отправленный звук. */
  audibleUntil(): number;
  /** Из обработчика нажатия: включить звук видео, если браузер его заглушил. */
  unlock(): void;
  /** Подключиться сейчас (для deferConnect). */
  connect(): void;
  /** Приглушить голос (первая ступень перебивания). */
  duck?(on: boolean): void;
}

export interface AnamAvatarProps {
  sessionId: string;
  /** Состояние с экрана (думаю / слушаю …); «говорю» компонент выставляет сам, пока звучит реплика. */
  state: WaveState;
  level?: () => number;
  name?: string;
  size?: number;
  tone?: "light" | "dark";
  className?: string;
  tokenPath?: string;
  onStatus?: (s: AnamStatus) => void;
  onSpeaking?: (on: boolean) => void;
  /** Заполнить родителя целиком (виджет проводника): без подписи, рамки и свечения. */
  fill?: boolean;
  /** Не подключаться до первого connect()/waitReady()/speak() — экраны, где разговор начинается по кнопке. */
  deferConnect?: boolean;
}

const PIPELINE_MS = 650;      // звук из потока звучит примерно через столько после отправки
const TAIL_MS = 220;
const READY_TIMEOUT_MS = 15000;
const STALL_MS = 5000;
const ROTATE_AHEAD_S = 75;    // плановая пересадка на свежую сессию — в паузе, не позже чем за 75 с до предела
const FORCE_AHEAD_S = 12;
const MAX_FAILS = 3;
const BACKGROUND_RETRY_MS = [3000, 6000, 10000, 15000, 25000, 40000];
// Видеопоток недоступен по лимиту (минуты периода исчерпаны, все места заняты): помним 10 минут в пределах вкладки —
// следующие экраны не ждут подключения и сразу говорят запасным голосом с живым портретом.
const LIMIT_KEY = "draft.avatar.limit";
const LIMIT_MS = 10 * 60 * 1000;
const LIMIT_RX = /429|minutes|limit|quota|Too Many/i;
function limitedRecently(): boolean {
  try { const v = Number(sessionStorage.getItem(LIMIT_KEY) || 0); return v > 0 && Date.now() - v < LIMIT_MS; } catch { return false; }
}
function markLimited() { try { sessionStorage.setItem(LIMIT_KEY, String(Date.now())); } catch { /* ignore */ } }
const AFTER_INTERRUPT_MS = 200;

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));
const toBuf = (b: Uint8Array | ArrayBuffer): ArrayBuffer =>
  b instanceof ArrayBuffer ? b : (b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer);

interface Slot {
  key: "a" | "b";
  client: AnamClient;
  input: AudioIn | null;
  rate: number;
  deadline: number;
  dead: boolean;
}

let sdkPromise: Promise<AnamSdk> | null = null;
const loadSdk = () => (sdkPromise ??= import("@anam-ai/js-sdk"));

export const AnamAvatar = forwardRef<AnamHandle, AnamAvatarProps>(function AnamAvatar(
  { sessionId, state, level, name = "Интервьюер", size = 200, tone = "light", className = "", tokenPath, onStatus, onSpeaking,
    fill = false, deferConnect = false }, ref,
) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const vid = (k: "a" | "b") => `anam-${uid}-${k}`;
  const videoEl = (k: "a" | "b") => document.getElementById(vid(k)) as HTMLVideoElement | null;

  const [status, setStatusState] = useState<AnamStatus>(deferConnect ? "idle" : "connecting");
  const [shown, setShown] = useState<"a" | "b">("a");
  const [speaking, setSpeakingState] = useState(false);
  const [needsUnlock, setNeedsUnlock] = useState(false);

  const statusRef = useRef<AnamStatus>(deferConnect ? "idle" : "connecting");
  // запасной режим: видеопоток не поднялся — портрет «говорит» вместе с запасным голосом, подключение — в фоне
  const fallbackRef = useRef(false);
  const [fallback, setFallback] = useState(false);
  const active = useRef<Slot | null>(null);
  const dead = useRef(false);
  const rotating = useRef(false);
  const fails = useRef(0);
  const until = useRef(0);
  const seq = useRef(0);
  const abortSeq = useRef(0);
  const lastInterrupt = useRef(0);
  const lastFrame = useRef(0);
  const unlockNeeded = useRef(false);
  const ducked = useRef(false);
  const speakingRef = useRef(false);
  const waiters = useRef<Array<(ok: boolean) => void>>([]);
  const connectRequested = useRef(!deferConnect);
  const started = useRef(false);
  const tokenPathRef = useRef(tokenPath);
  tokenPathRef.current = tokenPath;
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;
  const onSpeakingRef = useRef(onSpeaking);
  onSpeakingRef.current = onSpeaking;
  const speakTimer = useRef(0);
  const lastRotateFail = useRef(0);

  const setStatus = (s: AnamStatus) => {
    if (statusRef.current === s) return;
    if (statusRef.current === "failed") return;
    statusRef.current = s;
    if (!dead.current) setStatusState(s);
    onStatusRef.current?.(s);
    if (s === "live" || s === "failed") {
      const list = waiters.current.splice(0);
      for (const fn of list) { try { fn(s === "live"); } catch { /* ignore */ } }
    }
  };

  const setSpeaking = (on: boolean) => {
    if (speakingRef.current === on) return;
    speakingRef.current = on;
    if (!dead.current) setSpeakingState(on);
    onSpeakingRef.current?.(on);
  };

  // «говорит», пока не договорил отправленный звук
  const markSpeaking = () => {
    setSpeaking(true);
    window.clearTimeout(speakTimer.current);
    const tick = () => {
      const left = until.current - performance.now();
      if (left <= 0) { setSpeaking(false); return; }
      speakTimer.current = window.setTimeout(tick, Math.min(200, left + 20));
    };
    tick();
  };

  async function fetchToken(): Promise<TokenOut> {
    const t = tokenStore.get();
    const url = tokenPathRef.current ?? `/interview/sessions/${sessionId}/avatar-token`;
    const r = await fetch(apiUrl(url), { method: "POST", headers: t ? { Authorization: `Bearer ${t}` } : {} });
    if (!r.ok) throw new Error(String(r.status));
    return (await r.json()) as TokenOut;
  }

  async function playVideo(k: "a" | "b", sound: boolean) {
    const v = videoEl(k);
    if (!v) return;
    v.volume = ducked.current ? 0.35 : 1;
    const activated = () => (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation?.hasBeenActive ?? false;
    // play() прерывается, когда поток переподключает srcObject (AbortError), — это не запрет автозапуска: повторяем
    for (let attempt = 0; attempt < 5; attempt++) {
      v.muted = !sound;
      try {
        await v.play();
        if (sound) { unlockNeeded.current = false; if (!dead.current) setNeedsUnlock(false); }
        return;
      } catch (e) {
        if (dead.current || !v.srcObject) return;
        const name = (e as { name?: string })?.name;
        if (name === "NotAllowedError" && (!sound || !activated() || attempt >= 1)) break;
        await new Promise((r) => window.setTimeout(r, 120 * (attempt + 1)));
      }
    }
    if (!sound) return;
    // автозапуск звука запрещён: видео без звука (губы видны), звук — по первому касанию
    v.muted = true;
    try { await v.play(); } catch { /* кадры придут после касания */ }
    unlockNeeded.current = true;
    if (!dead.current) setNeedsUnlock(true);
  }

  function watchFrames(k: "a" | "b") {
    const v = videoEl(k);
    if (!v) return;
    lastFrame.current = performance.now();
    if (typeof v.requestVideoFrameCallback !== "function") return;
    const cb = () => {
      if (dead.current || active.current?.key !== k) return;
      lastFrame.current = performance.now();
      v.requestVideoFrameCallback(cb);
    };
    v.requestVideoFrameCallback(cb);
  }

  /** Новая сессия во втором (или первом) <video>; resolve — когда пришли кадры и сессия готова принимать звук. */
  async function openSlot(k: "a" | "b", background: boolean): Promise<Slot> {
    if (typeof RTCPeerConnection === "undefined") throw new Error("no webrtc");
    const [tok, sdk] = await Promise.all([fetchToken(), loadSdk()]);
    if (dead.current) throw new Error("unmounted");
    const client = sdk.createClient(tok.session_token, {
      disableInputAudio: true,
      ...(tok.ice_servers?.length ? { iceServers: tok.ice_servers } : {}),
      ...(tok.relay_only ? { rtcConfiguration: { iceTransportPolicy: "relay" as RTCIceTransportPolicy } } : {}),
    });
    const slot: Slot = { key: k, client, input: null, rate: 0, deadline: Date.now() + Math.max(60, tok.max_seconds || 600) * 1000, dead: false };
    const ve = videoEl(k);
    if (ve) { ve.muted = background || unlockNeeded.current; if (background) ve.srcObject = null; }
    await new Promise<void>((resolve, reject) => {
      let ready = false, frames = false, settled = false;
      const finish = (err?: Error) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        window.clearTimeout(grace);
        if (err) reject(err); else resolve();
      };
      const check = () => { if (ready && frames) finish(); };
      const timer = window.setTimeout(() => finish(new Error("timeout")), READY_TIMEOUT_MS);
      let grace = 0;
      client.addListener(sdk.AnamEvent.SESSION_READY, () => { ready = true; check(); });
      client.addListener(sdk.AnamEvent.VIDEO_STREAM_STARTED, () => { void playVideo(k, !background && !unlockNeeded.current); });
      client.addListener(sdk.AnamEvent.VIDEO_PLAY_STARTED, () => {
        frames = true;
        check();
        // без SESSION_READY (старые версии сервера) — через 1,5 с после первых кадров считаем сессию готовой
        if (!ready) grace = window.setTimeout(() => { ready = true; check(); }, 1500);
      });
      client.addListener(sdk.AnamEvent.CONNECTION_CLOSED, () => {
        slot.dead = true;
        if (!settled) finish(new Error("closed"));
        else onSlotClosed(slot);
      });
      client.streamToVideoElement(vid(k)).catch((e: unknown) => {
        const err = e instanceof Error ? e : new Error(String(e));
        if (LIMIT_RX.test(`${err.message} ${String((e as { status?: number })?.status ?? "")}`)) markLimited();
        finish(err);
      });
    });
    if (dead.current) { void client.stopStreaming().catch(() => undefined); throw new Error("unmounted"); }
    return slot;
  }

  function inputFor(slot: Slot, rate: number): AudioIn {
    if (slot.input && slot.rate === rate) return slot.input;
    if (slot.input && slot.input.getSequenceNumber() > 0) { try { slot.input.endSequence(); } catch { /* ignore */ } }
    slot.input = slot.client.createAgentAudioInputStream({ encoding: "pcm_s16le", sampleRate: rate, channels: 1 });
    slot.rate = rate;
    return slot.input;
  }

  function activate(slot: Slot) {
    const prev = active.current;
    active.current = slot;
    fallbackRef.current = false;
    if (!dead.current) setFallback(false);
    setShown(slot.key);
    void playVideo(slot.key, !unlockNeeded.current);
    watchFrames(slot.key);
    fails.current = 0;
    setStatus("live");
    if (prev && prev !== slot) {
      prev.dead = true;
      const pv = videoEl(prev.key);
      if (pv) pv.muted = true;
      void prev.client.stopStreaming().catch(() => undefined).finally(() => { const v = videoEl(prev.key); if (v && active.current?.key !== prev.key) v.srcObject = null; });
    }
  }

  function releaseWaiters() {
    const list = waiters.current.splice(0);
    for (const fn of list) { try { fn(false); } catch { /* ignore */ } }
  }

  async function startFirst() {
    if (started.current || dead.current) return;
    started.current = true;
    const limited = limitedRecently();
    if (!limited) {
      setStatus("connecting");
      for (let attempt = 0; attempt < 2 && !dead.current; attempt++) {
        try {
          const slot = await openSlot("a", false);
          activate(slot);
          return;
        } catch {
          if (dead.current) return;
          if (limitedRecently()) break;   // лимит — повтор сразу бесполезен
          await sleep(1200);
        }
      }
    }
    // видеопоток пока не поднялся: голос идёт запасным путём, портрет говорит вместе с ним, а подключение
    // повторяется в фоне — как только место освободится, губы оживут со следующей реплики
    fallbackRef.current = true;
    if (!dead.current) setFallback(true);
    setStatus("reconnecting");
    releaseWaiters();
    const plan = limitedRecently() ? [60000, 120000] : BACKGROUND_RETRY_MS;
    for (const wait of plan) {
      await sleep(wait);
      if (dead.current || active.current) return;
      try {
        const slot = await openSlot(Math.random() < 0.5 ? "a" : "b", false);
        if (dead.current) { void slot.client.stopStreaming().catch(() => undefined); return; }
        activate(slot);
        return;
      } catch { /* следующая попытка */ }
    }
    if (!dead.current && !active.current) setStatus("failed");
  }

  /** Пересадка на свежую сессию: planned — в паузе перед пределом; closed/stall — поток уже не работает. */
  async function rotate(reason: "planned" | "forced" | "closed" | "stall") {
    if (rotating.current || dead.current || statusRef.current === "failed") return;
    if (reason === "planned" && Date.now() - lastRotateFail.current < 20000) return;
    rotating.current = true;
    const cur = active.current;
    const broken = reason === "closed" || reason === "stall" || !cur || cur.dead;
    if (broken) {
      // звук, который ещё не прозвучал из умершего потока, уже не прозвучит — запасной голос подхватит следующую реплику
      until.current = 0;
      setSpeaking(false);
      setStatus("reconnecting");
    }
    const next: "a" | "b" = cur?.key === "a" ? "b" : "a";
    let retry = false;
    try {
      const slot = await openSlot(next, true);
      if (dead.current) { void slot.client.stopStreaming().catch(() => undefined); return; }
      // плановая пересадка ждёт конца реплики, но не дольше предела старой сессии
      while (!broken && cur && !cur.dead && performance.now() < until.current && Date.now() < cur.deadline - FORCE_AHEAD_S * 1000) await sleep(200);
      activate(slot);
    } catch {
      fails.current += 1;
      lastRotateFail.current = Date.now();
      if (broken || active.current?.dead) {
        if (fails.current >= MAX_FAILS) setStatus("failed");
        else retry = true;
      }
    } finally {
      rotating.current = false;
    }
    if (retry && !dead.current) window.setTimeout(() => { void rotate("closed"); }, 800 * fails.current);
  }

  function onSlotClosed(slot: Slot) {
    if (dead.current || active.current !== slot) return;
    void rotate("closed");
  }

  function interrupt() {
    abortSeq.current = seq.current;
    const slot = active.current;
    const audible = performance.now() < until.current;
    until.current = 0;
    setSpeaking(false);
    if (slot && !slot.dead) {
      if (audible) {
        try { if (slot.client.isStreaming()) slot.client.interruptPersona(); } catch { /* поток уже закрыт */ }
        lastInterrupt.current = performance.now();
      }
      if (slot.input && slot.input.getSequenceNumber() > 0) { try { slot.input.endSequence(); } catch { /* ignore */ } }
    }
  }

  function open(rate: number): AnamWriter | null {
    const slot = active.current;
    if (!slot || slot.dead || statusRef.current !== "live") return null;
    let input: AudioIn;
    try { input = inputFor(slot, rate); } catch { return null; }
    if (input.getSequenceNumber() > 0) { try { input.endSequence(); } catch { /* прошлая реплика без end() */ } }
    const my = ++seq.current;
    const bpms = (rate * 2) / 1000;
    let sent = 0;
    let closedSeq = false;
    const held: ArrayBuffer[] = [];
    let holdTimer = 0;
    const ok = () => !slot.dead && active.current === slot && my > abortSeq.current;
    const send = (buf: ArrayBuffer) => {
      const now = performance.now();
      if (!sent) {
        input.sendAudioChunk(new ArrayBuffer(Math.round(bpms * 80) & ~1));  // разгон губ
        until.current = Math.max(until.current, now + PIPELINE_MS) + 80;
      }
      input.sendAudioChunk(buf);
      sent += buf.byteLength;
      until.current = Math.max(until.current, now + PIPELINE_MS) + buf.byteLength / bpms;
      markSpeaking();
    };
    const flushHeld = () => {
      holdTimer = 0;
      if (!ok()) { held.length = 0; return; }
      while (held.length) send(held.shift()!);
      if (closedSeq && sent) { try { input.endSequence(); } catch { /* ignore */ } }
    };
    return {
      get ok() { return ok(); },
      push(b) {
        if (!ok() || closedSeq) throw new Error("anam_closed");
        const buf = toBuf(b);
        const wait = lastInterrupt.current + AFTER_INTERRUPT_MS - performance.now();
        if (wait > 0 || held.length) {
          held.push(buf);
          if (!holdTimer) holdTimer = window.setTimeout(flushHeld, Math.max(0, wait));
          return;
        }
        send(buf);
      },
      async end() {
        if (closedSeq) return;
        closedSeq = true;
        if (!held.length && sent && ok()) { try { input.endSequence(); } catch { /* ignore */ } }
        while (holdTimer) await sleep(30);
        for (;;) {
          if (my <= abortSeq.current) return;
          if (slot.dead || active.current !== slot) throw new Error("anam_closed");
          const left = until.current + TAIL_MS - performance.now();
          if (left <= 0) return;
          await sleep(Math.min(120, left));
        }
      },
      abort() { if (my > abortSeq.current) interrupt(); },
    };
  }

  function requestConnect() {
    connectRequested.current = true;
    if (!started.current) void startFirst();
  }

  function unlock() {
    const slot = active.current;
    if (!slot) return;
    const v = videoEl(slot.key);
    if (v && (v.muted || v.paused)) {
      v.muted = false;
      void v.play().then(() => { unlockNeeded.current = false; if (!dead.current) setNeedsUnlock(false); })
        .catch(() => { v.muted = true; void v.play().catch(() => undefined); });  // звук ещё нельзя — хотя бы губы
    }
  }

  useEffect(() => {
    dead.current = false;
    if (connectRequested.current) void startFirst();
    const watchdog = window.setInterval(() => {
      const slot = active.current;
      if (!slot || dead.current || statusRef.current !== "live" || rotating.current) return;
      // звук был заблокирован, а пользователь уже взаимодействовал со страницей — включаем сами
      if (unlockNeeded.current && (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation?.hasBeenActive) unlock();
      const now = Date.now();
      const visible = document.visibilityState === "visible";
      if (visible && performance.now() - lastFrame.current > STALL_MS) { void rotate("stall"); return; }
      const idle = performance.now() > until.current + 400;
      if (now > slot.deadline - FORCE_AHEAD_S * 1000) void rotate("forced");
      else if (idle && now > slot.deadline - ROTATE_AHEAD_S * 1000) void rotate("planned");
    }, 1000);
    const onVisible = () => { if (document.visibilityState === "visible") lastFrame.current = performance.now(); };
    const onGesture = () => { if (unlockNeeded.current) unlock(); };
    // закрытие или перезагрузка вкладки — сессию видеопотока закрываем сразу (место не висит до тайм-аута)
    const onHide = () => { const s = active.current; if (s) { s.dead = true; void s.client.stopStreaming().catch(() => undefined); } };
    window.addEventListener("pagehide", onHide);
    document.addEventListener("visibilitychange", onVisible);
    document.addEventListener("pointerdown", onGesture, true);
    document.addEventListener("keydown", onGesture, true);
    return () => {
      dead.current = true;
      window.clearInterval(watchdog);
      window.clearTimeout(speakTimer.current);
      document.removeEventListener("visibilitychange", onVisible);
      document.removeEventListener("pointerdown", onGesture, true);
      document.removeEventListener("keydown", onGesture, true);
      window.removeEventListener("pagehide", onHide);
      const list = waiters.current.splice(0);
      for (const fn of list) { try { fn(false); } catch { /* ignore */ } }
      const slot = active.current;
      active.current = null;
      abortSeq.current = seq.current;
      if (slot) { slot.dead = true; void slot.client.stopStreaming().catch(() => undefined); }
      // сессию, которая ещё подключается, гасит openSlot (dead.current)
    };
  }, [sessionId]);  // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({
    live: () => statusRef.current === "live" && !!active.current && !active.current.dead,
    waitReady: (timeoutMs = 4500) => {
      requestConnect();
      if (statusRef.current === "live" && active.current) return Promise.resolve(true);
      if (statusRef.current === "failed") return Promise.resolve(false);
      if (fallbackRef.current) return Promise.resolve(false);
      return new Promise<boolean>((resolve) => {
        let done = false;
        const fin = (okv: boolean) => { if (done) return; done = true; window.clearTimeout(tid); resolve(okv); };
        const tid = window.setTimeout(() => fin(statusRef.current === "live"), timeoutMs);
        waiters.current.push(fin);
      });
    },
    speak: (pcm: ArrayBuffer, opts?: { sampleRate?: number }) => (async () => {
      const rate = opts?.sampleRate ?? 16000;
      const w = open(rate);
      if (!w || pcm.byteLength < 2) throw new Error("anam not live");
      const bytes = new Uint8Array(pcm, 0, pcm.byteLength - (pcm.byteLength % 2));
      const step = Math.round(rate * 2 * 0.2) & ~1;  // по 200 мс
      const t0 = performance.now();
      for (let i = 0, ms = 0; i < bytes.byteLength; i += step, ms += 200) {
        if (!w.ok) break;
        const ahead = ms - (performance.now() - t0);
        if (ahead > 2200) await sleep(ahead - 2200);
        if (!w.ok) break;
        w.push(bytes.subarray(i, Math.min(bytes.byteLength, i + step)));
      }
      if (!w.ok && seq.current <= abortSeq.current) return;  // перебили — это не ошибка
      await w.end();
    })(),
    open: (opts?: { sampleRate?: number }) => open(opts?.sampleRate ?? 16000),
    stop: () => interrupt(),
    audibleUntil: () => until.current,
    unlock,
    connect: requestConnect,
    duck: (on: boolean) => {
      ducked.current = on;
      const slot = active.current;
      const v = slot ? videoEl(slot.key) : null;
      if (v) v.volume = on ? 0.35 : 1;
    },
  }), []);  // eslint-disable-line react-hooks/exhaustive-deps

  if (status === "failed") {
    return <InterviewerAvatar state={state} level={level} name={name} size={fill ? 640 : size} tone={tone} glow={false}
      className={fill ? `h-full w-full [&>div]:!h-full [&>div]:!w-full [&>div]:!rounded-none [&>figcaption]:hidden ${className}` : className} />;
  }

  const shownState: WaveState = speaking ? "speaking" : state === "speaking" ? "listening" : state;
  const label = WAVE_LABEL[shownState].toLowerCase();
  const textTone = tone === "dark" ? "text-white" : "text-brand-night";
  const isLive = status === "live";
  const frame = (
    <div className={fill ? "relative h-full w-full overflow-hidden bg-[#15131C]" : "relative aspect-square max-w-full overflow-hidden rounded-3xl bg-[#15131C]"}
      style={fill ? undefined : { width: size }}>
      <img src="/avatar/interviewer.webp" alt="" aria-hidden="true" className="absolute inset-0 h-full w-full object-cover" />
      {fallback && !isLive && (
        <div className="absolute inset-0" data-testid="avatar-fallback">
          <InterviewerAvatar state={state} level={level} name={name} size={fill ? 640 : size} tone={tone} glow={false}
            className="h-full w-full [&>div]:!h-full [&>div]:!w-full [&>div]:!rounded-none [&>figcaption]:hidden" />
        </div>
      )}
      {(["a", "b"] as const).map((k) => (
        <video key={k} id={vid(k)} autoPlay playsInline disablePictureInPicture
          aria-label={k === shown ? `${name}: сгенерированный образ, не человек` : undefined} aria-hidden={k !== shown}
          className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-500 ${isLive && k === shown ? "opacity-100" : "opacity-0"}`}
          data-testid={k === shown ? "avatar-anam-video" : undefined} />
      ))}
      {needsUnlock && isLive && (
        <button type="button" onClick={unlock} aria-label="Включить звук"
          className="absolute left-1/2 top-1/2 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur transition hover:bg-black/70"
          data-testid="avatar-unmute">
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M11 5 6 9H3v6h3l5 4z" fill="currentColor" stroke="none" /><path d="m16 9 5 6M21 9l-5 6" />
          </svg>
        </button>
      )}
    </div>
  );
  if (fill) {
    return (
      <div className={`relative h-full w-full ${className}`} data-testid="interviewer-avatar" data-state={shownState}
        data-mode={isLive ? "anam" : fallback ? "fallback" : status}>
        {frame}
      </div>
    );
  }
  return (
    <figure className={`m-0 flex flex-col items-center text-center ${className}`} data-testid="interviewer-avatar" data-state={shownState}
      data-mode={isLive ? "anam" : "connecting"}>
      {frame}
      <figcaption className="mt-2">
        <p className={`text-sm font-semibold ${textTone}`}>
          {name}: <span aria-live="polite" data-testid="avatar-state">{label}</span>
        </p>
      </figcaption>
    </figure>
  );
});
