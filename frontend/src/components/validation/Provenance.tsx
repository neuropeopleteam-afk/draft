import { Alert, NB, pct, useApi } from "../ui";
import { NUMBERS } from "../../lib/numbers";

/** Я8: происхождение каждого числа /validation и /criteria (backend: app/modules/validation/provenance.py).
 *  Одна строка «синтетика / модель / люди · дата · SHA алгоритма · банк · команда воспроизведения» — из JSON
 *  расчёта, не текстом страницы; снимки разных банков разделены: «текущий» и «исторический». */

export type Prov = {
  src: string; kind: string; kind_label: string; title?: string; command?: string | null; sections?: string[];
  date?: string | null; commit?: string | null; bank?: string | null; bank_families?: number | null;
  bank_current?: boolean | null; snapshot: string;
};

const KIND_CLS: Record<string, string> = {
  synthetic: "bg-[#F3F2FB] text-brand-night ring-brand-night/15",
  model: "bg-amber-50 text-amber-900 ring-amber-200",
  mixed: "bg-amber-50 text-amber-900 ring-amber-200",
  people: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  rules: "bg-brand-blush/50 text-brand-plum ring-brand/20",
  live: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  tests: "bg-white text-brand-night ring-brand-night/20",
  doc: "bg-white text-brand-night ring-brand-night/20",
  measured: "bg-[#F3F2FB] text-brand-night ring-brand-night/15",
  yours: "bg-emerald-50 text-emerald-800 ring-emerald-200",
};
const SNAP: Record<string, string> = {
  current: "текущий снимок", historical: "исторический снимок", no_bank: "от банка не зависит",
  bank_unknown: "банк не записан", live: "по базе при запросе", missing: "не посчитано", code: "по коду этой версии",
};
const d10 = (v?: string | null) => (v ? `${v.slice(8, 10)}.${v.slice(5, 7)}.${v.slice(0, 4)}` : null);

/** Чип вида данных: «синтетика», «модель, не люди», «люди», «правила на демо-данных». */
export function KindChip({ p }: { p: Pick<Prov, "kind" | "kind_label"> }) {
  return <span className={`inline-flex items-center rounded-md px-1.5 py-px text-xs font-bold uppercase tracking-[0.06em] ring-1 ${KIND_CLS[p.kind] ?? KIND_CLS.synthetic}`}>{p.kind_label}</span>;
}

export function ProvenanceLine({ p, className = "" }: { p?: Prov | null; className?: string }) {
  if (!p) return null;
  const bankNowFamilies = NUMBERS.bank?.families;
  const famCount = p.bank_families && p.bank_families >= 1000 ? p.bank_families : bankNowFamilies;
  const bankLabel = p.bank ? (famCount ? `банк ${famCount.toLocaleString("ru-RU")}${NB}семейств` : "банк продукта") : p.snapshot === "no_bank" ? "банк не нужен" : p.snapshot === "live" ? null : "банк продукта";
  const commit = p.commit && p.commit !== "unknown" ? p.commit : null;
  const plainParts = [d10(p.date), bankLabel].filter(Boolean);
  const snapLabel = p.snapshot === "historical" ? "снимок расчёта" : (SNAP[p.snapshot] ?? p.snapshot);
  return (
    <span className={`flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs leading-snug text-brand-ink/70 [overflow-wrap:anywhere] ${className}`} data-testid="provenance-line" data-snapshot={p.snapshot} data-kind={p.kind}>
      <KindChip p={p} />
      {plainParts.map((x, i) => <span key={i}>{i ? "· " : ""}{x}</span>)}
      <span>· {snapLabel}</span>
      {(commit || p.command || p.bank) && (
        <details className="inline-block text-[11px] text-brand-ink/60">
          <summary className="cursor-pointer font-medium text-brand-plum/80 hover:underline">код и пересчёт</summary>
          <span className="mt-0.5 block rounded bg-[#F7F6FC] px-2 py-1">
            {commit ? <>{p.snapshot === "code" || p.snapshot === "live" ? "код" : "алгоритм"} <code>{commit}</code> · </> : null}
            {p.bank ? <>хэш банка <code>{p.bank.slice(0, 8)}</code> · </> : null}
            {p.command ? <code>{p.command}</code> : null}
          </span>
        </details>
      )}
    </span>
  );
}

const SECTION_T: Record<string, string> = {
  headline: "5 чисел", "path-retest": "Весь путь дважды", bench: "Бенчмарк", ablations: "Абляции", "retest-repeats": "Повторы заданий",
  retest: "Повтор", test: "Тест", "other-conditions": "Другие условия измерения", exposure: "Частота показа", leak: "Утечка",
  matching: "Демо-500", junior: "Junior у порога", intern: "Стажёр", grader: "Оценщик ответов", experts: "Модельная панель",
  discrimination: "D и r_pb", calibration: "Калибровка",
};

