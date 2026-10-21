import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { IncidentSandbox } from "../../components/IncidentSandbox";
import { launchLiveAvatar } from "../../components/Interview";
import { JuryPanel } from "../../components/JuryPanel";
import { ShieldIcon, SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { errText } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { juryLogin } from "../../lib/jury";
import { usePageTitle } from "../../lib/meta";

/** W2: «Экспертиза ФСП» (/expertise) — единый хаб для экспертов жюри. Сюда перенесено всё конкурсное с главной:
 *  запуск главных инноваций в 1 клик, «Проверка за 12 минут», критерии ТЗ, протоколы валидации, «Красная кнопка»
 *  и проверка на своём наборе данных. */
const LINKS: { to: string; n: string; title: string; text: string; cta: string; testid: string }[] = [
  { to: "/criteria", n: "01", title: "Выполнение 7 критериев ТЗ", testid: "exp-criteria",
    text: "Раздел 6 ТЗ по подпунктам: что сделать, что увидите, чем доказано и честное ограничение. Шесть критериев продукта и питч.", cta: "Открыть критерии" },
  { to: "/validation#protocols", n: "02", title: "Протоколы валидации и точности", testid: "exp-validation",
    text: "Метрики подбора и теста с подписью расчёта: синтетика, модельная разметка, повтор теста, калибровка и ограничения.", cta: "Открыть протоколы" },
  { to: "/validation#red-button", n: "03", title: "Красная кнопка: атаки на ИИ и античит", testid: "exp-security",
    text: "Атакуйте сами на живых демо-данных в памяти: инъекции в оценщик, утечка банка заданий, завышение ответов.", cta: "Запустить атаку" },
  { to: "/validation#evaluate", n: "04", title: "Проверка на своём наборе пар", testid: "exp-evaluate",
    text: "Свои анонимные потребности и профили (до 50 и 500) — выдача и метрики точности на ваших данных; данные живут только в памяти запроса.", cta: "Загрузить набор" },
];

export default function Expertise() {
  usePageTitle("Экспертиза ФСП");
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showIncident, setShowIncident] = useState(false);

  async function openCandidateAvatar() {
    setBusy("cand-avatar"); setErr(null);
    try {
      if (me?.role !== "candidate") await juryLogin("candidate", signIn);
      await launchLiveAvatar(signIn, navigate, "candidate");
    }
    catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  async function openEmployerAdvisor() {
    setBusy("emp-advisor"); setErr(null);
    try {
      if (me?.role !== "employer") await juryLogin("employer", signIn);
      const needs = await api<any[]>("/employer/needs");
      const first = needs?.[0];
      if (first?.id) {
        navigate(`/employer/needs/${first.id}/compare`);
      } else {
        navigate("/employer/needs");
      }
    } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  async function openFspTournament() {
    setBusy("fsp-cup"); setErr(null);
    try {
      if (me?.role !== "employer") await juryLogin("employer", signIn);
      const needs = await api<any[]>("/employer/needs");
      const first = needs?.[0];
      if (first?.id) {
        const cup = await api<any>(`/employer/cups/from-need/${first.id}`, { body: {} });
        navigate(`/employer/cups/${cup.id}`);
      } else {
        navigate("/employer/cups");
      }
    } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  return (
    <div className="np relative min-h-screen overflow-x-clip">
      <div className="np-backdrop" aria-hidden="true"><div className="np-gridlines" /><div className="np-glow np-glow-indigo" /><div className="np-glow np-glow-red" /></div>
      <SiteHeader premium />
      <main id="main" tabIndex={-1} className="relative mx-auto max-w-content px-4 pb-24 pt-10 outline-none sm:px-6 md:pt-14">
        <p className="np-eyebrow">Единый раздел для экспертов жюри спецтрека ФСП</p>
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <span className="np-shield-xl" aria-hidden="true"><ShieldIcon className="h-7 w-7" /></span>
          <h1 className="text-4xl font-extrabold tracking-tight np-text md:text-5xl">Экспертиза <span className="np-grad">ФСП</span></h1>
        </div>
        <p className="mt-4 max-w-3xl text-base leading-relaxed np-muted md:text-lg">
          Основной сайт работает как чистый коммерческий продукт для кандидатов и работодателей, а все инструменты проверки для жюри собраны на этой вкладке:
          быстрый запуск ключевых инноваций в 1 клик, проводник по ТЗ, протоколы валидации и стенд атак на ИИ.
        </p>

        <section className="mt-10" aria-labelledby="exp-knockout-t" data-testid="exp-knockout">
          <p className="np-eyebrow">Новые продуктовые решения · запуск в 1 клик без длинных путей</p>
          <h2 id="exp-knockout-t" className="mt-2 text-2xl font-extrabold tracking-tight np-text md:text-3xl">Проверьте главные фишки сразу в деле</h2>
          {err && <p className="mt-3 text-sm np-risk" role="alert">{err}</p>}
          <Link to="/warroom" data-testid="exp-go-warroom"
            className="group relative mt-5 block overflow-hidden rounded-3xl border border-rose-400/50 bg-gradient-to-br from-[#160a2a] via-[#2a0c38] to-[#0b1240] p-6 text-white shadow-[0_20px_60px_-20px_rgba(255,0,83,0.8)] transition hover:-translate-y-0.5 md:p-8">
            <span className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-rose-500/25 blur-3xl" aria-hidden="true" />
            <span className="pointer-events-none absolute -bottom-20 left-1/3 h-56 w-56 rounded-full bg-indigo-500/25 blur-3xl" aria-hidden="true" />
            <span className="relative flex flex-wrap items-center gap-2 font-mono text-xs font-bold uppercase tracking-[0.2em] text-rose-300">
              <span className="h-2 w-2 animate-pulse rounded-full bg-rose-400" />Интерактивный стенд · проверка вживую
            </span>
            <span className="relative mt-3 block text-2xl font-black leading-tight md:text-3xl">Боевой ИИ-Полигон: Архитектура, Аватар и Античит вживую</span>
            <span className="relative mt-3 grid gap-3 text-sm text-white/75 md:grid-cols-2">
              <span><b className="text-white">Режим А.</b> Живая схема микросервисов под нагрузкой: включайте режимы отказоустойчивости, правьте конфигурацию и проверяйте реакцию системы в реальном времени.</span>
              <span><b className="text-white">Режим Б.</b> Сравнение «нечестный кандидат против контроля самостоятельности»: скрытая метка задания, темп набора и автоматический вызов на устную защиту.</span>
            </span>
            <span className="relative mt-5 inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-extrabold text-[#1a1240] transition group-hover:bg-rose-50">Открыть Боевой ИИ-Полигон <span aria-hidden="true">→</span></span>
          </Link>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 01 · КАНДИДАТ</span>
              <h3 className="mt-2 text-xl font-bold np-text">Живой видео-аватар: устная защита кода</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Прямой вход в комнату разговора без промежуточных анкет: ИИ-интервьюер озвучивает вопрос по решению кандидата своим голосом и автоматически включает микрофон для вашего ответа.
              </p>
              <button type="button" onClick={openCandidateAvatar} disabled={!!busy} className="np-btn-primary mt-4 px-5 py-2.5 text-sm" data-testid="exp-go-avatar">
                {busy === "cand-avatar" ? "Открываем комнату разговора…" : "Поговорить с ИИ-интервьюером (1 клик)"}
              </button>
            </article>

            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 02 · ДИРЕКТОР И HR</span>
              <h3 className="mt-2 text-xl font-bold np-text">ИИ-советник руководителя на сравнении кандидатов</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Аватар докладывает голосом по топ-кандидатам вакансии (кто лидер по адаптивному тесту и ФСП, какие навыки не проверены, чья вилка выгоднее) и отвечает на вопросы руководителя голосом.
              </p>
              <button type="button" onClick={openEmployerAdvisor} disabled={!!busy} className="np-btn-primary mt-4 px-5 py-2.5 text-sm" data-testid="exp-go-advisor">
                {busy === "emp-advisor" ? "Открываем сравнение…" : "Открыть ИИ-советника директора (1 клик)"}
              </button>
            </article>

            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 03 · ИНТЕРАКТИВНЫЙ ТЕСТ</span>
              <h3 className="mt-2 text-xl font-bold np-text">Визуальный тренажёр «Пульт инцидента»</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Вместо скучных текстовых задач на Senior/Lead — живой пульт платёжного шлюза под нагрузкой (38 % таймаутов и дубли списаний). Переключайте параметры и смотрите, как меняются метрики.
              </p>
              <button type="button" onClick={() => setShowIncident((v) => !v)} className="np-btn-ghost mt-4 px-5 py-2.5 text-sm font-bold" data-testid="exp-go-incident">
                {showIncident ? "Скрыть пульт инцидента" : "Открыть «Пульт инцидента» прямо здесь"}
              </button>
            </article>

            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 04 · ЭКОСИСТЕМА ФСП</span>
              <h3 className="mt-2 text-xl font-bold np-text">Отборочный турнир ФСП из вакансии в 1 клик</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Работодатель одной кнопкой превращает свою вакансию в 7-дневный турнир по дисциплине «Продуктовое программирование» из 3 задач банка с автопроверкой и лидербордом призёров.
              </p>
              <button type="button" onClick={openFspTournament} disabled={!!busy} className="np-btn-ghost mt-4 px-5 py-2.5 text-sm font-bold" data-testid="exp-go-tournament">
                {busy === "fsp-cup" ? "Запускаем турнир…" : "Запустить турнир ФСП из вакансии (1 клик)"}
              </button>
            </article>
          </div>

          {showIncident && (
            <div className="mt-5">
              <IncidentSandbox />
            </div>
          )}
        </section>

        <div className="mt-12"><JuryPanel /></div>

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
