// Голос ведущей в живом разговоре: реплики идут в видеопоток аватара (губы двигаются под звук), а если поток ещё
// подключается, переподключается или отказал — тем же звуком через Web Audio (голос не прерывается).
// Реплики встают в очередь одна за другой (связка «Секунду.» → ответ без паузы), stop() обрывает всё сразу.
// currentText/echoText — текст, который сейчас звучит из динамиков: по нему отсекается эхо в распознавании.
import type { AnamHandle, AnamWriter } from "../AnamAvatar";
import { PcmPlayer } from "./player";

export type SayResult = "done" | "aborted";

export interface Utterance {
  readonly text: string;
  /** Дописать текст реплики (ответ приходит по фразам): эхо и «что прозвучало» — по всему тексту. */
  append(more: string): void;
  readonly startedAt: number;
  /** Длительность отправленного звука, мс. */
  readonly durationMs: number;
  push(bytes: Uint8Array): void;
  /** Звук закончился (или прерван). */
  end(): Promise<SayResult>;
  /** Сколько звука уже прозвучало (0…1) — для решения «повторить шаг или идти дальше». */
  progress(): number;
}

const LOOKAHEAD_MS = 2200;   // отправлять звук в поток не дальше чем на ~2 с вперёд (ровно, без залпа)
const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

export class Voice {
  readonly player = new PcmPlayer();
  private seq = 0;
  private until = 0;           // performance.now(), когда договорит последняя реплика в очереди
  private lastStart = 0;
  private current = "";
  private tail = { text: "", until: 0 };

  private lookahead: number;
  private chunk = 9600;            // кусок звука в поток (24 кГц, 16 бит: 9600 байт = 200 мс)

  /** lookaheadMs — на сколько вперёд отправлять звук в видеопоток (по умолчанию ~2 с). */
  constructor(private avatar: () => AnamHandle | null, opts: { lookaheadMs?: number; chunkBytes?: number } = {}) {
    this.lookahead = opts.lookaheadMs ?? LOOKAHEAD_MS;
    this.chunk = Math.max(960, (opts.chunkBytes ?? 9600) & ~1);
  }

  /** Звучит ли сейчас её голос (с запасом на задержку потока). */
  speaking(): boolean { return performance.now() < this.until; }
  /** Сколько мс уже звучит текущая реплика. */
  sinceStart(): number { return this.speaking() ? performance.now() - this.lastStart : 0; }
  /** Текст, который сейчас звучит или только что прозвучал (эхо может прийти в распознавание с задержкой). */
  echoText(): string {
    if (this.speaking()) return this.current;
    return performance.now() < this.tail.until ? this.tail.text : "";
  }

  unlock() { this.player.unlock(); this.avatar()?.unlock(); }

