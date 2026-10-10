import type { ReactNode } from "react";
import { DIRECTIONS } from "../ui";
import { ScrollX } from "../A11y";

/* Блок /validation «Порог грейда Стажёр»: симуляция теста при четырёх порогах-кандидатах на текущем банке и на банке
   с лёгкими семействами. Данные — intern_cut из /api/validation/report (make intern-cut). Без подгонки: правило выбора
   задано заранее, цифры — как получились. */

const pct = (v?: number | null, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d).replace(".", ",")}\u00A0%`);
const num = (v?: number | null, d = 2) => (v == null ? "—" : v.toFixed(d).replace(".", ","));
const theta = (v?: number | null) => (v == null ? "—" : `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(2).replace(".", ",").replace(/,?0+$/, "")}`);

function Table({ head, rows, mark }: { head: string[]; rows: ReactNode[][]; mark?: number }) {
  return (
    <ScrollX label="Таблица" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`border-t border-brand-night/5 ${i === mark ? "bg-brand-blush/15 font-semibold" : ""}`}>
              {r.map((c, j) => <td key={j} className={`px-3 py-2 tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollX>
  );
}

export function InternCutSection({ ic }: { ic: any }) {
  if (!ic || ic.missing) return null;
  const cuts: any[] = ic.by_cut ?? [];
  const easy: any[] = ic.with_easy_families?.by_cut ?? [];
  const rule = ic.rule ?? {};
  const chosen = ic.chosen?.cut;
  const row = (s: any) => [theta(s.cut), pct(s.false_confirm, 1), pct(s.false_reject, 1), pct(s.band_confirm), pct(s.band_upgrade, 1),
    num(s.mean_items, 1), num(s.mean_se), pct(s.exhausted_share), pct(s.pop_share_band, 1)];
  // Я8: на банке 165 правило выполняется и на текущем банке — подписи из JSON расчёта, а не прежним текстом
  const cur = ic.current_bank_rule ?? {};
  const curOk = !!cur.all_pass;
  const curRow = cuts.find((s) => s.cut === cur.cut) ?? {};
  const idx = cuts.findIndex((s) => s.cut === (curOk ? cur.cut : chosen));
  const basisNow = ic.chosen?.basis === "current_bank";  // с 10.10 порог выбирается по текущему банку
  const easyRule = ic.with_easy_families?.rule ?? {};
  const idxE = easy.findIndex((s) => s.cut === chosen);
  const dirs = Object.keys(ic.retest ?? {});
  const poolNow = ic.pool_now ?? {};
  const easyPool = ic.with_easy_families?.pool ?? {};
  return (
    <section id="intern" className="mt-12 scroll-mt-20" aria-labelledby="intern-t">
      <h2 id="intern-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Порог грейда «Стажёр»</h2>
      <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Стажёр — грейд ниже Junior для начинающих. Его порог на шкале θ выбран симуляцией теста платформы при четырёх порогах-кандидатах:
        кандидаты с истинным θ от −3 до −0,5 (по {ic.n_per_theta} на точку сетки, направление и порог), заявлен Стажёр, остановка у порогов и
        дотестирование как в продукте. Правило задано заранее: самый низкий порог, при котором ложные подтверждения (θ ниже порога на 0,25 и более)
        не выше {pct(rule.max_false_confirm)}, ложные отказы (θ выше порога на 0,25 и более) не выше {pct(rule.max_false_reject)} и не больше {pct(rule.max_exhausted)} сессий
        упираются в исчерпание заданий. В продукте действует порог <b>θ = {theta(ic.cut_in_use)}</b>.
      </p>
      <h3 className="mt-6 text-base font-bold text-brand-night">{curOk ? `Текущий банк: правилу удовлетворяет порог ${(cur.passing ?? []).map(theta).join(", ")}` : "Текущий банк: лёгких семейств для Стажёра ещё нет, тест идёт по самым простым заданиям Junior"}</h3>
      <div className="mt-3">
        <Table head={["Порог", "Ложное подтверждение", "Ложный отказ", "Подтверждение в полосе Стажёра", "Предложен Junior в полосе", "Заданий", "SE", "Исчерпание пула", "Доля полосы, θ ~ N(0; 1)"]}
          rows={cuts.map(row)} mark={idx} />
      </div>
      <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        {curOk ? <>На текущем банке правило выполнено при пороге {theta(cur.cut)}{cur.cut === ic.cut_in_use ? " — он и действует в продукте" : ""}: ложные подтверждения {pct(curRow.false_confirm, 1)},
        ложные отказы {pct(curRow.false_reject, 1)} (предел {pct(rule.max_false_reject)} — запаса почти нет), исчерпание пула {pct(curRow.exhausted_share)}. Лёгкие семейства для Стажёра
        в банке появились, но их немного: SE не опускается ниже ≈ {num(Math.min(...cuts.map((s) => s.mean_se ?? 1)))}, поэтому решение по Стажёру грубее, чем по другим грейдам. Порог выбирается по текущему банку, без добавленных синтетических семейств.</> : <>
        Ни один порог правилу на текущем банке не удовлетворяет: у самых простых семейств Junior трудность b не ниже −0,9, при θ ≈ −2 они дают мало
        информации, SE не опускается ниже ≈ {num(Math.min(...cuts.map((s) => s.mean_se ?? 1)))}, и почти каждая сессия доходит до максимума заданий. Поэтому решение
        по Стажёру на текущем банке грубее, чем по другим грейдам, а порог выбран по банку с лёгкими семействами ниже.</>}
      </p>
      {easy.length > 0 && (
        <>
          <h3 className="mt-6 text-base font-bold text-brand-night">Банк с лёгкими семействами: {ic.with_easy_families.per_block} синтетических семейств на блок, b от −2,5 до −1,5</h3>
          <div className="mt-3">
            <Table head={["Порог", "Ложное подтверждение", "Ложный отказ", "Подтверждение в полосе Стажёра", "Предложен Junior в полосе", "Заданий", "SE", "Исчерпание пула", "Доля полосы, θ ~ N(0; 1)"]}
              rows={easy.map(row)} mark={basisNow ? -1 : idxE} />
          </div>
          <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
            {basisNow ? <>Справочно: с синтетическими лёгкими семействами правилу удовлетворяли бы пороги {(easyRule.passing ?? []).map(theta).join(", ") || "—"}
            {easyRule.cut != null && <>, самый низкий — {theta(easyRule.cut)}</>}. На выбор это не влияет: порог выбирается по текущему банку, без добавленных семейств.
            Такие семейства (закрытые форматы, 90–180 с, трудность b ≈ −2) запрошены у банка заданий; появятся — попадут в тест Стажёра автоматически,
            и пересчёт покажет, можно ли опустить порог.</> : curOk && chosen !== ic.cut_in_use ? <>С синтетическими лёгкими семействами правилу удовлетворяют пороги {ic.chosen?.passing?.map(theta).join(", ")}; самый низкий — {theta(chosen)} —
            станет кандидатом, когда такие семейства появятся в банке (решение — после пересчёта). До этого действует {theta(ic.cut_in_use)}: он выполняет правило на текущем банке.</> : <>
            Правилу удовлетворяет {ic.chosen?.passing?.length === 1 ? "только порог" : "порог"} {ic.chosen?.passing?.map(theta).join(", ")}: он и выбран.
            Такие семейства (закрытые форматы, 90–180 с, трудность b ≈ −2) запрошены у банка заданий; появятся — попадут в тест Стажёра автоматически.</>}
          </p>
        </>
      )}
      <h3 className="mt-6 text-base font-bold text-brand-night">Повтор и запас информации пула у порога {theta(chosen)}{curOk && chosen !== ic.cut_in_use ? " (выбран по банку с лёгкими семействами)" : ""}</h3>
      <div className="mt-3">
        <Table head={["Направление", "Семейств в тесте (текущий банк)", "Информация у порога", "Минимальная SE", "С лёгкими семействами: семейств / SE", "Согласие решения при повторе", "r(θ) повтора"]}
          rows={dirs.map((d) => {
            const p = poolNow[d] ?? {};
            // Я8: ключи JSON — «-2.0», а String(-2) — «-2»: ищем по обоим написаниям
            const ck = (o: any) => o?.[String(chosen)] ?? o?.[Number(chosen).toFixed(1)] ?? o?.[Number(chosen).toFixed(2)] ?? {};
            const pn = ck(ic.pool?.[d]);
            const pe = ck(easyPool[d]);
            const rt = ic.retest?.[d] ?? {};
            return [DIRECTIONS[d] ?? d, `${(p.n_common ?? 0) + (p.n_direction ?? 0)} (общих ${p.n_common ?? 0})`, num(pn.info_at_cut, 1), num(pn.min_se),
              `${pe.n_families ?? "—"} / ${num(pe.min_se)}`, pct(rt.decision_agreement), num(rt.r_theta)];
          })} />
      </div>
      <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Согласие решения при повторе ({dirs.length ? `${pct(Math.min(...dirs.map((d) => ic.retest[d].decision_agreement)))}–${pct(Math.max(...dirs.map((d) => ic.retest[d].decision_agreement)))}` : "—"})
        ниже, чем у остальных грейдов: это следствие того же недостатка лёгких заданий. Правило подтверждения у Стажёра то же, что у остальных грейдов:
        P(θ ≥ порога) ≥ {pct(ic.config?.confirm_level)}; при P(θ ≥ порога Junior) ≥ {pct(ic.config?.upgrade_level)} предлагается тест на Junior.
        Пересчёт: <code className="rounded bg-white px-1.5 py-0.5 text-sm">make intern-cut</code>.
      </p>
    </section>
  );
}
