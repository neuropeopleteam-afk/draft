import { useRef, useState } from "react";
import { Alert, NB, errText } from "../../components/ui";
import { apiUpload } from "../../lib/api";

/** Ф5: потребность из файла вакансии. Сервер извлекает текст (PDF, DOCX, TXT; тип — по содержимому), текст
 *  подставляется в поле «Кого вы ищете» и идёт в обычный разбор — работодатель видит и правит его. */
export interface NeedFileInfo {
  text: string; filename: string; kind: "pdf" | "docx" | "txt"; kind_title: string; pages: number | null;
  chars: number; chars_total: number; truncated: boolean; limit: number;
}

const MAX_MB = 5;
const ACCEPT = ".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain";
const EXAMPLE_FILE = "/examples/vacancy_python_middle.docx";
const n = (v: number) => v.toLocaleString("ru-RU").replace(/\s/g, NB);

function chars(v: number) {
  const m10 = v % 10, m100 = v % 100;
  const w = m10 === 1 && m100 !== 11 ? "знак" : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? "знака" : "знаков";
  return `${n(v)}${NB}${w}`;
}

export function NeedFileUpload({ disabled, onText }: { disabled?: boolean; onText: (info: NeedFileInfo) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onFile(f?: File) {
    if (!f) return;
    setErr(null);
    if (f.size > MAX_MB * 1024 * 1024) { setErr(`Файл больше ${MAX_MB}${NB}МБ — загрузите файл поменьше или вставьте текст вручную`); return; }
    setBusy(true);
    try { onText(await apiUpload<NeedFileInfo>("/employer/needs/file", f)); }
    catch (e) { setErr(errText(e)); }
    finally { setBusy(false); if (ref.current) ref.current.value = ""; }
  }

  const off = disabled || busy;
  return (
    <div className="space-y-2" data-testid="need-file">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <label className={`btn-ghost cursor-pointer focus-within:ring-2 focus-within:ring-brand/40 ${off ? "pointer-events-none opacity-60" : ""}`}>
          {busy ? "Читаем файл…" : "Загрузить файл вакансии"}
          <input ref={ref} type="file" accept={ACCEPT} className="sr-only" disabled={off} aria-describedby="need-file-hint"
            onChange={(e) => onFile(e.target.files?.[0])} />
        </label>
        <span id="need-file-hint" className="text-brand-ink/65">
          PDF, DOCX или TXT до {MAX_MB}{NB}МБ. Текст появится в поле выше — его можно поправить.{" "}
          <a className="font-semibold text-brand hover:underline" href={EXAMPLE_FILE} download>Пример файла</a>
        </span>
      </div>
      <Alert>{err}</Alert>
    </div>
  );
}

export function NeedFileNote({ info, edited }: { info: NeedFileInfo; edited: boolean }) {
  const meta = [info.kind_title, info.pages ? `${info.pages}${NB}стр.` : null, chars(info.chars)].filter(Boolean).join(", ");
  return (
    <div className="space-y-1 text-xs text-brand-ink/65" data-testid="need-file-note">
      <p className="break-words">
        Текст из файла «{info.filename}» ({meta}){edited ? ", вы его поправили" : ""}. Разбор — тот же, что у набранного текста: проверьте цитаты и требования ниже.
      </p>
      {info.truncated && (
        <p className="font-semibold text-brand-plum">
          Файл длиннее поля: взяты первые {chars(info.chars)} из {n(info.chars_total)}. Если требования были в конце файла — вставьте их в поле вручную.
        </p>
      )}
    </div>
  );
}
