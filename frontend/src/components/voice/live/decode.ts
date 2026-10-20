// Сжатый голос → PCM 24 кГц для видеопотока аватара. Постоянные фразы и реплики шагов грузятся в mp3 (в 6 раз меньше
// сырого PCM: обзор не забивает медленный канал и не тормозит загрузку страниц), декодируются в браузере.
const RATE = 24000;

type OfflineCtor = new (channels: number, length: number, sampleRate: number) => OfflineAudioContext;

function offlineCtor(): OfflineCtor | null {
  const w = window as unknown as { OfflineAudioContext?: OfflineCtor; webkitOfflineAudioContext?: OfflineCtor };
  return w.OfflineAudioContext ?? w.webkitOfflineAudioContext ?? null;
}

/** mp3 (или другой формат браузера) → PCM s16le 24 кГц моно; тишина в начале срезается (до 300 мс). */
export async function decodeToPcm24(buf: ArrayBuffer): Promise<Uint8Array | null> {
  const Ctor = offlineCtor();
  if (!Ctor) return null;
  try {
    const ctx = new Ctor(1, RATE, RATE);
    const ab = await new Promise<AudioBuffer>((resolve, reject) => {
      const p = ctx.decodeAudioData(buf.slice(0), resolve, reject);
      if (p && typeof (p as Promise<AudioBuffer>).then === "function") (p as Promise<AudioBuffer>).then(resolve, reject);
    });
    const src = ab.getChannelData(0);
    // декодер уже привёл частоту к 24 кГц; если браузер этого не сделал — линейная интерполяция
    const ratio = ab.sampleRate / RATE;
    const len = ratio === 1 ? src.length : Math.floor(src.length / ratio);
    const at = (i: number) => {
      if (ratio === 1) return src[i];
      const x = i * ratio, j = Math.floor(x), f = x - j;
      return (src[j] ?? 0) * (1 - f) + (src[j + 1] ?? 0) * f;
    };
    let start = 0;
    const lim = Math.min(len, Math.round(RATE * 0.3));
    while (start < lim && Math.abs(at(start)) < 0.003) start++;
    start = Math.max(0, start - 240);
    const n = Math.max(0, len - start);
    const out = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const s = Math.max(-1, Math.min(1, at(start + i)));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return new Uint8Array(out.buffer);
  } catch {
    return null;
  }
}

/** Голос постоянной фразы: mp3 + декодирование; не вышло — сырой PCM 24 кГц. low — фоновая предзагрузка.
 *  У каждой попытки — свой срок: зависший запрос (медленная или рвущаяся связь) не держит разговор. */
export async function fetchPhrasePcm(url: string, text: string, low = false): Promise<Uint8Array | null> {
  const attempt = async (format: string, ms: number): Promise<Uint8Array | null> => {
    const ctl = new AbortController();
    const tid = window.setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, format }),
        signal: ctl.signal, ...(low ? { priority: "low" } : { priority: "high" }),
      } as RequestInit);
      if (!r.ok) return null;
      const buf = await r.arrayBuffer();
      if (format === "mp3") return await decodeToPcm24(buf);
      return new Uint8Array(buf);
    } catch {
      return null;
    } finally {
      window.clearTimeout(tid);
    }
  };
  const plan: [string, number][] = low ? [["mp3", 15000], ["pcm24", 15000]] : [["mp3", 3500], ["mp3", 4000], ["pcm24", 6000]];
  for (const [format, ms] of plan) {
    const pcm = await attempt(format, ms);
    if (pcm && pcm.byteLength > 0) return pcm;
  }
  return null;
}
