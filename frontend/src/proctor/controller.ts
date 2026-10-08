/**
 * Контроллер камеры во время теста — синглтон на вкладку: переживает переход «экран камеры → тест»,
 * держит поток камеры и детектор, раз в TICK_MS анализирует кадр и копит по заданиям интервалы
 * «нет лица» / «несколько лиц» / «камера закрыта» / «камера не передаёт изображение», а также сколько
 * камера наблюдала каждое задание. На сервер уходят только эти события (без кадров): каждые FLUSH_MS,
 * при смене задания, перед завершением теста и при уходе со страницы (fetch с keepalive).
 *
 * Любая ошибка камеры или модели переводит контроллер в состояние «error» с честным сообщением; тест при
 * этом не прерывается — он продолжается без камеры.
 */
import { useSyncExternalStore } from "react";
import { apiUrl, tokenStore } from "../lib/api";
import { MODEL_NAME, analyzeFrame, checkSupport, loadDetector, type FaceDetectorLike, type FrameState } from "./detector";

export const TICK_MS = 700;
const FLUSH_MS = 15_000;
const STABLE_TICKS = 2; // смена состояния — после двух одинаковых кадров подряд (сглаживание ложных срабатываний)
const MIN_EVENT_MS = 1000;
const SPLIT_OPEN_MS = 10_000;
const MAX_PENDING = 100;

export type CamStatus = "off" | "starting" | "on" | "error";
export type CamState = FrameState | "camera_off" | "unknown";
export type StopReason = "user" | "error" | "navigate";

export interface CamSnapshot {
  status: CamStatus;
  state: CamState;
  faces: number;
  error: string | null;       // честное сообщение, если камера или модель не заработали
  errorCode: "denied" | "unsupported" | "error" | null;
  sessionId: string | null;
  itemId: string | null;
  sent: number;               // отправлено событий за сессию
  frames: number;             // проанализировано кадров
}

interface Interval { kind: Exclude<FrameState, "face"> | "camera_off"; itemId: string; startedAt: number; faces: number }
interface Observed { ms: number; frames: number; face: number }
interface EventOut { item_id: string; kind: string; duration_ms: number; faces?: number; at_ms: number }

const STATE_TITLES: Record<CamState, string> = {
  face: "лицо в кадре", no_face: "нет лица в кадре", multi_face: "в кадре несколько лиц", blocked: "камера закрыта",
  camera_off: "камера не передаёт изображение", unknown: "камера включается",
};
export const stateTitle = (s: CamState) => STATE_TITLES[s];

class CameraController {
  private snap: CamSnapshot = { status: "off", state: "unknown", faces: 0, error: null, errorCode: null, sessionId: null, itemId: null, sent: 0, frames: 0 };
  private listeners = new Set<() => void>();
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private detector: FaceDetectorLike | null = null;
  private timer: number | null = null;
  private flushTimer: number | null = null;
  private candidate: { state: CamState; ticks: number } = { state: "unknown", ticks: 0 };
  private open: Interval | null = null;
  private pending: EventOut[] = [];
  private observed = new Map<string, Observed>();
  private flushing: Promise<void> | null = null;
  private pagehide = () => { void this.flush({ keepalive: true }); };