/** Первый экран /validation: единый снимок NUMBERS.json и реестр источников расчёта. */
export function Snapshots() {
  const { data, error } = useApi<any>("/validation/provenance", []);
  if (error) return <div className="mt-6"><Alert>{error}</Alert></div>;
  if (!data) return null;
  const rows: Prov[] = data.sources ?? [];
  const fam = NUMBERS.bank?.families ?? data.bank_now?.n_families ?? 1504;
  return (
    <section id="snapshots" className="mt-6 scroll-mt-20 rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 sm:p-5" aria-labelledby="snapshots-t" data-testid="validation-snapshots">
      <h2 id="snapshots-t" className="text-base font-bold text-brand-night">
        Единый снимок метрик ({fam.toLocaleString("ru-RU")}{NB}семейств заданий в банке продукта)
      </h2>
      <p className="mt-1 max-w-4xl text-xs leading-relaxed text-brand-ink/75">
        Все ключевые показатели на этой странице сведены к актуальному банку продукта ({fam.toLocaleString("ru-RU")}{NB}семейств, {NUMBERS.bank.variants_20seeds.toLocaleString("ru-RU")}{NB}вариантов). У каждого расчёта ниже явно помечено происхождение данных: <b>симуляция</b> (проверка математической модели на синтетических кандидатах), <b>модельная панель</b> (разметка текста языковыми моделями) или <b>реальные документы и вакансии</b> (протоколы ФСП и вакансии hh.ru).
      </p>
      <details className="mt-3 text-xs text-brand-ink/75">
        <summary className="cursor-pointer font-semibold text-brand-plum hover:underline">
          Реестр всех расчётных таблиц страницы и команды воспроизведения ({rows.length})
        </summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {rows.map((r) => (
            <div key={r.src} className="min-w-0 rounded-xl border border-brand-night/5 bg-[#FBF8FC] p-2.5 text-sm">
              <p className="leading-snug text-brand-night">
                {r.title}{" "}
                <span className="text-xs">
                  {(r.sections ?? []).map((s, i) => (
                    <a key={s} href={`#${s}`} className="font-semibold text-brand-plum underline-offset-2 hover:underline">
                      {i ? ", " : "→ "}{SECTION_T[s] ?? s}
                    </a>
                  ))}
                </span>
              </p>
              <ProvenanceLine p={r} className="mt-0.5" />
            </div>
          ))}
        </div>
        {(data.config ?? []).map((r: Prov & { note?: string }) => (
          <div key={r.src} className="mt-2 min-w-0 border-t border-brand-night/5 pt-2 text-sm" data-testid="snapshots-config">
            <p className="text-xs font-semibold text-brand-night">
              Настройка движка: {r.title} <a href="#exposure" className="font-semibold text-brand-plum underline underline-offset-2">→ Частота показа</a>
            </p>
            <ProvenanceLine p={r} className="mt-0.5" />
          </div>
        ))}
      </details>
    </section>
  );
}

/** Я8 (судья п. 13): рядом с повтором — точность к синтетической истине, завышение, занижение, «без категории». */
export function RetestVsTruth({ v, className = "" }: { v?: any; className?: string }) {
  if (!v) return null;
  const cells: [string, number | null | undefined][] = [["Повтор: грейд совпал", v.retest_exact], ["С истиной: точно", v.exact], ["Выше истинного", v.over], ["Ниже истинного", v.under], ["Без категории", v.no_category]];
  const cleanLead = String(v.lead ?? "")
    .replace(/κw повтора[^—]*—/g, "Согласие при повторе —")
    .replace(/κ повтора/g, "согласие при повторе");
  const cleanCost = String(v.cost ?? "")
    .replace(/\bP\s*≥\s*0,6\b/g, "порог уверенности 60 %")
    .replace(/\bP\s*≥\s*0,8\b/g, "порог уверенности 80 %");
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="retest-vs-truth">
      <p className="text-sm font-semibold leading-snug text-brand-night">{cleanLead}</p>
      <dl className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {cells.map(([k, x], i) => (
          <div key={k} className={`min-w-0 rounded-lg px-2.5 py-1.5 ${i === 0 ? "bg-[#F3F2FB]" : i === 3 ? "bg-brand-blush/40" : "bg-[#FBF8FC]"}`}>
            <dt className="text-[11px] leading-tight text-brand-ink/70">{k}</dt>
            <dd className="text-lg font-extrabold tabular-nums text-brand-night">{pct(x, 1)}</dd>
          </div>
        ))}
      </dl>
      <details className="mt-2 text-xs leading-relaxed text-brand-ink/75">
        <summary className="cursor-pointer font-medium text-brand-plum/85 hover:underline">
          Пояснение про порог уверенности и маршрут дотестирования
        </summary>
        <p className="mt-1">{cleanCost}</p>
      </details>
    </div>
  );
}
