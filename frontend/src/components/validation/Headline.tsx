import { NB, num, pct } from "../ui";
import { ProvenanceLine } from "./Provenance";
import { ScrollX } from "../A11y";
import { fmtNum, getGradeVerdict, type Frac } from "../../lib/numbers";

/** Первый экран /validation: точность решения по грейду — симуляция продукта (docs/NUMBERS.json → grade_verdict).
 *  Каждое число — из расчёта с подписью мира; нет расчёта — нет числа. */

export type Signature = { world?: string; seed?: number; config_hash?: string; commit?: string; command?: string; generated_at?: string; n?: number };

export function SignatureLine({ s, className = "" }: { s?: Signature | null; className?: string }) {
  if (!s) return null;
  return (
    <p className={`text-[11px] leading-snug text-brand-ink/65 [overflow-wrap:anywhere] ${className}`} data-testid="world-signature">
      Мир: {s.world ?? "—"} · seed{NB}{s.seed ?? "—"} · конфигурация <code>{s.config_hash ?? "—"}</code> · коммит <code>{s.commit ?? "—"}</code>{s.command ? <> · <code>{s.command}</code></> : null}
    </p>
  );
}

const pc = (v: number | null | undefined) => (v == null || Number.isNaN(Number(v)) ? "—" : (Number(v) * 100).toFixed(1).replace(".", ","));
const nint = (v: number | null | undefined) => (v == null ? "—" : Math.round(Number(v)).toLocaleString("ru-RU"));

const GRADE_TITLE: Record<string, string> = {
  intern: "Intern", junior: "Junior", middle: "Middle", senior: "Senior", lead: "Lead", principal: "Principal",
};

function ci(f?: Frac | null) {
  return f?.ci95 ? `95 % ДИ ${pc(f.ci95[0])}–${pc(f.ci95[1])}` : "";
}

function Big({ label, f, sub, testid }: { label: string; f?: Frac | null; sub: string; testid: string }) {
  return (
    <div className="rounded-xl bg-brand-cream/40 p-4 ring-1 ring-brand-night/10" data-testid={testid}>
      <div className="text-[11px] font-bold uppercase tracking-wide text-brand-ink/70">{label}</div>
      <div className="mt-1 text-2xl font-extrabold text-brand-night">{f ? `${pc(f.value)} %` : "—"}</div>
      <div className="mt-1 text-xs text-brand-ink/70">{sub}</div>
      {f && <div className="mt-1 text-[11px] text-brand-ink/70">{[f.k != null && f.n != null ? `${f.k} из ${f.n}` : "", ci(f)].filter(Boolean).join(" · ")}</div>}
    </div>
  );
}

/** Главный блок /validation: точность решения по заявленному грейду — симуляция ПРОДУКТА (А4, 21.10).
 * Только docs/NUMBERS.json → grade_verdict (артефакт product_sim_test_*.json), никаких чисел в коде. */
