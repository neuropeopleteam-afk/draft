// «Надиктовать» у поля потребности работодателя (VOICE_NEED_ENABLED, docs/VOICE.md). Запись — общий хук Я15
// components/voice (useVoiceRecorder: getUserMedia + MediaRecorder + уровень сигнала), здесь — только экран потребности:
// явное согласие (один раз за вкладку) → разрешение микрофона браузером → запись ≤ max секунд с индикатором уровня и
// «Стоп» → распознавание на сервере (POST /employer/needs/voice, функция движка интервью stt) → текст в поле, его можно
// поправить. Ничего не сохраняется и не отправляется само: разбор — по кнопке «Разобрать требования». Любой сбой (нет
// микрофона, отказ, старый браузер, таймаут, поставщик) → понятное сообщение и ввод с клавиатуры.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { useMeta } from "../lib/meta";
import { postAudio, useVoiceRecorder, type RecErrorCode } from "./voice";

const MSG: Record<RecErrorCode, string> = {
  unsupported: "Этот браузер не умеет записывать звук — введите текст с клавиатуры.",
  denied: "Доступ к микрофону не разрешён. Разрешите его в настройках сайта (значок слева от адреса) или введите текст с клавиатуры.",
  no_device: "Микрофон не найден — подключите его или введите текст с клавиатуры.",
  too_large: "Запись слишком большая — надиктуйте короче или введите текст с клавиатуры.",
  empty: "Запись пустая — попробуйте ещё раз или введите текст с клавиатуры.",
  failed: "Не удалось включить микрофон — введите текст с клавиатуры.",
};
const MIN_SECONDS = 0.7;
const CONSENT_KEY = "voice_need_consent";
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** Признак из /api/meta: null — флаг выключен, кнопки нет. */
export function useVoiceNeed() {
  const v = useMeta()?.voice_need;
  return v?.enabled ? v : null;
}

/** Индикатор уровня микрофона: ширина полосы по level() каждый кадр, без перерисовки React. */
function LevelBar({ level }: { level: () => number }) {
  const bar = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let raf = 0;
    const loop = () => { if (bar.current) bar.current.style.width = `${Math.round(level() * 100)}%`; raf = requestAnimationFrame(loop); };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [level]);
  return (
    <span className="h-2 w-24 overflow-hidden rounded-full bg-brand-night/10" aria-hidden="true">
      <span ref={bar} className="block h-full w-0 rounded-full bg-brand-strong" data-testid="voice-level" />
    </span>
  );
}

/** Кнопка «Надиктовать». onText — вставить расшифровку в поле fieldId (вызывающий решает, дописать или заменить). */
export function DictateNeed({ fieldId, disabled, onText }: { fieldId: string; disabled?: boolean; onText: (text: string) => void }) {
  const v = useVoiceNeed();
  const max = v?.max_seconds ?? 60;
  const consent = v?.consent_version ?? "";
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [cut, setCut] = useState(false);
  const focusField = useCallback(() => window.setTimeout(() => document.getElementById(fieldId)?.focus(), 0), [fieldId]);
  const rec = useVoiceRecorder({
    maxSeconds: max, maxBytes: 3 * 1024 * 1024,
    onError: (_m, code) => setError(MSG[code]),
    onBlob: async (blob, seconds) => {
      if (seconds < MIN_SECONDS) { setError("Запись слишком короткая — нажмите «Надиктовать», говорите, затем «Стоп»."); return; }
      setCut(seconds >= max);
      setBusy(true);
      try {
        const q = new URLSearchParams({ consent, duration_ms: String(Math.round(seconds * 1000)) });
        const r = await postAudio(`/employer/needs/voice?${q}`, blob);
        onText(r.text);
        setNote(r.stub ? "Заглушка: распознавание не подключено, в поле подставлен пример текста — поправьте его под свою вакансию."
          : "Текст распознан и добавлен в поле — проверьте и поправьте ошибки распознавания.");
        focusField();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Нет связи с сервером — введите текст с клавиатуры.");
      } finally { setBusy(false); }
    },
  });
  if (!v) return null;
  const agreed = () => { try { return sessionStorage.getItem(CONSENT_KEY) === consent; } catch { return false; } };
  const go = () => { setError(null); setNote(null); setCut(false); void rec.start(); };
  const begin = () => { if (!rec.supported) { setError(MSG.unsupported); return; } if (agreed()) go(); else { setError(null); setAsk(true); } };
  const accept = () => { try { sessionStorage.setItem(CONSENT_KEY, consent); } catch { /* приватный режим — спросим снова */ } setAsk(false); go(); };
  const keyboard = () => { setError(null); setAsk(false); focusField(); };
  const on = rec.state === "recording" || rec.state === "stopping";
  return (
    <div className="space-y-2" data-testid="voice-need">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
        {on ? (
          <>
            <button type="button" className="btn-primary" disabled={rec.state === "stopping"} onClick={rec.stop} data-testid="voice-stop">Стоп</button>
            <span className="inline-flex items-center gap-2 tabular-nums text-brand-night" data-testid="voice-recording">
              <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-brand-strong" aria-hidden="true" />
              Идёт запись · {mmss(rec.seconds)} из {mmss(max)}
            </span>
            <LevelBar level={rec.level} />
            <button type="button" className="font-semibold text-brand-plum hover:underline" onClick={rec.cancel}>Отменить</button>
          </>
        ) : (
          <>
            <button type="button" className="btn-ghost" disabled={disabled || busy || ask || rec.state !== "idle"} onClick={begin}
              data-testid="voice-start" aria-describedby="voice-need-hint">
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
              {rec.state === "requesting" ? "Ждём разрешения микрофона…" : busy ? "Распознаём…" : "Надиктовать"}
            </button>
            <span id="voice-need-hint" className="text-brand-ink/65">До {max} с голосом — текст появится в поле, его можно поправить.{v.stub ? " Сейчас — заглушка: вместо распознавания подставится пример." : ""}</span>
          </>
        )}
      </div>
      <p className="sr-only" role="status">{on ? "Идёт запись. Нажмите «Стоп», когда закончите." : busy ? "Распознаём запись…" : ""}</p>
      {ask && (
        <div className="rounded-xl border border-brand-lavender/30 bg-[#F3F2FB] p-3 text-sm text-brand-night" role="group" aria-label="Согласие на распознавание записи" data-testid="voice-consent">
          <p>{v.consent_text}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className="btn-primary" onClick={accept} data-testid="voice-consent-ok">Согласен, включить микрофон</button>
            <button type="button" className="btn-ghost" onClick={keyboard}>Ввести текстом</button>
          </div>
        </div>
      )}
      {error && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-brand/30 bg-brand-blush/40 px-3 py-2 text-sm text-brand-plum" role="alert" data-testid="voice-error">
          <span className="min-w-0 flex-1 break-words">{error}</span>
          <button type="button" className="font-semibold underline-offset-2 hover:underline" onClick={keyboard}>Ввести текстом</button>
        </div>
      )}
      {note && !error && (
        <p className="text-xs text-brand-ink/75" role="status" data-testid="voice-note">
          {note}{cut ? ` Запись остановлена на ${max} с.` : ""} Разбор начнётся по кнопке «Разобрать требования».
        </p>
      )}
    </div>
  );
}
