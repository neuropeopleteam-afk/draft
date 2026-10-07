/**
 * Детектор лица для камеры во время теста (по согласию). Работает только в браузере кандидата:
 * MediaPipe Face Detector (tasks-vision 1.1.0, модель blaze_face_short_range) — файлы модели и wasm лежат
 * в public/vendor и отдаются с нашего домена, загружаются лениво — после нажатия «Включить камеру».
 * Кадры никуда не отправляются; наружу уходит только число лиц в кадре и признак «камера закрыта».
 * Лицо не сравнивается с эталоном и не распознаётся — это не биометрическая идентификация.
 */
export const MP_BASE = "/vendor/mediapipe/1.1.0";
export const MODEL_NAME = "blaze_face_short_range";
export const MIN_CONFIDENCE = 0.65; // стандартная поддельная камера Chromium даёт ложные «лица» до 0,6–0,76 — порог выше

/** Признак кадра: одно лицо / нет лица / несколько лиц / камера закрыта (тёмный ровный кадр). */
export type FrameState = "face" | "no_face" | "multi_face" | "blocked";

export interface Support { ok: boolean; reason?: string; code?: "unsupported" | "insecure" }

interface FaceDetectorLike {
  detectForVideo(video: HTMLVideoElement, timestampMs: number): { detections: { categories: { score: number }[] }[] };
  close(): void;
}

// WebAssembly SIMD: минимальный модуль с инструкцией i8x16.splat (так же проверяет wasm-feature-detect)
const SIMD_PROBE = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11]);

/** Что умеет браузер: getUserMedia в защищённом контексте, WebAssembly с SIMD, canvas. */
export function checkSupport(): Support {
  if (typeof window === "undefined") return { ok: false, reason: "Нет окна браузера", code: "unsupported" };
  if (!window.isSecureContext) {
    return { ok: false, code: "insecure", reason: "Камера доступна только по защищённому соединению (https). Тест можно пройти без камеры." };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, code: "unsupported", reason: "Браузер не даёт доступ к камере (нет getUserMedia). Тест можно пройти без камеры." };
  }
  let simd = false;
  try { simd = typeof WebAssembly === "object" && WebAssembly.validate(SIMD_PROBE); } catch { simd = false; }
  if (!simd) {
    return { ok: false, code: "unsupported", reason: "Браузер не поддерживает WebAssembly SIMD, нужный модели анализа видео (Chrome 91+, Firefox 89+, Safari 16.4+). Тест можно пройти без камеры." };
  }
  if (typeof document.createElement("canvas").getContext !== "function") {
    return { ok: false, code: "unsupported", reason: "Браузер не поддерживает canvas. Тест можно пройти без камеры." };
  }
  return { ok: true };
}

let detectorPromise: Promise<FaceDetectorLike> | null = null;

/** Ленивая загрузка модели (один раз на вкладку). Ошибка — честное сообщение, дальше режим «без камеры». */
export function loadDetector(): Promise<FaceDetectorLike> {
  if (!detectorPromise) {
    detectorPromise = (async () => {
      const url = `${MP_BASE}/vision_bundle.mjs`;
      const mod: any = await import(/* @vite-ignore */ url);
      const fileset = { wasmLoaderPath: `${MP_BASE}/vision_wasm_internal.js`, wasmBinaryPath: `${MP_BASE}/vision_wasm_internal.wasm` };
      const det = await mod.FaceDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: `${MP_BASE}/${MODEL_NAME}.tflite`, delegate: "CPU" },
        runningMode: "VIDEO",
        minDetectionConfidence: MIN_CONFIDENCE,
      });
      return det as FaceDetectorLike;
    })().catch((e) => { detectorPromise = null; throw e; });
  }
  return detectorPromise;
}

const DARK_MEAN = 14; // яркость 0–255: закрытая ладонью или заклеенная камера даёт почти чёрный ровный кадр
const DARK_SPREAD = 5;

/** Кадр тёмный и ровный (камера закрыта): по уменьшенной копии 16×12 — дёшево и без сохранения кадра. */
export function isDarkFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement): boolean {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return false;
  canvas.width = 16; canvas.height = 12;
  try { ctx.drawImage(video, 0, 0, 16, 12); } catch { return false; }
  const d = ctx.getImageData(0, 0, 16, 12).data;
  let sum = 0, sum2 = 0;
  const n = d.length / 4;
  for (let i = 0; i < d.length; i += 4) {
    const y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    sum += y; sum2 += y * y;
  }
  const mean = sum / n;
  const sd = Math.sqrt(Math.max(0, sum2 / n - mean * mean));
  return mean < DARK_MEAN && sd < DARK_SPREAD;
}

/** Состояние одного кадра. Детектор уже считает только лица с уверенностью ≥ MIN_CONFIDENCE. */
export function analyzeFrame(det: FaceDetectorLike, video: HTMLVideoElement, canvas: HTMLCanvasElement, nowMs: number): { state: FrameState; faces: number } {
  if (isDarkFrame(video, canvas)) return { state: "blocked", faces: 0 };
  const res = det.detectForVideo(video, nowMs);
  const faces = res.detections.length;
  return { state: faces === 1 ? "face" : faces === 0 ? "no_face" : "multi_face", faces };
}

export type { FaceDetectorLike };
