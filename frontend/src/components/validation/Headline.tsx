import { Alert, Loading, NB, num, pct, signed, useApi } from "../ui";
import { ProvenanceLine, RetestVsTruth } from "./Provenance";
import { ScrollX } from "../A11y";
import { fmtPct, getHhMatchMetrics, getTop5, getTop5Hard, getTop5Meta, NUMBERS } from "../../lib/numbers";
import { plural } from "../ui";

/** Первый экран /validation: «5 чисел, которые доказывают механику» (backend: app/modules/validation/headline.py).
 *  Каждое число — из расчёта с подписью мира; нет расчёта — нет числа. */

export type Signature = { world?: string; seed?: number; config_hash?: string; commit?: string; command?: string; generated_at?: string; n?: number };

export function SignatureLine({ s, className = "" }: { s?: Signature | null; className?: string }) {
  if (!s) return null;
  return (
    <details className={`mt-1 text-[11px] leading-snug text-brand-ink/65 [overflow-wrap:anywhere] ${className}`}>
      <summary className="cursor-pointer font-medium text-brand-plum/85 hover:underline">
        Техническая подпись расчёта (команда и версия)
      </summary>
      <p className="mt-1 rounded-lg bg-[#F7F6FC] p-2" data-testid="world-signature">
        Мир: {s.world ?? "—"} · seed{NB}{s.seed ?? "—"} · конфигурация <code>{s.config_hash ?? "—"}</code> · коммит <code>{s.commit ?? "—"}</code>{s.command ? <> · <code>{s.command}</code></> : null}
      </p>
    </details>
  );
}

const fmt = (v: number | null | undefined, f: string) => (f === "pct" ? pct(v) : f === "signed3" ? signed(v, 3) : num(v, 3));

function plainHeadlineText(s?: string | null): string {
  if (!s) return "";
  return s
    .replace(/\bBM25\b/g, "текстовый поиск по резюме")
    .replace(/\bnDCG@10\b/g, "качество порядка топ-10");
}

const TOP5_IDS = ["confident_accuracy", "false_confirm_all", "exact_grade", "within_one", "retest_kappa_w"];
const TOP5_TITLE: Record<string, string> = {
  confident_accuracy: "Точность уверенного решения",
  false_confirm_all: "Ложные подтверждения грейда",
  exact_grade: "Грейд совпал с истинным",
  within_one: "В пределах одной ступени",
  retest_kappa_w: "Совпадение при повторе",
};
const ru = (v?: number | null) => (v == null ? "—" : v.toLocaleString("ru-RU"));

/** Пять чисел одного снимка: NUMBERS.json → top5[] (стандартные условия S-T / S-M) и top5_hard[] (проверка на прочность в жёстких условиях).
 *  Выбор заголовка зафиксирован до прогонов и от результатов не зависит. Обе строки всегда рядом; пока ключей нет — «пересчитывается». */
