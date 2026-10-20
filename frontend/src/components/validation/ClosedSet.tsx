import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert, errText, num, pct, ruText } from "../ui";
import { api, apiUrl, tokenStore } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { isJury, juryToken } from "../../lib/jury";

/** A private request-only laboratory; nothing is added to needs or candidate tables. */
export default function ClosedSet() {
  const { me, signIn } = useAuth();
  const loc = useLocation();
  const [content, setContent] = useState("");
  const [format, setFormat] = useState<"json" | "csv">("json");
  const [k, setK] = useState(5);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filename, setFilename] = useState("");
  // Ф6 (В10): форма свёрнута — сначала доказательства («5 чисел» выше), затем свои данные по кнопке; по #closed-set / #evaluate — раскрыта
  const [open, setOpen] = useState(() => window.location.hash === "#closed-set" || window.location.hash === "#evaluate");
  useEffect(() => {
    const h = loc.hash || window.location.hash;
    if (h === "#closed-set" || h === "#evaluate") setOpen(true);
  }, [loc.hash]);
  const body = { content, format, k };
  const authenticate = async () => {
    if (!isJury(me?.email) || !["employer", "admin"].includes(me?.role ?? "")) {
      await signIn((await juryToken("employer")).access_token);
    }
  };
  const run = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      await authenticate();
      setResult(await api("/validation/closed-set/evaluate", { body }));
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const download = async () => {
    setBusy(true); setError("");
    try {
      await authenticate();
      const response = await fetch(apiUrl("/validation/closed-set/export"), {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${tokenStore.get()}` },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error((await response.json()).detail?.message ?? "Не удалось скачать CSV");
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a"); a.href = url; a.download = "closed-set-results.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  return (
    <section id="closed-set" className="mt-12 scroll-mt-20 rounded-2xl border border-brand-night/10 bg-white p-5 md:p-7">
      <span id="evaluate" className="block scroll-mt-20" aria-hidden="true" />
      <p className="text-xs font-semibold uppercase tracking-wider text-brand-plum">Проверка на ваших данных</p>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-72">
          <h2 className="text-xl font-bold text-brand-night">Закрытый набор жюри</h2>
          <p className="mt-1 text-sm leading-relaxed text-brand-ink/70">Свои анонимные потребности и профили (до 50 и 500) — выдача и p@k/nDCG@k на них; данные живут только в памяти запроса.</p>
        </div>
        <button type="button" className="btn-ghost" aria-expanded={open} aria-controls="closed-set-form" onClick={() => setOpen((v) => !v)}>
          {open ? "Свернуть" : "Проверить на своих данных"}
        </button>
      </div>
      {open && <div id="closed-set-form">
      <p className="mt-3 text-sm leading-relaxed text-brand-ink/75">
        Загрузите анонимные потребности, профили и, при наличии, метки релевантности от 0 до 3.
        До 50 потребностей и 500 профилей. Данные существуют только в памяти вашего запроса:
        они не записываются в общий пул и недоступны другим песочницам.
      </p>
      <p className="mt-2 text-sm text-brand-ink/70">
        Поля theta, навыки и достижения — доказательства, заявленные автором набора, а не проверка платформой.
        Без theta профиль не входит в подтверждённую подборку. Не включайте имена и контакты.
        Этот эксперимент разбирает потребность без LLM.
      </p>
      {!isJury(me?.email) && <p className="mt-2 text-xs text-brand-ink/65">
        При проверке откроется ваша демо-песочница в роли работодателя.
      </p>}
      <div className="mt-4 flex flex-wrap gap-3 text-sm font-semibold text-brand-plum">
        <a href={apiUrl("/validation/closed-set/template/json")} download>Скачать шаблон JSON</a>
        <a href={apiUrl("/validation/closed-set/template/csv")} download>Скачать шаблон CSV</a>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-[1fr_auto]">
        <label className="min-w-0 text-sm font-semibold text-brand-night">
          Набор JSON или CSV
          <input type="file" accept=".json,.csv" className="mt-2 block w-full min-w-0 text-xs file:mr-3 file:rounded-lg file:border-0 file:bg-brand-blush file:px-3 file:py-2 file:text-brand-plum"
            onChange={async (e) => {
              setError(""); setResult(null);
              const file = e.target.files?.[0];
              if (!file) return;
              if (file.size > 2_000_000) { setError("Файл не должен превышать 2 МБ"); setContent(""); return; }
              try { setContent(await file.text()); setFormat(file.name.toLowerCase().endsWith(".csv") ? "csv" : "json"); setFilename(file.name); }
              catch { setError("Не удалось прочитать файл"); }
            }} />
          {filename && <p className="mt-1 break-all text-xs font-normal text-brand-ink/65">{filename}</p>}
        </label>
        <label className="text-sm font-semibold text-brand-night">Размер топа k
          <input aria-label="Размер топа k" type="number" min={1} max={50} value={k}
            className="input mt-2 block w-24" onChange={(e) => { setK(Number(e.target.value)); setResult(null); }} />
        </label>
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="btn-primary" disabled={busy || !content || k < 1 || k > 50} onClick={run}>
          {busy ? "Проверяем…" : "Проверить набор в своей песочнице"}
        </button>
        <button className="btn-secondary" disabled={busy || !result} onClick={download}>Скачать выдачу CSV</button>
        {content && <button className="btn-secondary" onClick={() => { setContent(""); setResult(null); setFilename(""); }}>Очистить данные</button>}
      </div>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      {result && <div className="mt-6 space-y-4" aria-live="polite">
        <Alert kind="info">{result.note}</Alert>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            ["Профилей", num(result.n_candidates, 0)], ["Потребностей", num(result.n_needs, 0)],
            [`p@${k}`, pct(result.summary?.[`p@${k}`], 1)],
            [`nDCG@${k}`, num(result.summary?.[`ndcg@${k}`], 3)],
          ].map(([label, value]) => <div key={label} className="rounded-xl bg-brand-blush/30 p-3">
            <p className="text-xs text-brand-ink/65">{label}</p><p className="mt-1 text-xl font-bold text-brand-night">{value}</p>
          </div>)}
        </div>
        {result.summary && <p className="text-sm text-brand-ink/70">Метрики по {num(result.evaluated_needs, 0)} из {num(result.n_needs, 0)} потребностей с полной разметкой.</p>}
        {!result.summary && <p className="text-sm text-brand-ink/70">Нет полной разметки: выдача готова, метрики не рассчитываются.</p>}
        {result.per_need.map((need: any) => <details key={need.need_id} className="rounded-xl border border-brand-night/10 p-4" open={result.n_needs === 1}>
          <summary className="cursor-pointer break-all text-sm font-semibold text-brand-night">
            {need.need_id} · выдано {num(need.returned, 0)} · покрытие метками {pct(need.label_coverage)}
          </summary>
          {need.requirements.coverage && <p className="mt-3 text-sm text-brand-plum">{need.requirements.coverage.message} Не проверяется: {need.requirements.coverage.not_tested}.</p>}
          {!need.results.length && <p className="mt-3 text-sm">Нет профилей в подтверждённой категории потребности.</p>}
          <ol className="mt-3 space-y-3">
            {need.results.map((row: any) => <li key={row.candidate_id} className="min-w-0 rounded-lg bg-[#FBF8FC] p-3 text-sm">
              <b className="break-all">{num(row.rank, 0)}. {row.candidate_id}</b> · скор {num(row.score, 3)} · метка {row.relevance == null ? "нет" : num(row.relevance, 0)}
              <ul className="mt-2 space-y-1 text-xs leading-relaxed text-brand-ink/75">
                {row.reasons.map((r: any, i: number) => <li key={i}><b>{r.requirement} [{r.level}]: </b>{ruText(r.text)}</li>)}
              </ul>
            </li>)}
          </ol>
        </details>)}
      </div>}
      </div>}
    </section>
  );
}
