import { Alert, Loading, useApi } from "../ui";
import { ScrollX } from "../A11y";
import { useMeta } from "../../lib/meta";

/** Блок /validation (Я12): разбор потребности на корпусе реальных вакансий hh.ru — полнота полей, совпадение с
 * полями hh.ru, навыки, отрицания (backend: tools/realdata/hh_corpus.py → validation/data/hh_parse.json).
 * Показывается при включённой интеграции hh.ru (HH_ENABLED). */

const pct = (v?: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1).replace(".", ",")}\u00A0%`);
const d10 = (v?: string | null) => (v ? new Date(v).toLocaleDateString("ru-RU") : "—");
const FIELD: Record<string, string> = {
  direction: "Направление", grade: "Грейд", experience_years_min: "Опыт, лет", work_format: "Формат работы", stack: "Стек (≥ 1 навык)", salary: "Зарплата в тексте",
};

export default function HhParse() {
  const on = useMeta()?.hh?.enabled ?? false;
  const { data: r, error, loading } = useApi<any>(on ? "/validation/hh-parse" : null, [on]);
  if (!on) return null;
  return (
    <section id="hh-parse" className="mt-12 scroll-mt-20" aria-labelledby="hh-parse-t">
      <h2 id="hh-parse-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Разбор потребности на вакансиях hh.ru</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Замер ещё не посчитан: tools/realdata/hh_corpus.py run.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const p = r.parser ?? {}, a = p.accuracy ?? {}, sk = p.skills ?? {}, ng = p.negations ?? {};
  const q = r.compare?.parser, rev = r.compare?.rev;
  const rows: [string, string, string?][] = [
    ["Направление (роль hh.ru)", `${a.direction?.correct} из ${a.direction?.n} — ${pct(a.direction?.share)}`, q && pct(q.accuracy?.direction?.share)],
    ["Грейд (слово в названии)", `${a.grade?.correct} из ${a.grade?.n} — ${pct(a.grade?.share)}`, q && pct(q.accuracy?.grade?.share)],
    ["Опыт внутри поля «опыт» hh.ru", `${a.experience?.consistent} из ${a.experience?.found} найденных — ${pct(a.experience?.share_of_found)}`, q && pct(q.accuracy?.experience?.share_of_found)],
    ["Формат внутри поля «формат» hh.ru", `${a.work_format?.consistent} из ${a.work_format?.found} найденных — ${pct(a.work_format?.share_of_found)}`, q && pct(q.accuracy?.work_format?.share_of_found)],
    ["«Опыт не требуется» → не требует опыта", `${ng.neg_exp?.correct} из ${ng.neg_exp?.n} — ${pct(ng.neg_exp?.share)}`, q && pct(q.negations?.neg_exp?.share)],
    ["«Нет опыта» в hh.ru → не требует опыта", `${ng.noexp_field?.correct} из ${ng.noexp_field?.n} — ${pct(ng.noexp_field?.share)}`, q && pct(q.negations?.noexp_field?.share)],
    ["«Удалёнка не предусмотрена», «только офис» → не «удалённо»", `${ng.neg_remote?.correct} из ${ng.neg_remote?.n} — ${pct(ng.neg_remote?.share)}`, q && pct(q.negations?.neg_remote?.share)],
    ["Только «на месте» в hh.ru → не «удалённо»", `${ng.onsite_only?.correct} из ${ng.onsite_only?.n} — ${pct(ng.onsite_only?.share)}`, q && pct(q.negations?.onsite_only?.share)],
    ["Ключевые навыки hh.ru найдены в тексте", `${sk.key_skills_found} из ${sk.key_skills_total} — ${pct(sk.key_skills_recall)}`, q && pct(q.skills?.key_skills_recall)],
  ];
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        {r.n} реальных ИТ-вакансий hh.ru (корпус от {d10(r.corpus_collected_at)}: 5 направлений × 4 грейда и выборки с отрицаниями). Разбор — правилами, как у потребности, только по названию и описанию; метки — из полей, которые работодатель заполнил на hh.ru (роль, опыт, формат, ключевые навыки), а не из того же текста. Корпус — только для проверки разбора: в репозитории номера, ссылки и метки, без текстов вакансий.
      </p>
      <p className="mt-1 text-xs text-brand-ink/65" data-testid="hh-parse-signature">Прогон {d10(r.generated_at)} · код {r.code_commit} · недоступно с даты сбора: {r.n_missing ?? 0} · текст изменился: {r.text_changed_since_collect ?? 0} · метки серебряные (поля hh.ru, не эксперты)</p>
      <div className="mt-4">
        <ScrollX label="Разбор на вакансиях hh.ru" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
              <tr><th scope="col" className="px-3 py-2.5 font-semibold">Проверка</th><th scope="col" className="px-3 py-2.5 font-semibold">Текущий разбор</th>{q && <th scope="col" className="px-3 py-2.5 font-semibold">Ветка {rev}</th>}</tr>
            </thead>
            <tbody>
              {rows.map(([t, v, w]) => <tr key={t} className="border-t border-brand-night/5"><td className="px-3 py-2 font-medium text-brand-night">{t}</td><td className="px-3 py-2 tabular-nums text-brand-ink/80">{v}</td>{q && <td className="px-3 py-2 tabular-nums text-brand-ink/80">{w}</td>}</tr>)}
            </tbody>
          </table>
        </ScrollX>
      </div>
      <p className="mt-3 text-sm text-brand-ink/70">Полнота полей (что разбор нашёл в тексте): {Object.entries<number>(p.completeness ?? {}).map(([k, v]) => `${FIELD[k] ?? k} ${pct(v)}`).join(" · ")}.</p>
      {r.import?.n ? <p className="mt-1 text-sm text-brand-ink/70">Черновик импорта (текст + поля hh.ru): категория {pct(r.import.category)}, вилка из hh.ru {pct(r.import.salary_from_hh)} (ещё {pct(r.import.salary_partial)} — частично: только «от» или «до», либо шире 1,5; с пометкой «уточните»), формат {pct(r.import.work_format)}, город {pct(r.import.city)}, стек {pct(r.import.stack)}.</p> : null}
      <p className="mt-2 text-xs text-brand-ink/65">«Опыт» и «формат» — доля среди вакансий, где разбор нашёл значение: значение внутри поля hh.ru («3–6 лет» → 3…6). Отрицания: «верно» — разбор не требует опыта (0 или не указан) и не пишет «удалённо». Подробно и расхождения — docs/validation/HH_PARSE.md.</p>
    </>
  );
}
