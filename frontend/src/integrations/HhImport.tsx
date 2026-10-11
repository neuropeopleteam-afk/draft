// hh.ru (Я12): импорт СВОЕЙ вакансии работодателя в черновик и «Рынок по hh.ru» у вилки приглашения.
// Показывается только при HH_ENABLED и токене приложения на сервере (/api/meta → hh.enabled). Поиска и витрины чужих
// вакансий нет (ответ организаторов FTT.6): вакансия — по ссылке или номеру, рынок — только агрегат.
import { useEffect, useState } from "react";
import { Alert, Field, Loading, Modal, catTitle, dt, errText, range, rub, useApi } from "../components/ui";
import { salaryText } from "../components/Salary";
import { api } from "../lib/api";
import { useMeta } from "../lib/meta";

export const useHh = () => useMeta()?.hh?.enabled ?? false;

interface HhPreview {
  hh_id: string; url: string; title: string; employer_name: string | null; own_company: boolean | null; confirm_required: boolean;
  archived: boolean; experience: string | null; conditions: string; salary_hh: string; key_skills: string[]; category_id: string | null;
  stack: string[]; stack_titles: string[]; stack_from_key_skills: string[]; salary_from: number; salary_to: number; salary_basis: string;
  salary_from_hh: boolean; salary_source?: "hh" | "hh_partial" | "market"; work_format: string; city: string | null; description_preview: string; notes: string[];
  state: "new" | "same" | "changed" | "edited"; state_title: string; vacancy_id: string | null; fetched_at: string | null; stub: boolean;
}
type HhImported = HhPreview & { result: "created" | "updated" | "skipped"; text: string; imported_at?: string | null };
const FORMAT: Record<string, string> = { office: "офис", hybrid: "гибрид", remote: "удалённо", any: "любой формат" };

