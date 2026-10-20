// Правила живого разговора: сборка фразы из промежуточных и окончательных сегментов распознавания, конец хода,
// отличие собственного эха ведущей от настоящей реплики человека и решение «перебить ведущую» (barge-in).
import type { SttEvent } from "./listener";

export class SpeechBuffer {
  private finals: string[] = [];
  private interim = "";
  version = 0;
  lastChangeAt = 0;

  accept(e: SttEvent): boolean {
    if (e.type !== "interim" && e.type !== "final") return false;
    const text = e.text.trim();
    if (!text) return false;
    if (e.type === "interim") {
      if (text === this.interim) return false;
      this.interim = text;
    } else {
      this.finals.push(text);
      this.interim = "";
    }
    this.version++;
    this.lastChangeAt = performance.now();
    return true;
  }

  read(): string { return [...this.finals, this.interim].filter(Boolean).join(" ").replace(/\s+/g, " ").trim(); }
  hasFinal(): boolean { return this.finals.length > 0; }
  take(): string { const t = this.read(); this.reset(); return t; }
  reset() { this.finals = []; this.interim = ""; this.version++; this.lastChangeAt = 0; }
}

export const words = (t: string): string[] => (t.toLowerCase().match(/[a-zа-яё0-9]+/giu) ?? []).map((w) => w.replace(/ё/g, "е"));

const BACKCHANNEL = new Set(["угу", "ага", "ага-ага", "да", "ну", "так", "понятно", "ясно", "хорошо", "ок", "окей", "ладно",
  "мм", "м", "ммм", "э", "эээ", "а", "ой", "класс", "супер", "отлично", "интересно", "здорово", "вот", "спасибо"]);
// слова, которыми человек явно обращается к ведущей — перебивают сразу, даже одно слово
const STOP_WORDS = /^(стоп|стой|стойте|подожди|подождите|погоди|погодите|пауза|хватит|елена|лена|секунду|минуту|извините|простите|вопрос|дальше|назад|повтори|повторите|остановись|остановитесь|замолчи)$/u;
const UNFINISHED = /(?:^|\s)(и|а|но|или|что|чтобы|потому|поэтому|если|когда|как|это|ну|вот|например|то есть|типа|в|на|с|по|для|из|от|к|у|о|об|про|за|который|которая|которые|э+|м+)$/u;
const END_MARKERS = /(?:^|\s)(всё|все|я закончил|я закончила|у меня всё|у меня все|это всё|это все|закончил|закончила|готово|ответ такой)[\s.!]*$/u;

/** Доля слов реплики, которые встречаются в тексте ведущей (эхо из динамиков, просочившееся мимо эхоподавления). */
export function echoShare(heard: string, hers: string): number {
  const h = words(heard);
  if (!h.length || !hers) return 0;
  const set = new Set(words(hers));
  let hit = 0;
  for (const w of h) if (set.has(w)) hit++;
  return hit / h.length;
}

export function isEcho(heard: string, hers: string): boolean {
  const h = words(heard);
  if (!h.length || !hers) return false;
  const share = echoShare(heard, hers);
  return h.length <= 2 ? share >= 1 : share >= 0.6;
}

export function isBackchannel(text: string): boolean {
  const w = words(text);
  return w.length > 0 && w.length <= 2 && w.every((x) => BACKCHANNEL.has(x));
}

export function hasStopWord(text: string): boolean {
  return words(text).slice(0, 3).some((w) => STOP_WORDS.test(w));
}

/**
 * Перебить ведущую? heard — что распознано, пока она говорит; hers — её текущая реплика; sinceStartMs — сколько она уже
 * говорит. Эхо и поддакивания не перебивают; первые ~0,9 с реплики даём ей начать мысль (кроме явных «стоп», «Елена»).
 */
export function bargeIn(heard: string, hers: string, sinceStartMs: number, minWords = 2): boolean {
  const w = words(heard);
  if (!w.length) return false;
  if (isEcho(heard, hers)) return false;
  if (hasStopWord(heard)) return true;
  if (isBackchannel(heard)) return false;
  if (sinceStartMs < 900) return false;
  return w.length >= minWords;
}

/** Пауза после окончания фразы до отправки хода. mode: guide — короткие команды и вопросы; answer — развёрнутый ответ. */
export function endDelay(text: string, mode: "guide" | "answer" = "guide"): number {
  const t = text.trim().toLowerCase();
  const n = words(t).length;
  if (mode === "answer") {
    if (END_MARKERS.test(t)) return 250;
    if (UNFINISHED.test(t)) return 3200;
    return n < 4 ? 2600 : 1900;
  }
  if (UNFINISHED.test(t)) return 1500;
  if (/[?]$/.test(t)) return 250;
  if (n <= 3) return 350;
  return 650;
}

export function stripEndMarker(text: string): string {
  return text.replace(/[\s,]*(?:я закончил|я закончила|у меня всё|у меня все|это всё|это все|ответ такой)[\s.!]*$/iu, "").trim() || text;
}
