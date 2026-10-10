import { Alert, NB, pct, useApi } from "../ui";

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
  return <span className={`inline-flex items-center rounded-md px-1.5 py-px text-[10px] font-bold uppercase tracking-[0.06em] ring-1 ${KIND_CLS[p.kind] ?? KIND_CLS.synthetic}`}>{p.kind_label}</span>;
}

export function ProvenanceLine({ p, className = "" }: { p?: Prov | null; className?: string }) {
  if (!p) return null;
  const bank = p.bank ? `банк ${p.bank.slice(0, 8)}${p.bank_families ? ` (${p.bank_families}${NB}семейств)` : ""}` : p.snapshot === "no_bank" ? "банк не нужен" : p.snapshot === "live" ? null : "банк не записан";
  const parts = [d10(p.date), p.commit ? <>{p.snapshot === "code" || p.snapshot === "live" ? "код" : "алгоритм"} <code>{p.commit}</code></> : p.snapshot === "live" ? null : "коммит не записан", bank,
    p.command ? <code>{p.command}</code> : null].filter(Boolean);
  return (
    <span className={`flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] leading-snug text-brand-ink/70 [overflow-wrap:anywhere] ${className}`} data-testid="provenance-line" data-snapshot={p.snapshot} data-kind={p.kind}>
      <KindChip p={p} />
      {parts.map((x, i) => <span key={i}>{i ? "· " : ""}{x}</span>)}
      <span className={p.snapshot === "historical" ? "font-semibold text-brand-plum" : ""}>· {SNAP[p.snapshot] ?? p.snapshot}</span>
    </span>
  );
}

const SECTION_T: Record<string, string> = {
  headline: "5 чисел", "path-retest": "Весь путь дважды", bench: "Бенчмарк", ablations: "Абляции", "retest-repeats": "Повторы заданий",
  retest: "Повтор", test: "Тест", competitors: "Условия конкурентов", exposure: "Частота показа", leak: "Утечка",
  matching: "Демо-500", junior: "Junior у порога", intern: "Стажёр", grader: "Оценщик ответов", experts: "Модельная панель",
  discrimination: "D и r_pb", calibration: "Калибровка",
};

/** Первый экран /validation: из каких снимков числа страницы — текущий банк или прошлый (с датой). */
export function Snapshots() {
  const { data, error } = useApi<any>("/validation/provenance", []);
  if (error) return <div className="mt-6"><Alert>{error}</Alert></div>;
  if (!data) return null;
  const rows: Prov[] = data.sources ?? [];
  const groups: [string, string, Prov[]][] = [
    ["current", `Текущий снимок — банк в продукте (${data.bank_now?.n_families ?? "—"}${NB}семейств, ${data.bank_now?.content_hash?.slice(0, 8) ?? "—"})`, rows.filter((r) => r.snapshot === "current" || r.snapshot === "no_bank")],
    ["historical", "Исторические снимки — посчитаны на прошлом банке или банк не записан: числа подписаны датой", rows.filter((r) => r.snapshot === "historical" || r.snapshot === "bank_unknown")],
  ];
  return (
    <section id="snapshots" className="mt-6 scroll-mt-20 rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 sm:p-5" aria-labelledby="snapshots-t" data-testid="validation-snapshots">
      <h2 id="snapshots-t" className="text-base font-bold text-brand-night">Откуда числа этой страницы</h2>
      <p className="mt-1 max-w-4xl text-xs leading-relaxed text-brand-ink/70">{data.how_to_read} Код стенда <code>{data.code_commit}</code>; людей в расчётах ниже нет — синтетика и модели{data.one_snapshot ? "." : "; снимки ещё не сведены в один."}</p>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        {groups.filter(([, , g]) => g.length).map(([k, t, g]) => (
          <div key={k} className="min-w-0" data-testid={`snapshots-${k}`}>
            <p className={`text-xs font-semibold ${k === "historical" ? "text-brand-plum" : "text-brand-night"}`}>{t}</p>
            <ul className="mt-1.5 space-y-2">
              {g.map((r) => (
                <li key={r.src} className="min-w-0 border-t border-brand-night/5 pt-1.5 text-sm">
                  <p className="leading-snug text-brand-night">{r.title}{" "}
                    <span className="text-xs">{(r.sections ?? []).map((s, i) => <a key={s} href={`#${s}`} className="font-semibold text-brand-plum underline-offset-2 hover:underline">{i ? ", " : "→ "}{SECTION_T[s] ?? s}</a>)}</span></p>
                  <ProvenanceLine p={r} className="mt-0.5" />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Я8 (судья п. 13): рядом с κ повтора — точность к синтетической истине, завышение, занижение, «без категории»,
 *  цена порога P ≥ 0,8 и маршрут восстановления (backend: headline.retest_vs_truth, числа make path-retest). */
export function RetestVsTruth({ v, className = "" }: { v?: any; className?: string }) {
  if (!v) return null;
  const cells: [string, number | null | undefined][] = [["Повтор: грейд совпал", v.retest_exact], ["С истиной: точно", v.exact], ["Выше истинного", v.over], ["Ниже истинного", v.under], ["Без категории", v.no_category]];
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="retest-vs-truth">
      <p className="text-sm font-semibold leading-snug text-brand-night">{v.lead}</p>
      <dl className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {cells.map(([k, x], i) => (
          <div key={k} className={`min-w-0 rounded-lg px-2.5 py-1.5 ${i === 0 ? "bg-[#F3F2FB]" : i === 3 ? "bg-brand-blush/40" : "bg-[#FBF8FC]"}`}>
            <dt className="text-[11px] leading-tight text-brand-ink/70">{k}</dt>
            <dd className="text-lg font-extrabold tabular-nums text-brand-night">{pct(x, 1)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/75">{v.cost}</p>
    </div>
  );
}
