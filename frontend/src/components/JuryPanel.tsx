import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errText, NB } from "./ui";
import { useAuth } from "../lib/auth";
import { guide, juryLogin, juryReset, quick, quickSteps, QUICK_MINUTES, startQuick, STEPS, type Persona } from "../lib/jury";
import { useMeta } from "../lib/meta";

/** W2: вход жюри — один компонент для двух мест.
 *  compact — плашка быстрого старта на главной (только для экспертов жюри и в демо-режиме, lib/juryMode.ts);
 *  full — блок «Проверка за 12 минут» в хабе «Экспертиза ФСП» (/expertise): выбор сценария, все роли, сброс демо,
 *  живой ИИ-интервьюер. Селекторы e2e (section#jury, «Проверка для жюри», jury-quick, jury-roles, jury-more-roles,
 *  «Войти как: …», jury-avatar, jury-avatar-try, jury-links → «критерии ТЗ») — одинаковые в обоих видах. */

export const JURY: { id: Persona; title: string; text: string }[] = [
  { id: "candidate", title: "Кандидат с паспортом ФСП", text: "Мария Королёва · Backend · Middle. Тест пройден, достижения ФСП из реестра, место в рейтинге и 2-е место в кубке работодателя." },
  { id: "candidate_nofsp", title: "Кандидат без ФСП", text: "Илья Сергеев · Backend · Middle. Нет истории ФСП — без штрафа. Ждёт приглашение с вилкой." },
  { id: "candidate_junior", title: "Кандидат «Junior (предварительно)»", text: "Артём Лебедев · Backend · Junior у порога: грейд не подтверждён, но и не доказанно ниже. Вероятность уровня, короткое дотестирование, статус у работодателя." },
  { id: "candidate_new", title: "Пройдите тест сами", text: "Антон Лебедев · Backend · категории нет. Экспресс-тест около 5 минут или полный, подсказка грейда по резюме, путь до категории и подборки." },
  { id: "employer", title: "Работодатель", text: "«Северный платёж»: потребности текстом с цитатами, фильтр ст. 64 ТК РФ, подборки с объяснением, сравнение кандидатов, кубок с решениями на оценке." },
  { id: "expert", title: "Эксперт", text: "Разметка вслепую: пары «потребность — кандидат», ответы по рубрике, пороги грейдов. И проверка ответов «на проверке»." },
  { id: "fsp", title: "Федерация (ФСП)", text: "Кабинет ФСП: спрос работодателей, эффект соревнований на приглашения, зарплаты из офферов. Только агрегаты." },
];

// SIMPLIFY п.9: одно главное действие и компактный ряд входов; остальные роли, сброс демо и проводник с регистрации —
// под «Ещё роли» (ничего не удалено, только убрано с первого экрана).
export const MAIN_ROLES: { id: Persona; label: string }[] = [
  { id: "candidate", label: "Кандидат" }, { id: "candidate_new", label: "Пройти тест с нуля" },
  { id: "employer", label: "Работодатель" }, { id: "fsp", label: "Федерация (ФСП)" },
];
const isMain = (p: Persona) => MAIN_ROLES.some((m) => m.id === p);