  // ------------------------------------------------------------- подписка (React)
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  getSnapshot = () => this.snap;
  private set(patch: Partial<CamSnapshot>) {
    this.snap = { ...this.snap, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  /** Поток для превью на экране согласия (кадры — только на экран кандидата). */
  get mediaStream(): MediaStream | null { return this.stream; }

  // ------------------------------------------------------------- запуск
  /** Включить камеру и загрузить модель. Ошибка → status "error" с понятным сообщением (и исключение). */
  async start(): Promise<void> {
    if (this.snap.status === "on" || this.snap.status === "starting") return;
    const sup = checkSupport();
    if (!sup.ok) {
      this.set({ status: "error", error: sup.reason ?? "Браузер не поддерживает анализ видео", errorCode: "unsupported" });
      throw new Error(sup.reason);
    }
    this.set({ status: "starting", error: null, errorCode: null, state: "unknown", faces: 0 });
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 320 }, height: { ideal: 240 }, facingMode: "user", frameRate: { ideal: 10, max: 15 } }, audio: false });
      this.stream = stream;
      const video = document.createElement("video");
      video.muted = true; video.playsInline = true; video.autoplay = true;
      video.srcObject = stream;
      await video.play();
      await new Promise<void>((ok) => { if (video.readyState >= 2) ok(); else video.onloadeddata = () => ok(); });
      this.video = video;
      this.canvas = document.createElement("canvas");
      this.detector = await loadDetector();
      for (const t of stream.getVideoTracks()) {
        t.addEventListener("ended", this.onTrackLost);
        t.addEventListener("mute", this.onTrackLost);
        t.addEventListener("unmute", this.onTrackBack);
      }
      this.timer = window.setInterval(() => this.tick(), TICK_MS);
      this.flushTimer = window.setInterval(() => { void this.flush(); }, FLUSH_MS);
      window.addEventListener("pagehide", this.pagehide);
      this.set({ status: "on" });
    } catch (e) {
      this.release();
      const { message, code } = describeError(e);
      this.set({ status: "error", error: message, errorCode: code });
      throw new Error(message);
    }
  }

  /** Сессия теста, куда идут события (после создания сессии или при возврате на страницу теста). */
  attachSession(sessionId: string) {
    if (this.snap.sessionId !== sessionId) {
      this.pending = []; this.observed.clear(); this.open = null;
      this.set({ sessionId, itemId: null, sent: 0 });
    }
  }

  private holders = 0;
  /** Страница теста открыта: события идут в эту сессию. */
  enterTest(sessionId: string) { this.holders += 1; this.attachSession(sessionId); }
  /** Страница теста закрыта: камера выключается, если страницу не открыли снова сразу (StrictMode перезапускает эффекты). */
  leaveTest() {
    this.holders = Math.max(0, this.holders - 1);
    window.setTimeout(() => { if (this.holders === 0 && this.snap.status !== "off") void this.stop("navigate"); }, 50);
  }

  /** Текущее задание: интервалы и наблюдение режутся по его границе; при смене — отправка. */
  setItem(itemId: string | null) {
    if (itemId === this.snap.itemId) return;
    const now = Date.now();
    this.closeOpen(now);
    this.set({ itemId });
    if (itemId && this.snap.status === "on" && this.snap.state !== "face" && this.snap.state !== "unknown") {
      this.open = { kind: this.snap.state as Interval["kind"], itemId, startedAt: now, faces: this.snap.faces };
    }
    void this.flush();
  }

  /** Выключить камеру: кнопкой (user), из-за сбоя (error) или при уходе со страницы теста (navigate — камера
   * выключается, окно наблюдения на сервере не закрывается, его закроет /start при возврате или finish). */
  async stop(reason: StopReason): Promise<void> {
    const sid = this.snap.sessionId;
    this.closeOpen(Date.now());
    this.release();
    this.set({ status: "off", state: "unknown", faces: 0 });
    await this.flush();
    if (sid && reason !== "navigate") {
      await this.post(`/proctor/sessions/${sid}/stop`, { reason }).catch(() => undefined);
    }
  }

  /** Тест завершён: сервер уже закрыл окно наблюдения — выключаем камеру без отправки и без /stop. */
  detach() {
    this.release();
    this.pending = []; this.observed.clear(); this.open = null;
    this.set({ status: "off", state: "unknown", faces: 0, sessionId: null, itemId: null, error: null, errorCode: null });
  }

  /** Отправить накопленное. Перед завершением теста — flush({ final: true }) и обязательно дождаться. */
  async flush(opts: { keepalive?: boolean; final?: boolean } = {}): Promise<void> {
    const sid = this.snap.sessionId;
    if (!sid) return;
    const now = Date.now();
    // наблюдение по текущему заданию — отдаём накопленное, счётчики обнуляем
    const observed = [...this.observed.entries()].filter(([, o]) => o.ms > 0 || o.frames > 0)
      .map(([item_id, o]) => ({ item_id, ms: Math.round(o.ms), frames: o.frames, face: o.face }));
    this.observed.clear();
    if (opts.final) this.closeOpen(now);
    const events = this.pending.splice(0, MAX_PENDING);
    if (this.open && now - this.open.startedAt >= SPLIT_OPEN_MS) {
      // длинный открытый интервал отправляем частями (каждая заведомо длиннее порога учёта): иначе он потерялся бы при закрытии вкладки
      events.push(this.toEvent(this.open, now));
      this.open = { ...this.open, startedAt: now };
    }
    if (!events.length && !observed.length) return;
    const keepalive = !!opts.keepalive;
    const run = async () => {
      try {
        const res = await this.post(`/proctor/sessions/${sid}/events`, { events, observed }, keepalive);
        if (res.ok) {
          this.set({ sent: this.snap.sent + events.length });
        } else if (res.status === 409) {
          // камера выключена на сервере (отзыв согласия, завершение теста) — выключаем и у себя, тест идёт дальше
          const body = await res.json().catch(() => null);
          const code = body?.detail?.code;
          if (code === "consent_revoked" || code === "camera_stopped" || code === "camera_not_enabled") {
            this.release();
            this.set({ status: "off", state: "unknown", error: code === "consent_revoked" ? "Согласие отозвано — камера выключена, тест продолжается без неё." : null });
          }
          this.pending = [];
        } else if (res.status >= 500) {
          this.pending.unshift(...events); // вернём в очередь: сервер временно недоступен
        }
      } catch {
        this.pending.unshift(...events.slice(0, MAX_PENDING - this.pending.length));
      }
    };
    this.flushing = run();
    await this.flushing;
    this.flushing = null;
  }

  // ------------------------------------------------------------- внутреннее
  private tick() {
    const v = this.video, det = this.detector, c = this.canvas;
    if (!v || !det || !c || this.snap.status !== "on") return;
    const now = Date.now();
    let raw: CamState, faces = 0;
    const track = this.stream?.getVideoTracks()[0];
    if (!track || track.readyState !== "live" || track.muted || v.readyState < 2) {
      raw = "camera_off";
    } else {
      try {
        const r = analyzeFrame(det, v, c, performance.now());
        raw = r.state; faces = r.faces;
      } catch {
        raw = "camera_off"; // сбой модели на кадре — считаем, что изображения нет; следующий кадр может пройти
      }
    }
    // наблюдение по заданию
    const item = this.snap.itemId;
    if (item) {
      const o = this.observed.get(item) ?? { ms: 0, frames: 0, face: 0 };
      o.ms += TICK_MS; o.frames += 1; if (raw === "face") o.face += 1;
      this.observed.set(item, o);
    }
    // сглаживание: новое состояние принимается после STABLE_TICKS одинаковых кадров
    if (raw === this.candidate.state) this.candidate.ticks += 1; else this.candidate = { state: raw, ticks: 1 };
    const stable = this.candidate.ticks >= STABLE_TICKS ? this.candidate.state : this.snap.state;
    if (stable !== this.snap.state) {
      this.closeOpen(now);
      if (stable !== "face" && stable !== "unknown" && item) this.open = { kind: stable as Interval["kind"], itemId: item, startedAt: now, faces };
      this.set({ state: stable, faces, frames: this.snap.frames + 1 });
    } else {
      if (this.open && stable === "multi_face") this.open.faces = Math.max(this.open.faces, faces);
      this.set({ faces, frames: this.snap.frames + 1 });
    }
  }

  private closeOpen(now: number) {
    if (!this.open) return;
    const dur = now - this.open.startedAt;
    if (dur >= MIN_EVENT_MS) this.pending.push(this.toEvent(this.open, now));
    if (this.pending.length > MAX_PENDING) this.pending.splice(0, this.pending.length - MAX_PENDING);
    this.open = null;
  }

  private toEvent(i: Interval, now: number): EventOut {
    const e: EventOut = { item_id: i.itemId, kind: i.kind, duration_ms: Math.min(3_600_000, now - i.startedAt), at_ms: i.startedAt };
    if (i.kind === "multi_face") e.faces = Math.max(2, i.faces);
    return e;
  }

  private onTrackLost = () => { this.candidate = { state: "camera_off", ticks: STABLE_TICKS }; };
  private onTrackBack = () => { this.candidate = { state: "unknown", ticks: 0 }; };

  private release() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    if (this.flushTimer) { clearInterval(this.flushTimer); this.flushTimer = null; }
    window.removeEventListener("pagehide", this.pagehide);
    for (const t of this.stream?.getTracks() ?? []) { try { t.stop(); } catch { /* уже остановлен */ } }
    this.stream = null;
    if (this.video) { this.video.srcObject = null; this.video = null; }
    this.candidate = { state: "unknown", ticks: 0 };
  }

  private post(path: string, body: unknown, keepalive = false): Promise<Response> {
    const token = tokenStore.get();
    return fetch(apiUrl(path), {
      method: "POST", keepalive,
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });
  }

  /** Справочные сведения о клиенте для /start (без данных о человеке). */
  clientInfo() {
    return { model: MODEL_NAME, fps: Math.round((1000 / TICK_MS) * 10) / 10, backend: "cpu", build: __APP_BUILD__ };
  }
}

function describeError(e: unknown): { message: string; code: "denied" | "unsupported" | "error" } {
  const name = (e as any)?.name as string | undefined;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return { code: "denied", message: "Доступ к камере не разрешён в браузере. Тест можно пройти без камеры." };
  }
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") {
    return { code: "denied", message: "Камера не найдена. Тест можно пройти без камеры." };
  }
  if (name === "NotReadableError" || name === "AbortError" || name === "TrackStartError") {
    return { code: "error", message: "Камера занята другим приложением или недоступна. Тест можно пройти без камеры." };
  }
  const msg = (e as any)?.message ? String((e as any).message) : "";
  if (/wasm|WebAssembly|fetch|network|tflite|import/i.test(msg)) {
    return { code: "unsupported", message: "Не удалось загрузить модель анализа видео в браузере. Тест можно пройти без камеры." };
  }
  return { code: "error", message: "Камеру не удалось включить. Тест можно пройти без камеры." };
}

export const camera = new CameraController();

/** Снимок состояния камеры для React-компонентов. */
export function useCamera(): CamSnapshot {
  return useSyncExternalStore(camera.subscribe, camera.getSnapshot, camera.getSnapshot);
}