export default function Headline() {
  const gv = getGradeVerdict();
  if (!gv) {
    return (
      <section id="headline" className="mt-8 rounded-2xl bg-white p-5 ring-1 ring-brand-night/10" data-testid="v-headline">
        <h2 className="text-lg font-extrabold text-brand-night">Точность решения по грейду</h2>
        <p className="mt-2 text-sm text-brand-ink/70">Отчётный прогон симуляции продукта ещё не опубликован.</p>
      </section>
    );
  }
  const m = gv.main;
  const mm = m.minutes_main, mt = m.minutes_total;
  const rows = Object.entries(m.by_claim || {});
  return (
    <section id="headline" className="mt-8 rounded-2xl bg-white p-5 ring-1 ring-brand-night/10" data-testid="v-headline">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-extrabold text-brand-night">Точность решения по грейду: симуляция продукта</h2>
        <span className="chip-lime" title="Модельные кандидаты с известным истинным уровнем, не люди">модельные кандидаты, не люди</span>
      </div>
      <p className="mt-2 text-sm text-brand-ink/70">
        Тот же движок, что у кандидата: выбор заданий у порога грейда, остановка, дотестирование, вердикт и второй этап у
        границы — на реальном банке из {nint(m.bank_families ?? 0)} семейств. Кандидатов {nint(m.n)}: у каждого известен
        истинный уровень, треть завышает заявку на ступень. Настройки подбирались на одних зёрнах, цифры — на других,
        отложенных. Людей в этом расчёте нет: пилот с людьми ещё впереди.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Big testid="v-hl-verdict" label="Верный вердикт по заявке" f={m.verdict_accuracy}
          sub="итог «подтверждён / не подтверждён» совпал с истиной (после второго этапа, если он нужен)" />
        <Big testid="v-hl-false-confirm" label="Ложное подтверждение" f={m.false_confirm}
          sub="у тех, кто завысил заявку: тест подтвердил уровень, которого нет" />
        <Big testid="v-hl-confident" label="Решено после основной части" f={m.confident_share}
          sub={`уверенных решений; из них верных — ${m.confident_accuracy ? pc(m.confident_accuracy.value) : "—"} %. Остальным — короткий второй этап у порога`} />
        <Big testid="v-hl-exact" label="Точный грейд" f={m.exact_grade}
          sub={`присвоенный уровень равен истинному; ошибок на 2+ ступени — ${m.gross_error ? pc(m.gross_error.value) : "—"} %`} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-brand-cream/40 p-3 text-xs text-brand-ink/75 ring-1 ring-brand-night/10" data-testid="v-hl-time">
          <b className="text-brand-night">Время.</b> Основная часть — в среднем {mm ? fmtNum(mm.mean, 0) : "—"} мин (у 90 % — до{" "}
          {mm ? fmtNum(mm.p90, 0) : "—"}), вместе со вторым этапом — {mt ? fmtNum(mt.mean, 0) : "—"} мин; лимит основной части — 60 мин.
          {m.items_main ? ` Заданий — в среднем ${fmtNum(m.items_main.mean, 1)}.` : ""}
        </div>
        <div className="rounded-xl bg-brand-cream/40 p-3 text-xs text-brand-ink/75 ring-1 ring-brand-night/10" data-testid="v-hl-practice">
          <b className="text-brand-night">Практика.</b> Код и развёрнутые ответы с автопроверкой — в среднем{" "}
          {m.code_open_share ? pc(m.code_open_share.mean) : "—"} % заданий попытки
          {m.code_open_share ? ` (не меньше трети — в ${pc(m.code_open_share.share_sessions_ge_one_third)} % попыток)` : ""}.
        </div>
        <div className="rounded-xl bg-brand-cream/40 p-3 text-xs text-brand-ink/75 ring-1 ring-brand-night/10" data-testid="v-hl-retest">
          <b className="text-brand-night">Повторяемость.</b>{" "}
          {m.retest
            ? `Две независимые попытки одного кандидата (без общих семейств заданий): тот же грейд — ${m.retest.exact_agreement ? pc(m.retest.exact_agreement.value) : "—"} %, тот же вердикт — ${m.retest.verdict_agreement ? pc(m.retest.verdict_agreement.value) : "—"} %, взвешенная каппа ${m.retest.kappa_w != null ? fmtNum(m.retest.kappa_w, 2) : "—"} (пар: ${nint(m.retest.n_pairs)}).`
            : "Расчёт ещё не опубликован."}
        </div>
      </div>
      {gv.misspec && (
        <p className="mt-3 text-xs text-brand-ink/70" data-testid="v-hl-misspec">
          <b className="text-brand-night">Если банк ещё не откалиброван на людях</b> (трудность семейств ошибается в среднем на
          полступени, различающая сила — на четверть; движок об этом не знает): верный вердикт —{" "}
          {gv.misspec.verdict_accuracy ? pc(gv.misspec.verdict_accuracy.value) : "—"} %, ложное подтверждение —{" "}
          {gv.misspec.false_confirm ? pc(gv.misspec.false_confirm.value) : "—"} %, точный грейд —{" "}
          {gv.misspec.exact_grade ? pc(gv.misspec.exact_grade.value) : "—"} %. Поэтому первые 300 попыток людей идут на
          калибровку банка.
        </p>
      )}
      {rows.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-semibold text-brand-night">По заявленному грейду</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs" data-testid="v-hl-by-claim">
              <thead><tr className="text-left text-brand-ink/70"><th className="py-1 pr-3">Заявка</th><th className="pr-3">Кандидатов</th><th className="pr-3">Верный вердикт</th><th className="pr-3">Ложное подтверждение</th><th className="pr-3">Решено сразу</th><th className="pr-3">Точный грейд</th><th>Минут всего</th></tr></thead>
              <tbody>
                {rows.map(([g, r]) => (
                  <tr key={g} className="border-t border-black/5 ">
                    <td className="py-1 pr-3 font-semibold text-brand-night">{GRADE_TITLE[g] || g}</td>
                    <td className="pr-3">{nint(r.n)}</td>
                    <td className="pr-3">{r.verdict_accuracy ? `${pc(r.verdict_accuracy.value)} %` : "—"}</td>
                    <td className="pr-3">{r.false_confirm_among_overclaim?.n ? `${pc(r.false_confirm_among_overclaim.value)} % (${r.false_confirm_among_overclaim.k}/${r.false_confirm_among_overclaim.n})` : "—"}</td>
                    <td className="pr-3">{r.confident_share_main ? `${pc(r.confident_share_main.value)} %` : "—"}</td>
                    <td className="pr-3">{r.exact_grade_final ? `${pc(r.exact_grade_final.value)} %` : "—"}</td>
                    <td>{r.minutes_total ? fmtNum(r.minutes_total.mean, 0) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <details className="mt-3 text-xs text-brand-ink/70">
        <summary className="cursor-pointer font-semibold text-brand-night">Как посчитано и как пересчитать</summary>
        <p className="mt-2">{gv.what} Зёрна отчёта: {(m.seeds || []).join(", ")}; дата {m.date}. Протокол выбора настроек
          зафиксирован до прогонов: <code>{gv.protocol}</code>.</p>
        <p className="mt-1">Пересчёт: <code className="break-all">{gv.recompute}</code></p>
        <p className="mt-1">Код: <code>{gv.code_ref}</code>.</p>
      </details>
    </section>
  );
}

export function Protocols({ v, className = "" }: { v?: any; className?: string }) {
  if (!v) return null;
  const rows: [string, any][] = [[`Перебор правил, P${NB}≥${NB}${v.sweep?.confirm_level} (make grade-sweep)`, v.sweep], [`Весь путь, P${NB}≥${NB}${v.path?.confirm_level} (make path-retest, карточки)`, v.path]];
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-protocols">
      <p className="text-sm font-semibold leading-snug text-brand-night">Два протокола, один порог</p>
      <ScrollX label="Сверка протоколов" className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <caption className="sr-only">Перебор правил и повтор всего пути при одном пороге уверенности</caption>
          <thead className="text-xs text-brand-ink/70">
            <tr>{["Протокол", "Точно", "Выше истинного", "Повтор: совпало", "κw повтора", "Банк"].map((h) => <th key={h} scope="col" className="px-2 py-1 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(([k, x]) => (
              <tr key={k} className="border-t border-brand-night/5 tabular-nums">
                <th scope="row" className="px-2 py-1 font-medium text-brand-night">{k}</th>
                <td className="px-2 py-1">{pct(x?.exact, 1)}</td><td className="px-2 py-1">{pct(x?.over, 1)}</td>
                <td className="px-2 py-1">{pct(x?.retest_exact, 1)}</td><td className="px-2 py-1">{num(x?.retest_kappa, 3)}</td>
                <td className="px-2 py-1"><code>{String(x?.bank ?? "—").slice(0, 8)}</code>{x?.bank_families ? ` · ${x.bank_families} семейств` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/75">{v.text}</p>
    </div>
  );
}

/** W1: точность грейда — три прозрачных числа первыми (make accuracy-views): вдали от порога, без занижения заявки,
 *  строго по всему пулу (+ повтор). У каждого — кто входит и доля пула. */
export function AccuracyViews({ v, className = "" }: { v?: any; className?: string }) {
  if (!v?.items?.length) return null;
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-accuracy">
      <p className="text-sm font-semibold leading-snug text-brand-night">Точность грейда: три числа, у каждого — кто входит</p>
      <ol className="mt-3 grid gap-3 md:grid-cols-3">
        {v.items.map((it: any, i: number) => (
          <li key={it.id} className="min-w-0 rounded-xl bg-[#F7F6FC] p-3" data-testid={`accuracy-${it.id}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{"абв"[i]}) {it.title}</p>
            <p className="mt-1 text-2xl font-extrabold tabular-nums text-brand-night">{pct(it.value, 1)}</p>
            {it.ci && <p className="text-xs tabular-nums text-brand-ink/70">95{NB}% ДИ: {pct(it.ci[0], 1)} … {pct(it.ci[1], 1)}</p>}
            <p className="mt-1 text-xs text-brand-ink/70">Кто входит: {it.who} · доля пула {pct(it.share, 1)}</p>
            <p className="mt-1.5 text-sm leading-snug text-brand-ink/80">{it.text}</p>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/70">{v.note} Пересчёт: <code>{v.command}</code>.</p>
      <ProvenanceLine p={v.provenance} className="mt-1.5" />
      <SignatureLine s={v.signature} className="mt-1" />
    </div>
  );
}
