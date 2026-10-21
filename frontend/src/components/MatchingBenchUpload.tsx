import { useState } from "react";
import { Alert, errText, num, pct } from "./ui";
import { api, apiUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { isJury, juryToken } from "../lib/jury";
import { MatchExplain } from "./MatchExplain";

export interface MatchingBenchUploadProps {
  className?: string;
  defaultOpen?: boolean;
}

/**
 * Режим «Принесите свой набор» для жюри (критерий ТЗ 35 % — проверка качества подбора на тестовом наборе пар).
 * Принимает JSON или CSV (вакансии, кандидаты или их профили/резюме, необязательная разметка 0..3),
 * ранжирует нашим движком, выводит P@5, P@10, nDCG@10, MRR, топ-N с объяснением и кнопку скачивания CSV.
 */
export function MatchingBenchUpload({
  className = "",
  defaultOpen = true,
}: MatchingBenchUploadProps) {
  const { me, signIn } = useAuth();
  const [open, setOpen] = useState(defaultOpen);
  const [content, setContent] = useState("");
  const [format, setFormat] = useState<"json" | "csv">("json");
  const [k, setK] = useState(5);
  const [filename, setFilename] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<any>(null);

  const ensureSandboxEmployer = async () => {
    if (!isJury(me?.email) || !["employer", "admin"].includes(me?.role ?? "")) {
      await signIn((await juryToken("employer")).access_token);
    }
  };

  const loadSampleAndRun = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const sampleRes = await fetch(apiUrl("/employer/benchmark/sample?format=json"));
      const sampleText = await sampleRes.text();
      setContent(sampleText);
      setFormat("json");
      setFilename("jury-benchmark-sample.json");
      await ensureSandboxEmployer();
      const evalRes = await api("/employer/benchmark/upload", {
        body: { content: sampleText, format: "json", k },
      });
      setResult(evalRes);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const runUpload = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      await ensureSandboxEmployer();
      const evalRes = await api("/employer/benchmark/upload", {
        body: { content, format, k },
      });
      setResult(evalRes);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const downloadCsv = () => {
    if (!result?.csv_export) return;
    const blob = new Blob([result.csv_export], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "jury-benchmark-results.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section
      id="jury-upload-bench"
      data-testid="matching-bench-upload"
      className={`rounded-2xl border border-brand-night/10 bg-white p-5 md:p-7 ${className}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-72">
          <p className="text-xs font-semibold uppercase tracking-wider text-brand-plum">
            Критерий 35 % · Проверка на тестовом наборе пар «вакансия — кандидат»
          </p>
          <h3 className="mt-1 text-xl font-extrabold tracking-tight text-brand-night">
            Режим «Принесите свой набор» для жюри
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-brand-ink/75">
            Загрузите собственный набор вакансий, профилей кандидатов и (при наличии) эталонную разметку
            релевантности в CSV или JSON. Движок подбора рассчитает P@5, P@10, nDCG@10 и MRR, покажет топ-{k} по
            каждой вакансии с полным объяснением («Почему №1 выше №2») и сформирует CSV-выгрузку.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="btn-ghost text-sm"
        >
          {open ? "Свернуть" : "Развернуть проверку"}
        </button>
      </div>

      {open && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-brand-plum">
            <a
              href={apiUrl("/employer/benchmark/sample?format=json")}
              download="jury-benchmark-sample.json"
              className="rounded-lg bg-brand-blush/40 px-3 py-1.5 hover:bg-brand-blush/70"
            >
              Скачать образец JSON
            </a>
            <a
              href={apiUrl("/employer/benchmark/sample?format=csv")}
              download="jury-benchmark-sample.csv"
              className="rounded-lg bg-brand-blush/40 px-3 py-1.5 hover:bg-brand-blush/70"
            >
              Скачать образец CSV
            </a>
            <button
              type="button"
              disabled={busy}
              onClick={loadSampleAndRun}
              data-testid="bench-upload-run-sample"
              className="rounded-lg bg-brand-night px-3 py-1.5 text-white hover:bg-brand-night/90 disabled:opacity-50"
            >
              {busy ? "Считаем…" : "Загрузить демонстрационный набор и проверить в 1 клик"}
            </button>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-[1fr_auto]">
            <label className="min-w-0 text-sm font-semibold text-brand-night">
              Файл набора (JSON или CSV, до 2 МБ)
              <input
                type="file"
                accept=".json,.csv"
                className="mt-2 block w-full min-w-0 text-xs file:mr-3 file:rounded-lg file:border-0 file:bg-brand-blush file:px-3 file:py-2 file:font-semibold file:text-brand-plum"
                onChange={async (e) => {
                  setError("");
                  setResult(null);
                  const file = e.target.files?.[0];
                  if (!file) return;
                  if (file.size > 2_000_000) {
                    setError("Размер файла не должен превышать 2 МБ");
                    setContent("");
                    return;
                  }
                  try {
                    const txt = await file.text();
                    setContent(txt);
                    setFormat(file.name.toLowerCase().endsWith(".csv") ? "csv" : "json");
                    setFilename(file.name);
                  } catch {
                    setError("Не удалось прочитать файл");
                  }
                }}
              />
              {filename && (
                <p className="mt-1 break-all text-xs font-normal text-brand-ink/65">
                  Выбран файл: {filename}
                </p>
              )}
            </label>

            <label className="text-sm font-semibold text-brand-night">
              Размер топа N
              <input
                aria-label="Размер топа N"
                type="number"
                min={1}
                max={50}
                value={k}
                onChange={(e) => {
                  setK(Math.max(1, Math.min(50, Number(e.target.value) || 5)));
                  setResult(null);
                }}
                className="input mt-2 block w-24"
              />
            </label>
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={busy || !content}
              onClick={runUpload}
              data-testid="bench-upload-submit"
              className="btn-primary"
            >
              {busy ? "Ранжируем…" : "Проверить загруженный набор"}
            </button>
            {result?.csv_export && (
              <button
                type="button"
                onClick={downloadCsv}
                data-testid="bench-upload-download-csv"
                className="btn-secondary"
              >
                Скачать результат CSV
              </button>
            )}
            {content && (
              <button
                type="button"
                onClick={() => {
                  setContent("");
                  setResult(null);
                  setFilename("");
                  setError("");
                }}
                className="btn-secondary"
              >
                Очистить
              </button>
            )}
          </div>

          {error && (
            <div className="mt-4">
              <Alert>{error}</Alert>
            </div>
          )}

          {result && (
            <div className="mt-6 space-y-5" aria-live="polite" data-testid="bench-upload-results">
              <Alert kind="info">{result.note}</Alert>
              {result.label_scale?.text && (
                <p className="text-xs text-brand-ink/70" data-testid="bench-upload-scale">
                  {result.label_scale.text}
                </p>
              )}

              {/* Сводка метрик */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6">
                {[
                  ["Вакансий", num(result.n_needs, 0)],
                  ["Кандидатов", num(result.n_candidates, 0)],
                  ["P@5", result.summary ? pct(result.summary["p@5"], 1) : "—"],
                  ["P@10", result.summary ? pct(result.summary["p@10"], 1) : "—"],
                  ["nDCG@10", result.summary ? num(result.summary["ndcg@10"], 3) : "—"],
                  ["MRR", result.summary ? num(result.summary["mrr"], 3) : "—"],
                ].map(([label, val]) => (
                  <div key={label} className="rounded-xl bg-[#FBF9FE] p-3 ring-1 ring-brand-night/10">
                    <p className="text-xs font-semibold text-brand-ink/65">{label}</p>
                    <p className="mt-1 text-xl font-extrabold text-brand-night tabular-nums">{val}</p>
                  </div>
                ))}
              </div>

              {/* Сравнение с базовой линией по самоописанию (T0) */}
              {result.summary && result.baseline_t0 && (
                <div className="rounded-xl bg-emerald-50/70 p-3.5 text-xs text-emerald-950 ring-1 ring-emerald-600/20">
                  <span className="font-bold">Преимущество подтверждённого профиля над резюме (самоописание): </span>
                  <span>
                    P@5 {pct(result.summary["p@5"], 1)} против {pct(result.baseline_t0["p@5"], 1)} у отбора по
                    ключевым словам резюме · nDCG@10 {num(result.summary["ndcg@10"], 3)} против{" "}
                    {num(result.baseline_t0["ndcg@10"], 3)} · MRR {num(result.summary["mrr"], 3)} против{" "}
                    {num(result.baseline_t0["mrr"], 3)}. Кандидаты с «раздутым» резюме без подтверждения тестом
                    отсечены с первых мест.
                  </span>
                </div>
              )}

              {/* Выдача по каждой вакансии */}
              <div className="space-y-4">
                {(result.per_need || []).map((n: any, idx: number) => (
                  <details
                    key={n.need_id}
                    open={idx === 0}
                    className="rounded-2xl border border-brand-night/10 bg-[#FBF9FE] p-4"
                  >
                    <summary className="cursor-pointer text-sm font-bold text-brand-night">
                      {n.title || n.need_id} ({n.need_id}) · найдено {n.returned} из {n.eligible}
                      {n.metrics && (
                        <span className="ml-2 font-normal text-brand-plum">
                          · P@5 {pct(n.metrics["p@5"], 0)} · nDCG@10 {num(n.metrics["ndcg@10"], 2)} · MRR{" "}
                          {num(n.metrics["mrr"], 2)}
                        </span>
                      )}
                    </summary>

                    <div className="mt-3 space-y-3">
                      {(n.results || []).map((row: any) => (
                        <div key={row.candidate_id} className="rounded-xl bg-white p-3.5 ring-1 ring-brand-night/10">
                          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                            <span className="text-sm font-bold text-brand-night">
                              #{row.rank} · {row.candidate_id}
                            </span>
                            <div className="flex flex-wrap items-center gap-2 text-xs">
                              {row.relevance != null && (
                                <span
                                  className={`rounded-full px-2.5 py-0.5 font-semibold ${
                                    row.relevance >= 2
                                      ? "bg-emerald-50 text-emerald-900"
                                      : "bg-rose-50 text-rose-900"
                                  }`}
                                >
                                  Эталонная метка: {row.relevance} из 3
                                </span>
                              )}
                              <span className="font-bold text-brand-plum tabular-nums">
                                Балл: {row.score100} / 100
                              </span>
                            </div>
                          </div>
                          <MatchExplain explain={row.explain} item={row} compact />
                        </div>
                      ))}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default MatchingBenchUpload;
