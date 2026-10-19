import { Link } from "react-router-dom";
import { JuryPanel } from "../../components/JuryPanel";
import { ShieldIcon, SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { usePageTitle } from "../../lib/meta";

/** W2: «Экспертиза ФСП» (/expertise) — единый хаб для экспертов жюри. Сюда перенесено всё конкурсное с главной:
 *  «Проверка за 12 минут» (проводник, сценарии, роли, сброс демо, живой ИИ-интервьюер) и быстрые переходы к
 *  критериям ТЗ, протоколам валидации, «Красной кнопке» и проверке на своём наборе данных. Вкладка в шапке —
 *  флаг VITE_JURY_TAB (по умолчанию включена); адрес работает всегда. */
const LINKS: { to: string; n: string; title: string; text: string; cta: string; testid: string }[] = [
  { to: "/criteria", n: "01", title: "Выполнение 7 критериев ТЗ", testid: "exp-criteria",
    text: "Раздел 6 ТЗ по подпунктам: что сделать, что увидите, чем доказано и честное ограничение. Шесть критериев продукта и питч.", cta: "Открыть критерии" },
  { to: "/validation", n: "02", title: "Протоколы валидации и точности", testid: "exp-validation",
    text: "Метрики подбора и теста с подписью расчёта: синтетика, модельная разметка, повтор теста, калибровка и ограничения.", cta: "Открыть протоколы" },
  { to: "/security", n: "03", title: "Красная кнопка: атаки на ИИ и античит", testid: "exp-security",
    text: "Атакуйте сами на живых демо-данных в памяти: инъекции в оценщик, утечка банка заданий, завышение ответов.", cta: "Запустить атаку" },
  { to: "/validation#evaluate", n: "04", title: "Проверка на своём JSON/CSV-наборе", testid: "exp-evaluate",
    text: "Свои анонимные потребности и профили (до 50 и 500) — выдача и p@k/nDCG@k на ваших данных; данные живут только в памяти запроса.", cta: "Загрузить набор" },
];

export default function Expertise() {
  usePageTitle("Экспертиза ФСП");
  return (
    <div className="np relative min-h-screen overflow-x-clip">
      <div className="np-backdrop" aria-hidden="true"><div className="np-gridlines" /><div className="np-glow np-glow-indigo" /><div className="np-glow np-glow-red" /></div>
      <SiteHeader premium />
      <main id="main" tabIndex={-1} className="relative mx-auto max-w-content px-4 pb-24 pt-10 outline-none sm:px-6 md:pt-14">
        <p className="np-eyebrow">Для экспертов жюри спецтрека ФСП</p>
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <span className="np-shield-xl" aria-hidden="true"><ShieldIcon className="h-7 w-7" /></span>
          <h1 className="text-4xl font-extrabold tracking-tight np-text md:text-5xl">Экспертиза <span className="np-grad">ФСП</span></h1>
        </div>
        <p className="mt-4 max-w-3xl text-base leading-relaxed np-muted md:text-lg">
          Всё для проверки «Драфта» — в одном месте: проводник за 12 минут, выполнение критериев ТЗ, протоколы валидации,
          атаки на ИИ и проверка на ваших данных. У каждого эксперта своя копия демо: действия и сброс не видны другим.
        </p>

        <div className="mt-10"><JuryPanel /></div>

        <section className="mt-14" aria-labelledby="exp-links-t">
          <h2 id="exp-links-t" className="text-2xl font-extrabold tracking-tight np-text md:text-3xl">Доказательства одной кнопкой</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {LINKS.map((l) => (
              <Link key={l.to} to={l.to} className="np-glass np-linkcard group p-6" data-testid={l.testid}>
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-sm np-accent">{l.n}</span>
                  <span className="np-arrow" aria-hidden="true">→</span>
                </div>
                <h3 className="mt-4 text-xl font-bold tracking-tight np-text">{l.title}</h3>
                <p className="mt-2 text-sm leading-relaxed np-muted">{l.text}</p>
                <p className="mt-4 text-sm font-semibold np-accent">{l.cta}</p>
              </Link>
            ))}
          </div>
          <p className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm np-muted">
            <Link to="/jury/live" className="font-semibold np-accent hover:underline">Демонстрация в зале по QR</Link>
            <Link to="/study" className="font-semibold np-accent hover:underline">Исследование с живыми пользователями</Link>
            <a href="/api/docs" className="font-semibold np-accent hover:underline">Документация API</a>
          </p>
        </section>
      </main>
      <SiteFooter premium />
    </div>
  );
}