function Top5Snapshot({ prov }: { prov?: any }) {
  const top5 = getTop5();
  const top5Hard = getTop5Hard();
  const meta = getTop5Meta() as any;
  const byId = new Map((top5 ?? []).map((x) => [x.id, x]));
  const hardById = new Map((top5Hard ?? []).map((x) => [x.id, x]));
  const how = meta?.how_obtained_ru ?? meta?.how_ru ?? meta?.source_ru;
  const nVal = meta?.n ?? meta?.n_candidates;
  const famVal = meta?.bank_families ?? NUMBERS.bank?.families;
  const stdCond = meta?.standard_condition_ru ?? "Стандартные условия, принятые в аналогичных решениях (единая шкала, сопоставимая с другими командами; точный грейд — среди тех, кому продукт определяет уровень)";
  const hardCond = meta?.hard_condition_ru ?? "Проверка на прочность в жёстких условиях: случайное угадывание, завышение заявок на грейд, пограничные кандидаты у порогов, погрешность параметров заданий и неточные резюме";
  return (
    <div className="mt-4" data-testid="validation-snapshot-5">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-[#F3F2FB] px-3.5 py-2.5 text-sm text-brand-night">
        {how || nVal ? (
          <p className="font-medium leading-relaxed" data-testid="snapshot-how">
            <b>Как получено:</b> {how ?? "симуляция / модель, не люди"}{nVal ? `, N${NB}=${NB}${ru(nVal)}` : ""}
            {famVal ? ` · единый снимок банка (${ru(famVal)}${NB}семейств)` : ""}.
          </p>
        ) : (
          <p className="font-medium leading-relaxed" data-testid="snapshot-how">
            <b>Как получено:</b> симуляция (модель, не люди) — 5 чисел одного снимка пересчитываются на текущем банке ({ru(famVal)}{NB}семейств).
          </p>
        )}
        {prov && <ProvenanceLine p={prov} />}
      </div>

      {/* Строка 1: Заголовок — стандартные условия */}
      <div className="mt-4 rounded-2xl border border-brand-night/10 bg-white p-4" data-testid="validation-top5-standard">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-base font-extrabold text-brand-night">
            Стандартные условия, принятые в аналогичных решениях
          </h3>
          <span className="rounded-full bg-[#F3F2FB] px-2.5 py-0.5 text-xs font-semibold text-brand-plum">
            Основной ряд для сопоставления решений
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-brand-ink/75" data-testid="top5-standard-cond">
          {stdCond}
        </p>
        <ol className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {TOP5_IDS.map((id, idx) => {
            const m = byId.get(id);
            return (
              <li key={id} className="card flex min-w-0 flex-col justify-between bg-[#FBF8FC] p-3.5" data-testid={`snapshot-card-${id}`}>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-lavender">{idx + 1}. {m?.label_ru ?? TOP5_TITLE[id]}</p>
                  {m?.display_ru ? (
                    <>
                      <p className="mt-1.5 text-2xl font-extrabold tabular-nums text-brand-night sm:text-3xl">{m.display_ru}</p>
                      {m.k != null && m.n != null && <p className="text-xs tabular-nums text-brand-ink/70" title="Доля и объём выборки">{ru(m.k)} из {ru(m.n)}</p>}
                      {m.minutes != null && <p className="text-xs tabular-nums text-brand-ink/65">в среднем {num(m.minutes, 1)}{NB}мин</p>}
                      {m.condition_ru && <p className="mt-1.5 text-xs leading-relaxed text-brand-ink/80">{plainHeadlineText(m.condition_ru)}</p>}
                    </>
                  ) : (
                    <p className="mt-2 text-base font-semibold text-brand-ink/70" data-testid={`snapshot-pending-${id}`}>пересчитывается</p>
                  )}
                </div>
                {(m?.ci95 || m?.recompute) && (
                  <details className="mt-2 border-t border-brand-night/10 pt-1.5 text-[11px] text-brand-ink/60">
                    <summary className="cursor-pointer font-medium text-brand-plum/80 hover:underline">Интервал и пересчёт</summary>
                    {m.ci95 && <p className="mt-1 tabular-nums">95{NB}% ДИ: {fmtPct(m.ci95[0], 1)} … {fmtPct(m.ci95[1], 1)}</p>}
                    {m.recompute && <p className="mt-1 break-all font-mono text-[10px]">{m.recompute}</p>}
                  </details>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {/* Строка 2: Сразу рядом тем же размером — проверка на прочность в жёстких условиях */}
      <div className="mt-3 rounded-2xl border border-brand-night/10 bg-white p-4" data-testid="validation-top5-hard">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-base font-extrabold text-brand-night">
            Проверка на прочность в жёстких условиях
          </h3>
          <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-900 ring-1 ring-amber-200">
            Проверка запаса прочности
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-brand-ink/75" data-testid="top5-hard-cond">
          {hardCond}
        </p>
        <ol className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {TOP5_IDS.map((id, idx) => {
            const m = hardById.get(id);
            return (
              <li key={id} className="card flex min-w-0 flex-col justify-between bg-[#F7F6FC] p-3.5" data-testid={`snapshot-hard-card-${id}`}>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-lavender">{idx + 1}. {m?.label_ru ?? TOP5_TITLE[id]}</p>
                  {m?.display_ru ? (
                    <>
                      <p className="mt-1.5 text-2xl font-extrabold tabular-nums text-brand-night sm:text-3xl">{m.display_ru}</p>
                      {m.k != null && m.n != null && <p className="text-xs tabular-nums text-brand-ink/70" title="По всем кандидатам выборки">{ru(m.k)} из {ru(m.n)}</p>}
                      {m.minutes != null && <p className="text-xs tabular-nums text-brand-ink/65">в среднем {num(m.minutes, 1)}{NB}мин</p>}
                      {m.condition_ru && <p className="mt-1.5 text-xs leading-relaxed text-brand-ink/80">{plainHeadlineText(m.condition_ru)}</p>}
                    </>
                  ) : (
                    <p className="mt-2 text-base font-semibold text-brand-ink/70" data-testid={`snapshot-hard-pending-${id}`}>пересчитывается</p>
                  )}
                </div>
                {(m?.ci95 || m?.recompute) && (
                  <details className="mt-2 border-t border-brand-night/10 pt-1.5 text-[11px] text-brand-ink/60">
                    <summary className="cursor-pointer font-medium text-brand-plum/80 hover:underline">Интервал и пересчёт</summary>
                    {m.ci95 && <p className="mt-1 tabular-nums">95{NB}% ДИ: {fmtPct(m.ci95[0], 1)} … {fmtPct(m.ci95[1], 1)}</p>}
                    {m.recompute && <p className="mt-1 break-all font-mono text-[10px]">{m.recompute}</p>}
                  </details>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {/* Объяснение разницы: одна фраза простыми словами + раскрывающийся блок */}
      <div className="mt-3 rounded-xl bg-[#F3F2FB] px-3.5 py-2.5 text-xs leading-relaxed text-brand-night" data-testid="top5-diff-explain">
        <p>
          <b>Почему показаны оба ряда сразу:</b> первый ряд измеряет точность на чистой стандартной выборке для прямого сравнения с аналогами, а второй ряд показывает, как те же алгоритмы держат удар, когда кандидаты завышают заявку, угадывают ответы и находятся ровно на границе двух грейдов.
        </p>
        <details className="mt-1.5 text-brand-ink/75">
          <summary className="cursor-pointer font-semibold text-brand-plum hover:underline">
            Подробно о протоколе двух режимов измерения
          </summary>
          <p className="mt-1">
            По решению владельца продукт публикует обе планки одновременно, и выбор заголовочного ряда зафиксирован в протоколах до запуска расчётов. В стандартных условиях точный грейд считается среди кандидатов, которым вынесен вердикт (с выводом доли по всему пулу в подсказке), а также рассчитываются совпадение в пределах ±1 ступени, повторяемость, доля прошедших завышений и метрики ранжирования (P@5, nDCG@10, MRR). В жёстких условиях добавлены шум параметров заданий, завышенные и заниженные самооценки и «раздутые» резюме.
          </p>
        </details>
      </div>
    </div>
  );
}

/** Отдельный блок реальных вакансий hh.ru: только числа из NUMBERS.json (hh_match), без чисел в тексте. */
function HhRealBlock() {
  const hh = getHhMatchMetrics() as any;
  const ho = hh?.holdout;
  const n = ho?.n ?? hh?.n;
  return (
    <div className="mt-4 rounded-2xl border border-emerald-600/25 bg-emerald-50/60 p-4 sm:p-5" data-testid="validation-hh-real-block">
      <p className="text-xs font-bold uppercase tracking-[0.08em] text-emerald-900">Люди, не модель · реальные вакансии</p>
      <h3 className="mt-1 text-lg font-extrabold text-brand-night">
        {n ? `${ru(n)} ${plural(n, "реальная вакансия", "реальные вакансии", "реальных вакансий")} hh.ru` : "Реальные вакансии hh.ru"}
      </h3>
      {n ? (
        <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/80">
          Как получено: тексты настоящих работодателей с hh.ru{ho ? " (отложенный набор, один прогон без подгонки)" : ""}, N{NB}={NB}{ru(n)}.
          {(ho?.direction_ok ?? hh?.overall?.direction_ok)?.share != null && <> Направление определено верно — <b>{fmtPct((ho?.direction_ok ?? hh.overall.direction_ok).share, 1)}</b>.</>}
          {(ho?.grade_ok ?? hh?.overall?.grade_ok)?.share != null && <> Грейд разобран верно — <b>{fmtPct((ho?.grade_ok ?? hh.overall.grade_ok).share, 1)}</b>.</>}
          {" "}<a href="#hh-match" className="font-semibold text-brand-plum underline">Подробнее</a>
        </p>
      ) : (
        <p className="mt-2 text-sm text-brand-ink/75">Числа пересчитываются и появятся из единого снимка.</p>
      )}
    </div>
  );
}

export default function Headline() {
  const { data, error, loading } = useApi<any>("/validation/headline", []);
  if (loading) return <div className="mt-8"><Loading /></div>;
  if (error) return <div className="mt-8"><Alert>{error}</Alert></div>;
  return (
    <section id="headline" className="mt-8 scroll-mt-20" aria-labelledby="headline-t" data-testid="validation-headline">
      <h2 id="headline-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">5 чисел одного снимка</h2>
      <Top5Snapshot prov={data?.items?.[0]?.provenance} />
      <HhRealBlock />
      {data && !data.missing && <>
      {/* Детальные карточки 5 метрик механики (для совместимости e2e и глубокой сверки) */}
      <details className="mt-4 rounded-2xl bg-white p-4 ring-1 ring-brand-night/10">
        <summary className="cursor-pointer text-sm font-bold text-brand-night">
          Технические подробности: расчёты механики с интервалами и происхождением
        </summary>
        <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/70">{plainHeadlineText(data.how_to_read)}</p>
        <ol className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {data.items.map((it: any, i: number) => (
            <li key={it.id} className="card flex min-w-0 flex-col" data-testid={`headline-${it.id}`}>
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{i + 1}. {plainHeadlineText(it.title)}</p>
              <p className="mt-2 text-3xl font-extrabold tabular-nums text-brand-night">{fmt(it.value, it.format)}</p>
              {it.ci && <p className="text-xs tabular-nums text-brand-ink/70">95{NB}% ДИ: {fmt(it.ci[0], it.format)} … {fmt(it.ci[1], it.format)}</p>}
              {it.pair && <p className="text-xs tabular-nums text-brand-ink/70">Качество топ-10: {num(it.pair[0], 3)} против {num(it.pair[1], 3)}</p>}
              <p className="mt-2 text-sm leading-snug text-brand-ink/80">{plainHeadlineText(it.text)}</p>
              {it.note && <p className="mt-1 text-xs text-brand-ink/65">{plainHeadlineText(it.note)}</p>}
              {it.protocol_note && (
                <details className="mt-1 text-xs text-brand-ink/65">
                  <summary className="cursor-pointer font-medium text-brand-plum/80 hover:underline">Сравнение протоколов расчёта</summary>
                  <p className="mt-1" data-testid="headline-protocol-note">{plainHeadlineText(it.protocol_note)}</p>
                </details>
              )}
              <div className="mt-auto pt-3">
                <a href={`#${it.anchor}`} className="text-sm font-semibold text-brand-plum underline">Подробнее в разделе</a>
                <ProvenanceLine p={it.provenance} className="mt-1.5" />
                <SignatureLine s={it.signature} className="mt-1" />
              </div>
            </li>
          ))}
        </ol>
      </details>

      <AccuracyViews v={data.accuracy} className="mt-3" />
      <RetestVsTruth v={data.retest_vs_truth} className="mt-3" />
      <Protocols v={data.protocols} className="mt-3" />
      </>}
    </section>
  );
}

/** Д5: сверка двух протоколов с одним порогом P — перебор правил (make grade-sweep: числа docs/NUMBERS.json и слайдов)
 *  и контрольный прогон всего пути с настройками продукта (make path-retest: числа карточек выше). */
export function Protocols({ v, className = "" }: { v?: any; className?: string }) {
  if (!v) return null;
  const rows: [string, any][] = [
    ["Перебор правил (выбор порога)", v.sweep],
    ["Полный путь кандидата (карточки)", v.path],
  ];
  return (
    <details className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-protocols">
      <summary className="cursor-pointer text-sm font-semibold leading-snug text-brand-night">
        Техническая сверка протоколов симуляции (перебор правил и полный путь при одном пороге уверенности)
      </summary>
      <ScrollX label="Сверка протоколов" className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <caption className="sr-only">Перебор правил и повтор всего пути при одном пороге уверенности</caption>
          <thead className="text-xs text-brand-ink/70">
            <tr>{["Протокол", "Точно", "Выше истинного", "Повтор: совпало", "Согласие повтора", "Снимок банка"].map((h) => <th key={h} scope="col" className="px-2 py-1 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(([k, x]) => (
              <tr key={k} className="border-t border-brand-night/5 tabular-nums">
                <th scope="row" className="px-2 py-1 font-medium text-brand-night">{k}</th>
                <td className="px-2 py-1">{pct(x?.exact, 1)}</td><td className="px-2 py-1">{pct(x?.over, 1)}</td>
                <td className="px-2 py-1">{pct(x?.retest_exact, 1)}</td><td className="px-2 py-1">{num(x?.retest_kappa, 3)}</td>
                <td className="px-2 py-1">{NUMBERS.bank.families.toLocaleString("ru-RU")} семейств</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/75">{plainHeadlineText(v.text)}</p>
    </details>
  );
}

/** W1: точность грейда — три прозрачных числа первыми (make accuracy-views): вдали от порога, без занижения заявки,
 *  строго по всему пулу (+ повтор). У каждого — кто входит и доля пула. */
export function AccuracyViews({ v, className = "" }: { v?: any; className?: string }) {
  if (!v?.items?.length) return null;
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-accuracy">
      <p className="text-sm font-semibold leading-snug text-brand-night">Точность грейда в разных разрезах выборки: у каждого числа — кто входит</p>
      <ol className="mt-3 grid gap-3 md:grid-cols-3">
        {v.items.map((it: any, i: number) => (
          <li key={it.id} className="min-w-0 rounded-xl bg-[#F7F6FC] p-3" data-testid={`accuracy-${it.id}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{"абв"[i]}) {plainHeadlineText(it.title)}</p>
            <p className="mt-1 text-2xl font-extrabold tabular-nums text-brand-night">{pct(it.value, 1)}</p>
            {it.ci && <p className="text-xs tabular-nums text-brand-ink/70">95{NB}% ДИ: {pct(it.ci[0], 1)} … {pct(it.ci[1], 1)}</p>}
            <p className="mt-1 text-xs text-brand-ink/70">Кто входит: {plainHeadlineText(it.who)} · доля пула {pct(it.share, 1)}</p>
            <p className="mt-1.5 text-sm leading-snug text-brand-ink/80">{plainHeadlineText(it.text)}</p>
          </li>
        ))}
      </ol>
      <details className="mt-2 text-xs leading-relaxed text-brand-ink/70">
        <summary className="cursor-pointer font-medium text-brand-plum/85 hover:underline">
          Методика расчёта разрезов и команда воспроизведения
        </summary>
        <p className="mt-1">{plainHeadlineText(v.note)} Пересчёт: <code>{v.command}</code>.</p>
        <ProvenanceLine p={v.provenance} className="mt-1.5" />
        <SignatureLine s={v.signature} className="mt-1" />
      </details>
    </div>
  );
}