export function JuryPanel({ compact = false }: { compact?: boolean }) {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const meta = useMeta();
  const interview = !!meta?.interview?.enabled;  // Я15: шаг «по желанию» в «12 минутах»
  const avatar = interview && !!meta?.interview?.avatar;  // SIMPLIFY п.8: карточка «ИИ-интервьюер» — только при образе интервьюера
  const steps = quickSteps(meta?.interview);
  const off = meta ? !meta.jury_mode_available : false;

  async function enter(p: Persona, next?: string, key: string = p) {
    setBusy(key); setMsg(null);
    try { navigate(await juryLogin(p, signIn, next)); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(null); }
  }
  async function quickStart() {  // Я9: «Проверка за 12 минут» — вход работодателем своей копии
    setBusy("quick"); setMsg(null);
    try { navigate(await startQuick(signIn)); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(null); }
  }
  async function reset() {
    setBusy("reset"); setMsg(null);
    try { const r = await juryReset(signIn); setMsg(`Ваше демо пересоздано в исходное состояние за ${String(r.seconds).replace(".", ",")} с. У других экспертов ничего не изменилось.`); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(null); }
  }
  function startFull() { quick.setMode("full"); guide.enable(); guide.show(); guide.setStep(0); navigate("/register?role=candidate"); }
  const text = (p: Persona) => JURY.find((j) => j.id === p)?.text;

  const roles = (
    <div className="min-w-0 flex-1">
      <p className="text-sm font-semibold np-text">Или войдите сами:</p>
      <div className="mt-2 flex flex-wrap gap-2" data-testid="jury-roles">
        {MAIN_ROLES.map((m) => (
          <button key={m.id} type="button" onClick={() => enter(m.id)} disabled={!!busy} title={text(m.id)}
            aria-label={`Войти как: ${m.label}`} className="np-btn-ghost px-4 py-2 text-sm disabled:opacity-60">
            {busy === m.id ? "Входим…" : m.label}
          </button>
        ))}
      </div>
      <details className="mt-3 text-sm" data-testid="jury-more-roles">
        <summary className="cursor-pointer font-semibold np-accent">Ещё роли</summary>
        <div className="mt-2 flex flex-wrap gap-2">
          {JURY.filter((p) => !isMain(p.id)).map((p) => (
            <button key={p.id} type="button" onClick={() => enter(p.id)} disabled={!!busy} title={p.text}
              aria-label={`Войти как: ${p.title}`} className="np-btn-ghost px-3 py-1.5 text-sm disabled:opacity-60">
              {busy === p.id ? "Входим…" : p.title}
            </button>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2">
          <button type="button" className="font-semibold np-accent underline-offset-2 hover:underline" onClick={startFull}>
            Начать проводник с регистрации
          </button>
          <button type="button" className="font-semibold np-accent underline-offset-2 hover:underline disabled:opacity-50" disabled={!!busy} onClick={reset}>
            {busy === "reset" ? "Сбрасываем…" : "Сбросить своё демо в исходное состояние"}
          </button>
        </div>
      </details>
    </div>
  );

  const avatarCard = avatar && (  // п.8: образ интервьюера — постер (без видео), вход демо-кандидатом сразу к панели устной защиты
    <div className={`np-glass flex w-full items-center gap-4 p-4 ${compact ? "max-w-sm" : ""}`} data-testid="jury-avatar">
      <div className="relative shrink-0">
        <img src="/avatar/interviewer.webp" alt="Портрет ИИ-интервьюера: сгенерирован моделью, несуществующий человек"
          className="h-16 w-16 rounded-xl object-cover" width={64} height={64} loading="lazy" decoding="async" />
        <span className="np-live-dot absolute -right-1 -top-1" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-bold np-text">ИИ-интервьюер</p>
        {!compact && <p className="mt-0.5 text-xs leading-snug np-muted">Живая устная защита кода голосом или в чате. ИИ-интервьюер, не человек.</p>}
        <button type="button" className="np-btn-primary mt-2 px-4 py-2 text-sm" disabled={!!busy} data-testid="jury-avatar-try"
          onClick={() => enter("candidate", "/candidate/category#defense", "avatar")}>{busy === "avatar" ? "Входим…" : "Попробовать устную защиту"}</button>
      </div>
    </div>
  );

  const links = (
    <p className={`text-xs np-muted ${compact ? "mt-5" : "mt-8"}`} data-testid="jury-links">
      Для экспертов: <Link to="/criteria" className="font-semibold np-accent hover:underline">критерии ТЗ</Link>
      {" · "}<Link to="/validation" className="font-semibold np-accent hover:underline">как мы проверяем себя</Link>
      {" · "}<Link to="/jury/live" className="font-semibold np-accent hover:underline">демонстрация в зале (QR)</Link>
      {compact && <>{" · "}<Link to="/expertise" className="font-semibold np-accent hover:underline">вся экспертиза ФСП</Link></>}
    </p>
  );

  if (compact) {
    return (
      <section id="jury" className="relative mx-auto max-w-content scroll-mt-24 px-4 sm:px-6" aria-labelledby="jury-title">
        <div className="np-glass np-glass-accent p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
            <div className="min-w-0 flex-1 basis-64">
              <p className="np-eyebrow">Режим эксперта · своя копия демо</p>
              <h2 id="jury-title" className="mt-2 text-xl font-extrabold tracking-tight np-text md:text-2xl">Проверка для жюри за {QUICK_MINUTES}{NB}минут</h2>
              <p className="mt-1 max-w-xl text-sm leading-relaxed np-muted">Проводник проведёт по главному сценарию. Регистрироваться не нужно.</p>
            </div>
            <button type="button" className="np-btn-primary px-6 py-3.5 text-base" disabled={!!busy} onClick={quickStart} data-testid="jury-quick">
              {busy === "quick" ? "Входим…" : `Начать проверку за ${QUICK_MINUTES} минут`}</button>
          </div>
          <div className="mt-5 flex flex-wrap items-start gap-5 border-t pt-5 np-border">
            {roles}
            {avatarCard}
          </div>
          {msg && <p className="mt-4 text-sm np-muted" role="status">{msg}</p>}
          {links}
        </div>
      </section>
    );
  }

  return (
    <section id="jury" className="scroll-mt-24" aria-labelledby="jury-title">
      <div className="np-glass np-glass-accent p-5 sm:p-8">
        <div className="grid gap-8 lg:grid-cols-[1.2fr_1fr]">
          <div className="min-w-0">
            <p className="np-eyebrow">{steps.length} шагов · около {QUICK_MINUTES}{NB}минут</p>
            <h2 id="jury-title" className="mt-3 text-2xl font-extrabold tracking-tight np-text md:text-3xl">Проверка для жюри за {QUICK_MINUTES}{NB}минут</h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed np-muted md:text-base">
              Главный сценарий ТЗ своими руками: своя потребность текстом, подборка с объяснением, приглашение с вилкой,
              ответ кандидата, экспресс-тест и доказательства. У каждого эксперта своя копия демо — действия и сброс не видны другим.
            </p>
            {off && <p className="mt-3 rounded-xl px-3 py-2 text-sm np-warn" role="note">Демо-режим жюри на этом сервере выключен: вход в один клик недоступен.</p>}
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button type="button" className="np-btn-primary px-7 py-4 text-base" disabled={!!busy} onClick={quickStart} data-testid="jury-quick">
                {busy === "quick" ? "Входим…" : `Начать проверку за ${QUICK_MINUTES} минут`}</button>
              <Link to="/jury/go" className="np-btn-ghost px-5 py-3.5 text-sm">Выбрать сценарий</Link>
            </div>
          </div>
          <ol className="grid content-start gap-2 text-sm" aria-label="Шаги проверки за 12 минут">
            {steps.map((s, i) => (
              <li key={s.title} className="np-step">
                <span className={`np-step-n ${s.optional || s.defense ? "np-step-n-opt" : ""}`} aria-hidden="true">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <b className="np-text">{s.title}</b>
                  <span className="block text-xs leading-snug np-muted">{s.crit}</span>
                </span>
                <span className="shrink-0 font-mono text-xs tabular-nums np-muted">≈{NB}{String(s.min).replace(".", ",")}{NB}мин</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="mt-8 grid gap-4 border-t pt-6 np-border md:grid-cols-3" aria-label="Сценарии проверки">
          <Scenario n="01" title={`Проверка за ${QUICK_MINUTES} минут`} text={`${steps.length} шагов главного сценария с таймером-ориентиром и критерием ТЗ у каждого шага.`}
            action={<button type="button" className="np-link" disabled={!!busy} onClick={quickStart}>Запустить проводник</button>} />
          <Scenario n="02" title="Полный справочник" text={`${STEPS.length} шагов: регистрация, полный тест, паспорт грейда, кубки, переписка, ATS, кабинет ФСП, второй фактор.`}
            action={<button type="button" className="np-link" onClick={startFull}>Начать с регистрации</button>} />
          <Scenario n="03" title="Своя роль" text="Войдите сразу кандидатом, работодателем, экспертом разметки или аналитиком ФСП — без регистрации."
            action={<a href="#jury-roles-anchor" className="np-link">К выбору роли</a>} />
        </div>

        <div id="jury-roles-anchor" className="mt-6 flex flex-wrap items-start gap-6 scroll-mt-28">
          {roles}
          {avatarCard}
        </div>
        {msg && <p className="mt-4 text-sm np-muted" role="status">{msg}</p>}
        {links}
      </div>
    </section>
  );
}

function Scenario({ n, title, text, action }: { n: string; title: string; text: string; action: ReactNode }) {
  return (
    <div className="np-tile p-4">
      <p className="font-mono text-xs np-faint">{n}</p>
      <p className="mt-1 font-bold np-text">{title}</p>
      <p className="mt-1 text-sm leading-relaxed np-muted">{text}</p>
      <div className="mt-3 text-sm">{action}</div>
    </div>
  );
}