/** Кнопка рядом с «Импортировать из ATS»: ссылка или номер вакансии hh.ru → предпросмотр → черновик. */
export function HhImportButton({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  if (!useHh()) return null;
  return (
    <>
      <button className="btn-ghost" onClick={() => setOpen(true)}>Импортировать с hh.ru</button>
      <HhImportModal open={open} onClose={() => setOpen(false)} onDone={onDone} />
    </>
  );
}

function HhImportModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [ref, setRef] = useState("");
  const [p, setP] = useState<HhPreview | null>(null);
  const [own, setOwn] = useState(false);
  const [busy, setBusy] = useState<"" | "preview" | "import">("");
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<HhImported | null>(null);
  const stub = useMeta()?.hh?.stub;
  useEffect(() => { if (!open) { setP(null); setRes(null); setErr(null); setOwn(false); setBusy(""); } }, [open]);
  async function preview(e?: React.FormEvent) {
    e?.preventDefault();
    if (!ref.trim() || busy) return;
    setBusy("preview"); setErr(null); setP(null); setRes(null); setOwn(false);
    try { setP(await api<HhPreview>(`/employer/vacancies/import/hh/preview?ref=${encodeURIComponent(ref.trim())}`)); }
    catch (x) { setErr(errText(x)); }
    finally { setBusy(""); }
  }
  async function run() {
    if (!p || busy) return;
    setBusy("import"); setErr(null);
    try { const r = await api<HhImported>("/employer/vacancies/import/hh", { body: { ref: p.hh_id, confirm_own: own } }); setRes(r); setP(r); onDone(); }
    catch (x) { setErr(errText(x)); }
    finally { setBusy(""); }
  }
  const canImport = !!p && !res && (p.state === "new" || p.state === "changed") && (!p.confirm_required || own);
  return (
    <Modal open={open} onClose={onClose} title="Импорт своей вакансии с hh.ru">
      <div className="space-y-4 text-sm">
        <p className="text-brand-ink/70">Вставьте ссылку на вакансию вашей компании на hh.ru или её номер. Платформа прочитает её (в hh.ru ничего не меняется), разберёт текст так же, как потребность, и создаст <b>черновик</b> с пометкой «с hh.ru» и ссылкой — проверьте поля и опубликуйте. Чужие вакансии платформа не собирает.</p>
        {stub && <Alert kind="info">Демо-режим: заглушка hh.ru (данные не настоящие). Номера для проверки: 90000001, 90000002, 90000003 (другая компания).</Alert>}
        <form onSubmit={preview} className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1 basis-60"><Field label="Ссылка или номер вакансии" htmlFor="hhref">
            <input id="hhref" className="input" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="https://hh.ru/vacancy/123456789" autoComplete="off" inputMode="url" />
          </Field></div>
          <button className="btn-primary" type="submit" disabled={!ref.trim() || !!busy} aria-busy={busy === "preview"}>{busy === "preview" ? "Читаем hh.ru…" : "Показать"}</button>
        </form>
        <Alert>{err}</Alert>
        {busy === "preview" && <Loading />}
        {p && (
          <div className="space-y-3 rounded-xl border border-brand-night/10 p-4" data-testid="hh-preview">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="min-w-0 font-bold text-brand-night">{p.title}</p>
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${p.state === "new" ? "bg-emerald-50 text-emerald-700" : p.state === "changed" ? "bg-amber-50 text-amber-800" : "bg-gray-100 text-gray-600"}`}>{p.state_title}</span>
            </div>
            <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
              <dt className="text-brand-ink/65">Работодатель в hh.ru</dt><dd className="min-w-0 break-words">{p.employer_name ?? "—"}{p.own_company ? " · совпадает с вашей компанией" : ""}</dd>
              <dt className="text-brand-ink/65">Зарплата в hh.ru</dt><dd>{p.salary_hh}</dd>
              <dt className="text-brand-ink/65">В черновик</dt><dd>{p.category_id ? catTitle(p.category_id) : "категория не определена"} · {salaryText(p.salary_from, p.salary_to, p.salary_basis)}{p.salary_from_hh ? "" : p.salary_source === "hh_partial" ? " (частично из hh.ru, уточните)" : " (рынок, уточните)"} · {FORMAT[p.work_format] ?? p.work_format}{p.city ? ` · ${p.city}` : ""}</dd>
              <dt className="text-brand-ink/65">Стек</dt><dd className="min-w-0 break-words">{p.stack_titles.join(", ") || "—"}{p.stack_from_key_skills.length ? ` (из ключевых навыков hh.ru: ${p.stack_from_key_skills.length})` : ""}</dd>
              {p.conditions && <><dt className="text-brand-ink/65">Условия</dt><dd className="min-w-0 break-words">{p.conditions.replace(/^Условия с hh\.ru — /, "")}</dd></>}
            </dl>
            {p.notes.map((n, i) => <p key={i} className="text-xs text-amber-800">{n}</p>)}
            <p className="text-xs text-brand-ink/65">Разбор текста — правилами, как у потребности (без LLM){p.fetched_at ? ` · прочитано ${dt(p.fetched_at)}` : ""} · <a className="font-semibold text-brand-plum underline" href={p.url} target="_blank" rel="noopener noreferrer">открыть на hh.ru ↗</a></p>
            {p.confirm_required && !res && (
              <label className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={own} onChange={(e) => setOwn(e.target.checked)} /><span>Это вакансия нашей компании — импортирую её как свою</span></label>
            )}
            {res ? (
              <Alert kind={res.result === "skipped" ? "info" : "ok"}>{res.text}{res.imported_at ? ` · импорт ${dt(res.imported_at)}` : ""}. {res.result !== "skipped" && "Черновик — в списке вакансий с пометкой «с hh.ru»."}</Alert>
            ) : (
              <div className="flex flex-wrap justify-end gap-2">
                <button className="btn-ghost" onClick={onClose}>Закрыть</button>
                <button className="btn-primary" disabled={!canImport || !!busy} aria-busy={busy === "import"} onClick={() => void run()}>{busy === "import" ? "Создаём черновик…" : p.state === "changed" ? "Обновить черновик" : "Создать черновик"}</button>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

interface HhMarket {
  available: boolean; reason?: string | null; category_title?: string | null; area?: { id: string; name: string } | null;
  area_requested?: { id: string; name: string } | null; area_fallback?: boolean; grade_by?: string; grade_by_title?: string;
  n?: number; found?: number; median?: number | null; p25?: number | null; p75?: number | null; median_gross?: number | null;
  as_of?: string | null; stale?: boolean; stub?: boolean; few_data?: boolean; shown?: boolean; search_url?: string | null; note?: string | null;
  gross_share?: number | null;
}

/** «Рынок по hh.ru» рядом с вилкой: медиана и p25–p75 вилок живых вакансий роли, грейда и региона (на руки). */
export function HhMarketNote({ cref, needId, categoryId, title = "Рынок по hh.ru", how }: { cref?: string | null; needId?: string | null; categoryId?: string | null; title?: string; how?: React.ReactNode }) {
  const on = useHh();
  const q = new URLSearchParams();
  if (categoryId) q.set("category_id", categoryId);
  if (cref) q.set("ref", cref);
  if (needId) q.set("need_id", needId);
  const { data: m, error, loading } = useApi<HhMarket>(on && q.toString() ? `/employer/market/hh?${q}` : null, [on, q.toString()]);
  // UX-2: how — общее «Как считали» формы приглашения (без hh.ru-данных — отдельной раскрывашкой)
  const howOnly = how ? <details className="text-xs text-brand-night"><summary className="cursor-pointer font-semibold text-brand-plum">Как считали</summary><p className="mt-1 text-brand-ink/80">{how}</p></details> : null;
  if (!on) return howOnly;
  if (loading && !m) return <p className="text-xs text-brand-ink/65" role="status">{title}: считаем по живым вакансиям…</p>;
  if (error) return <><p className="text-xs text-brand-ink/65">{title} сейчас недоступно: {error}</p>{howOnly}</>;
  if (!m) return howOnly;
  if (!m.available) return <><p className="text-xs text-brand-ink/65">{title}: {m.reason}</p>{howOnly}</>;
  const where = `${m.area?.name ?? "—"}${m.area_fallback ? ` (в регионе «${m.area_requested?.name}» мало вакансий)` : ""}`;
  return (
    <div className="rounded-lg bg-[#F3F2FB] px-3 py-2 text-xs text-brand-night" data-testid="hh-market">
      <p>
        <b>{title}</b>{m.category_title ? ` · ${m.category_title}` : ""}:{" "}
        {m.shown
          ? <>{range(m.p25, m.p75)} на руки, медиана {rub(m.median)} <span className="whitespace-nowrap">(≈ {rub(m.median_gross)} до вычета НДФЛ)</span></>
          : <>мало данных — {m.n} {m.n === 1 ? "вакансия" : "вакансий"} с зарплатой, медиану не считаем</>}
        {" "}· {m.n} вакансий · {where} · данные {m.as_of ? dt(m.as_of) : "—"}
        {m.shown && m.few_data && <span className="font-semibold text-brand-plum"> · мало данных, ориентир неустойчивый</span>}
        {m.stale && <span className="font-semibold text-brand-plum"> · hh.ru сейчас не отвечает — показаны прошлые данные</span>}
        {m.stub && <span className="font-semibold text-brand-plum"> · демо-заглушка hh.ru, данные не настоящие</span>}
      </p>
      <details className="mt-1">
        <summary className="cursor-pointer font-semibold text-brand-plum">Как считали</summary>
        <p className="mt-1 text-brand-ink/80">{how}{m.note}{m.search_url && <> <a className="font-semibold text-brand-plum underline" href={m.search_url} target="_blank" rel="noopener noreferrer">Тот же поиск на hh.ru ↗</a></>}</p>
      </details>
    </div>
  );
}