  /** Новая реплика в очередь. rate — частота PCM (24000 для голоса проводника, 16000 — старые эндпоинты). */
  begin(text: string, rate = 24000): Utterance {
    const my = ++this.seq;
    const self = this;
    const anam = this.avatar();
    let writer: AnamWriter | null = anam?.live() ? anam.open({ sampleRate: rate }) : null;
    let sentMs = 0;
    let startedAt = 0;
    let queue: Uint8Array[] = [];
    let pumping = false;
    let finished = false;
    let ended: Promise<SayResult> | null = null;
    const bpms = (rate * 2) / 1000;
    let full = text;
    this.current = text;

    const send = (chunk: Uint8Array) => {
      if (!startedAt) { startedAt = performance.now(); self.lastStart = Math.max(self.lastStart, startedAt); }
      if (writer?.ok) {
        try {
          writer.push(chunk);
          sentMs += chunk.byteLength / bpms;
          self.until = Math.max(self.until, anam?.audibleUntil() ?? 0);
          return;
        } catch {
          writer = null;  // поток оборвался посреди реплики — договариваем тем же звуком без видео
        }
      }
      const end = self.player.push(chunk, rate);
      sentMs += chunk.byteLength / bpms;
      self.until = Math.max(self.until, end + 120);
    };

    const pump = async () => {
      if (pumping) return;
      pumping = true;
      try {
        while (queue.length) {
          if (self.aborted(my)) { queue = []; return; }
          // ровная подача: не дальше LOOKAHEAD вперёд от реального времени (для потока аватара)
          if (writer?.ok && startedAt) {
            const ahead = sentMs - (performance.now() - startedAt);
            if (ahead > self.lookahead) { await sleep(Math.min(250, ahead - self.lookahead)); continue; }
          }
          send(queue.shift()!);
        }
      } finally { pumping = false; }
    };

    const u: Utterance = {
      get text() { return full; },
      append(more: string) {
        if (!more) return;
        full = full ? `${full} ${more}` : more;
        if (my === self.seq) self.current = full;
      },
      get startedAt() { return startedAt; },
      get durationMs() { return sentMs; },
      push(bytes: Uint8Array) {
        if (self.aborted(my) || finished) return;
        for (let i = 0; i < bytes.byteLength; i += self.chunk) queue.push(bytes.subarray(i, Math.min(bytes.byteLength, i + self.chunk)));
        void pump();
      },
      end() {
        if (ended) return ended;
        finished = true;
        ended = (async () => {
          while ((queue.length || pumping) && !self.aborted(my)) await sleep(40);
          if (self.aborted(my)) return "aborted" as SayResult;
          if (writer?.ok) {
            try { await writer.end(); } catch { /* поток оборвался — ниже ждём по часам */ }
            self.until = Math.max(self.until, anam?.audibleUntil() ?? 0);
          }
          while (performance.now() < self.until && !self.aborted(my)) await sleep(Math.min(120, self.until - performance.now()));
          if (self.aborted(my)) return "aborted" as SayResult;
          if (my === self.seq) {
            self.tail = { text: full, until: performance.now() + 1500 };
          }
          return "done" as SayResult;
        })();
        return ended;
      },
      progress() {
        if (!startedAt || !sentMs) return 0;
        return Math.max(0, Math.min(1, (performance.now() - startedAt - 300) / sentMs));
      },
    };
    return u;
  }

  private abortedBefore = 0;
  private aborted(my: number): boolean { return my <= this.abortedBefore; }

  /** Сказать готовый звук целиком (кэш шага, связка) или потоком (Response.body). */
  async say(text: string, src: ArrayBuffer | Uint8Array | ReadableStream<Uint8Array> | null, rate = 24000,
    onStart?: (u: Utterance) => void): Promise<SayResult> {
    const u = this.begin(text, rate);
    onStart?.(u);
    if (src instanceof ReadableStream) {
      const reader = src.getReader();
      let tailByte: Uint8Array | null = null;
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          let chunk = value;
          if (tailByte) { const m = new Uint8Array(tailByte.length + chunk.length); m.set(tailByte); m.set(chunk, tailByte.length); chunk = m; tailByte = null; }
          if (chunk.byteLength % 2) { tailByte = chunk.slice(chunk.byteLength - 1); chunk = chunk.subarray(0, chunk.byteLength - 1); }
          u.push(chunk);
        }
      } catch { /* обрыв загрузки — договорим то, что пришло */ } finally { try { reader.releaseLock(); } catch { /* ignore */ } }
    } else if (src) {
      const bytes = src instanceof Uint8Array ? src : new Uint8Array(src);
      u.push(bytes.subarray(0, bytes.byteLength - (bytes.byteLength % 2)));
    }
    return u.end();
  }

  /** Прервать всё, что звучит и стоит в очереди (человек заговорил, пауза, закрытие). */
  stop() {
    this.abortedBefore = this.seq;
    if (this.speaking()) this.tail = { text: this.current, until: performance.now() + 1500 };
    this.until = 0;
    this.player.stop();
    this.avatar()?.stop();
  }

  /** Приглушить голос на время, пока решаем, перебивает ли человек (первая ступень перебивания). */
  duck(on: boolean) {
    this.player.setVolume(on ? 0.35 : 1);
    this.avatar()?.duck?.(on);
  }

  level(): number { return this.player.level(); }

  close() { this.stop(); this.player.close(); }
}
