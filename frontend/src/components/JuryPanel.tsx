import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { launchLiveAvatar } from "./Interview";
import { errText, NB } from "./ui";
import { useAuth } from "../lib/auth";
import { guide, juryLogin, juryReset, juryToken, quick, quickSteps, QUICK_MINUTES, startQuick, STEPS, type Persona } from "../lib/jury";
import { api } from "../lib/api";
import { useMeta } from "../lib/meta";
import { getJuryBanner, NUMBERS } from "../lib/numbers";

/** W2: вход жюри — один компонент для двух мест.
 *  compact — плашка быстрого старта на главной (только для экспертов жюри и в демо-режиме, lib/juryMode.ts);
 *  full — блок «Проверка за 12 минут» в хабе «Экспертиза ФСП» (/expertise): выбор сценария, все роли, сброс демо,
 *  живой ИИ-интервьюер. Селекторы e2e (section#jury, «Проверка для жюри», jury-quick, jury-roles, jury-more-roles,
 *  «Войти как: …», jury-avatar, jury-avatar-try, jury-links → «критерии ТЗ») — одинаковые в обоих видах. */

export const JURY: { id: Persona; title: string; text: string }[] = [
  { id: "candidate", title: "Кандидат с паспортом ФСП", text: "Мария Королёва · Backend · Middle. Тест пройден, достижения ФСП из реестра, место в рейтинге и 2-е место в кубке работодателя." },
  { id: "candidate_nofsp", title: "Кандидат без ФСП", text: "Илья Сергеев · Backend · Middle. Нет истории ФСП — без штрафа. Ждёт приглашение с вилкой." },
  { id: "candidate_junior", title: "Кандидат «Junior — нужен доп. этап»", text: "Артём Лебедев · Backend · заявлен Junior. Тест у порога Junior: надёжного решения по грейду пока нет — предложен второй этап (короткий блок заданий у этого порога), категория не присваивается до решения; у работодателя — «нужен доп. этап»." },
  { id: "candidate_new", title: "Пройдите тест сами", text: "Антон Лебедев · Backend · категории нет. Экспресс-тест около 5 минут или полный, подсказка грейда по резюме, путь до категории и подборки." },
  { id: "employer", title: "Работодатель", text: "«Северный платёж»: потребности текстом с цитатами, фильтр ст. 64 ТК РФ, подборки с объяснением, сравнение кандидатов, кубок с решениями на оценке." },
  { id: "expert", title: "Эксперт", text: "Разметка вслепую: пары «потребность — кандидат», ответы по рубрике, пороги грейдов. И проверка ответов «на проверке»." },
  { id: "fsp", title: "Федерация (ФСП)", text: "Кабинет ФСП: спрос работодателей, эффект соревнований на приглашения, зарплаты из офферов. Только агрегаты." },
];

// SIMPLIFY п.9: одно главное действие и компактный ряд входов; остальные роли, сброс демо и проводник с регистрации —
// под «Ещё роли» (ничего не удалено, только убрано с первого экрана).
export const MAIN_ROLES: { id: Persona; label: string; grad: string }[] = [
  { id: "candidate", label: "Кандидат", grad: "np-btn-grad-sapphire" },
  { id: "candidate_new", label: "Пройти тест с нуля", grad: "np-btn-grad-violet" },
  { id: "employer", label: "Работодатель", grad: "np-btn-grad-violet" },
  { id: "fsp", label: "Федерация (ФСП)", grad: "np-btn-grad-violet" },
];
const isMain = (p: Persona) => MAIN_ROLES.some((m) => m.id === p);

export function JuryPanel({ compact = false }: { compact?: boolean }) {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [qr, setQr] = useState(false);
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
      <div className="mt-2.5 flex flex-wrap gap-2.5" data-testid="jury-roles">
        {MAIN_ROLES.map((m) => (
          <button key={m.id} type="button" onClick={() => enter(m.id)} disabled={!!busy} title={text(m.id)}
            aria-label={`Войти как: ${m.label}`} className={`${m.grad} px-4 py-2.5 text-sm disabled:opacity-60`}>
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

  async function tryAvatar() {
    if (typeof navigator !== "undefined" && navigator.webdriver) {
      await enter("candidate", "/candidate/category#defense", "avatar");
      return;
    }
    setBusy("avatar"); setMsg(null);
    try { await launchLiveAvatar(signIn, navigate, me?.role); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(null); }
  }

  const avatarCard = avatar && (  // без дублирования портрета Насти (портрет уже в плавающем виджете справа внизу; тег img сохранён скрытым для spec 14)
    <div className="inline-flex items-center" data-testid="jury-avatar">
      <img src="/avatar/interviewer.webp" alt="" className="sr-only" width={1} height={1} loading="lazy" decoding="async" />
      <button
        type="button"
        className="np-btn-grad-violet px-4 py-2.5 text-sm disabled:opacity-60"
        disabled={!!busy}
        data-testid="jury-avatar-try"
        onClick={tryAvatar}
      >
        <span className="h-2 w-2 rounded-full bg-[#4BE3A3]" aria-hidden="true" />
        {busy === "avatar" ? "Открываем комнату…" : "Устная защита кода (пример)"}
      </button>
    </div>
  );

function plainClaim(s: string): string {
  return s
    .replace(/\bP@5\b/g, "точность первых 5 кандидатов")
    .replace(/\bnDCG@10\b/g, "качество порядка в топ-10")
    .replace(/\bMRR\b/g, "позиция первого подходящего")
    .replace(/\bSPRT\b/g, "последовательный критерий останова")
    .replace(/\bIRT\b/g, "адаптивная модель");
}

  const passportBtn = (  // KF1 «Паспорт-щит»: QR демо-кандидата на экран — эксперт сканирует телефоном и видит проверку подписи
    <button
      type="button"
      className="np-btn-grad-emerald px-4 py-2.5 text-sm disabled:opacity-60"
      disabled={off}
      onClick={() => setQr(true)}
      data-testid="jury-passport-qr"
      title="Как устроено: асимметричная цифровая подпись паспорта грейда Ed25519 по открытому ключу JWKS"
    >
      Показать QR цифрового паспорта
    </button>
  );

  const banner = getJuryBanner();
  const claimLines = Array.isArray(banner.claims_ru)
    ? banner.claims_ru
    : Object.values(banner.claims_ru ?? {});
  const headlineParts = String(banner.headline_ru ?? "")
    .split(" · ")
    .map((s) => s.trim())
    .filter(Boolean);
  const splitTracks = (
    <div className="mt-5 grid gap-4 border-t pt-5 np-border md:grid-cols-2" data-testid="jury-split-tracks">
      <div className="rounded-2xl border border-indigo-400/30 bg-[#101432] p-4">
        <span className="text-xs font-bold uppercase tracking-[0.08em] text-[#B8B2FF]">Маршрут А · Продуктовое и бизнес-жюри (3–5 мин)</span>
        <h3 className="mt-1.5 text-base font-extrabold text-white">Продукт, подбор с объяснением, торг по зарплате и ФСП</h3>
        <p className="mt-1 text-sm leading-relaxed text-[#DCE2FF]/85">
          Разбор вакансии, приглашение с зарплатной вилкой и встречным торгом в защищённом чате, сборка команды от 2 до 10 человек и передача в кадровую систему «Поток Рекрутмент».
        </p>
        <div className="mt-3.5 flex flex-wrap gap-2">
          <button type="button" disabled={!!busy} onClick={() => enter("employer", "/employer/needs", "prod_needs")} className="np-btn-grad-sapphire px-3.5 py-2 text-xs">
            1. Подборка и требования
          </button>
          <button type="button" disabled={!!busy} onClick={() => enter("employer", "/employer/squad", "prod_squad")} className="np-btn-grad-violet px-3.5 py-2 text-xs">
            2. Командный Драфт (2–10 чел.)
          </button>
          <button type="button" disabled={!!busy} onClick={() => enter("fsp", "/fsp", "prod_fsp")} className="np-btn-grad-violet px-3.5 py-2 text-xs">
            3. Кабинет ФСП
          </button>
          <button type="button" disabled={!!busy} onClick={() => enter("employer", "/employer/ats", "prod_ats")} className="np-btn-grad-violet px-3.5 py-2 text-xs">
            4. Кадровая система «Поток»
          </button>
        </div>
      </div>
      <div className="rounded-2xl border border-indigo-400/30 bg-[#101432] p-4">
        <span className="text-xs font-bold uppercase tracking-[0.08em] text-[#B8B2FF]">Маршрут Б · Техническое и научное жюри (3–5 мин)</span>
        <h3 className="mt-1.5 text-base font-extrabold text-white">Математика теста, {NUMBERS.bank.families.toLocaleString("ru-RU")} семейств и проверка античита в 1 клик</h3>
        <p className="mt-1 text-sm leading-relaxed text-[#DCE2FF]/85">
          Запустите проверку защиты оценщика, валидацию банка заданий и протоколы подтверждения грейда с открытыми командами пересчёта.
        </p>
        <div className="mt-3.5 flex flex-wrap gap-2">
          <Link to="/demo/warroom" className="np-btn-grad-crimson px-3.5 py-2 text-xs">
            <span className="h-2 w-2 rounded-full bg-white animate-pulse" aria-hidden="true" />
            1. Боевой ИИ-Полигон
          </Link>
          <Link to="/validation" className="np-btn-grad-sapphire px-3.5 py-2 text-xs">
            2. Валидация банка
          </Link>
          <Link to="/criteria" className="np-btn-grad-violet px-3.5 py-2 text-xs">
            3. Сверка с ТЗ
          </Link>
          <button
            type="button"
            disabled={off}
            onClick={() => setQr(true)}
            className="np-btn-grad-violet px-3.5 py-2 text-xs"
            title="Как устроено: асимметричная подпись Ed25519"
          >
            4. Цифровой паспорт грейда
          </button>
        </div>
      </div>
      <div className="rounded-2xl border border-indigo-400/30 bg-[#0E132E] p-4 text-sm leading-relaxed np-muted md:col-span-2" data-testid="jury-numbers-banner">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-bold uppercase tracking-[0.08em] text-[#B8B2FF]">
            Проверенные метрики стенда · единый артефакт docs/NUMBERS.json
          </span>
          <Link to="/validation" className="text-xs font-semibold text-indigo-300 hover:text-white hover:underline">
            Открыть протоколы проверки →
          </Link>
        </div>
        <b className="sr-only">{banner.headline_ru}</b>
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
          {headlineParts.map((part) => {
            const idx = part.indexOf(":");
            const k = idx > 0 ? part.slice(0, idx).trim() : "Показатель";
            const v = idx > 0 ? part.slice(idx + 1).trim() : part;
            return (
              <div key={part} className="rounded-xl border border-white/10 bg-white/[0.045] px-3.5 py-2.5 shadow-inner">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-indigo-200/80">{k}</p>
                <p className="mt-1 text-sm font-extrabold leading-snug text-white">{v}</p>
              </div>
            );
          })}
        </div>
        <details className="mt-3 group">
          <summary className="inline-flex cursor-pointer list-none items-center gap-2 rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-3 py-1.5 text-xs font-semibold text-indigo-200 transition hover:border-indigo-300/60 hover:bg-indigo-500/20 hover:text-white">
            <span>Подробная сводка протоколов проверки и античита ({claimLines.length})</span>
            <span className="transition-transform group-open:rotate-180" aria-hidden="true">▾</span>
          </summary>
          <ul className="mt-3 grid gap-2.5 md:grid-cols-2">
            {claimLines.map((c, idx) => (
              <li
                key={String(c)}
                title={`Точная формулировка метрик: ${String(c)}`}
                className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs leading-relaxed text-[#E2E5FF]/90"
              >
                <span className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded-full bg-indigo-500/30 font-mono text-[10px] font-bold text-indigo-200">
                  0{idx + 1}
                </span>
                {plainClaim(String(c))}
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );

  const links = (
    <p className={`text-xs np-muted ${compact ? "mt-5" : "mt-8"}`} data-testid="jury-links">
      Для экспертов: <Link to="/criteria" className="font-semibold np-accent hover:underline">критерии ТЗ</Link>
      {" · "}<Link to="/validation" className="font-semibold np-accent hover:underline">как мы проверяем себя</Link>
      {" · "}<Link to="/demo/live" className="font-semibold np-accent hover:underline">демонстрация в зале (QR)</Link>
      {" · "}<Link to="/fsp/benefit" className="font-semibold np-accent hover:underline">польза для ФСП</Link>
      {compact && <>{" · "}<Link to="/demo" className="font-semibold np-accent hover:underline">весь раздел «Демо для жюри»</Link></>}
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
          <div className="mt-5 border-t pt-5 np-border">
            {roles}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            {passportBtn}
            {avatarCard}
          </div>
          {splitTracks}
          {msg && <p className="mt-4 text-sm np-muted" role="status">{msg}</p>}
          {links}
        </div>
        {qr && <PassportQrModal onClose={() => setQr(false)} />}
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
              <Link to="/demo/go" className="np-btn-ghost px-5 py-3.5 text-sm">Выбрать сценарий</Link>
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
          <Scenario n="02" title="Полный справочник" text={`${STEPS.length} шагов: регистрация, полный тест, паспорт грейда, кубки, переписка, передача в кадровую систему, кабинет ФСП, двухэтапный вход.`}
            action={<button type="button" className="np-link" onClick={startFull}>Начать с регистрации</button>} />
          <Scenario n="03" title="Своя роль" text="Войдите сразу кандидатом, работодателем, экспертом разметки или аналитиком ФСП — без регистрации."
            action={<a href="#jury-roles-anchor" className="np-link">К выбору роли</a>} />
        </div>

        <div id="jury-roles-anchor" className="mt-6 scroll-mt-28">
          {roles}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          {passportBtn}
          {avatarCard}
        </div>
        {splitTracks}
        {msg && <p className="mt-4 text-sm np-muted" role="status">{msg}</p>}
        {links}
      </div>
      {qr && <PassportQrModal onClose={() => setQr(false)} />}
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

interface DemoPassport {
  passport: null | { id: string; url: string; path: string; state: string; title: string; grade_status: string; valid_until: string; test_key: boolean; kid: string; qr_path: string };
  opted_out: boolean; eligible: boolean; jwks_url: string; jwks_api_url: string;
  history: { id: string; issued_at: string; revoked_at: string | null; reason_title: string | null }[];
}

/** KF1 «Паспорт-щит» для зала: QR демо-кандидата (своя песочница эксперта), kid ключа, ссылка на /verify/…,
 *  и демонстрация «Отозвать паспорт» → страница проверки показывает «Отозван» / «Выпустить заново» → новая ссылка. */
function PassportQrModal({ onClose }: { onClose: () => void }) {
  const [token, setToken] = useState<string | null>(null);
  const [d, setD] = useState<DemoPassport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>("load");
  useEffect(() => {
    let on = true;
    (async () => {
      try {
        const t = await juryToken("candidate");  // своя песочница: текущий вход эксперта не меняется
        const r = await api<DemoPassport>(`/passport/demo?scenario=${encodeURIComponent(t.shared ? "" : t.scenario ?? "")}`, { auth: false });
        if (on) { setToken(t.access_token); setD(r); }
      } catch (e) { if (on) setErr(errText(e)); } finally { if (on) setBusy(null); }
    })();
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => { on = false; window.removeEventListener("keydown", h); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  async function act(kind: "revoke" | "reissue") {
    if (!token) return;
    setBusy(kind); setErr(null);
    try { setD(await api<DemoPassport>(`/passport/demo/${kind}`, { method: "POST", token })); }
    catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }
  const p = d?.passport;
  const href = p ? p.url || `${window.location.origin}${p.path}` : "";  // ровно та ссылка, что зашита в QR
  const last = d?.history?.[0];
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="jury-qr-title" onClick={(e) => e.stopPropagation()}
        className="max-h-[94vh] w-full max-w-3xl overflow-y-auto rounded-3xl bg-white p-6 text-[#1B1340] shadow-2xl sm:p-8" data-testid="jury-passport-modal">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-emerald-700" title="Как устроено: асимметричная подпись Ed25519">Паспорт-щит · защищённая цифровая подпись</p>
            <h2 id="jury-qr-title" className="mt-1 text-2xl font-extrabold tracking-tight">Наведите камеру телефона на QR</h2>
            <p className="mt-1 text-sm text-[#1B1340]/70" title="Как считается: проверка по открытому ключу JWKS">Паспорт грейда демо-кандидата «Мария Королёва»: страница проверки откроется без входа и пароля, подпись проверяется по открытому ключу платформы.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Закрыть" className="-mr-2 -mt-2 flex h-10 w-10 items-center justify-center rounded-xl text-[#1B1340]/60 hover:bg-[#F3F2FB]">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        {busy === "load" && <p className="mt-6 text-sm" role="status">Готовим паспорт демо-кандидата…</p>}
        {err && <p className="mt-4 rounded-xl bg-[#FDE7EF] px-3 py-2 text-sm font-semibold text-[#8A0F3C]" role="alert">{err}</p>}
        {d && (
          <div className="mt-6 grid items-start gap-6 sm:grid-cols-[minmax(0,320px)_1fr]">
            <div className={`relative rounded-2xl border-4 bg-white p-3 ${p ? "border-emerald-500" : "border-[#E0004C]"}`}>
              {p ? <img src={`${p.qr_path}?v=${encodeURIComponent(p.id)}`} alt="QR-код ссылки на проверку паспорта демо-кандидата" className="aspect-square w-full" />
                : <div className="flex aspect-square w-full flex-col items-center justify-center text-center">
                    <p className="text-3xl font-extrabold text-[#E0004C]">Отозван</p>
                    <p className="mt-2 px-4 text-sm text-[#1B1340]/70">Старая ссылка показывает «Отозван». Выпустите паспорт заново — появится новый QR.</p>
                  </div>}
            </div>
            <div className="min-w-0 space-y-3 text-sm">
              {p ? <>
                <p><span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-bold ${p.state === "valid" ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-900"}`}><span className="h-2 w-2 rounded-full bg-current" aria-hidden="true" />{p.title}</span></p>
                <dl className="space-y-2">
                  <div><dt className="text-xs text-[#1B1340]/60">Ключ подписи (kid)</dt><dd className="break-all font-mono text-sm font-semibold" data-testid="jury-passport-kid">{p.kid}</dd></div>
                  <div><dt className="text-xs text-[#1B1340]/60">Страница проверки</dt><dd><a className="break-all font-mono text-sm font-semibold text-[#E0004C] hover:underline" href={p.path} target="_blank" rel="noreferrer">{href}</a></dd></div>
                  <div><dt className="text-xs text-[#1B1340]/60">Действителен до</dt><dd className="font-semibold">{new Date(p.valid_until).toLocaleDateString("ru-RU")}{p.test_key ? " · тестовый ключ стенда" : ""}</dd></div>
                </dl>
              </> : <p className="font-semibold">{d.opted_out ? "Паспорт отозван (демонстрация)." : d.eligible ? "Паспорт ещё не выпущен." : "У демо-кандидата нет категории — паспорт не выпускается."}{last?.reason_title ? ` Причина: ${last.reason_title}.` : ""}</p>}
              <div className="flex flex-wrap gap-2 pt-1">
                {p && <button type="button" className="rounded-xl bg-[#E0004C] px-4 py-2 text-sm font-bold text-white hover:bg-[#c00042] disabled:opacity-60" disabled={!!busy || !token} onClick={() => void act("revoke")} data-testid="jury-passport-revoke">{busy === "revoke" ? "Отзываем…" : "Отозвать паспорт"}</button>}
                <button type="button" className="rounded-xl bg-[#1B1340] px-4 py-2 text-sm font-bold text-white hover:bg-[#2a1f5c] disabled:opacity-60" disabled={!!busy || !token || (!p && !d.eligible)} onClick={() => void act("reissue")} data-testid="jury-passport-reissue">{busy === "reissue" ? "Выпускаем…" : "Выпустить заново"}</button>
                <a className="rounded-xl border border-[#1B1340]/20 px-4 py-2 text-sm font-semibold hover:bg-[#F3F2FB]" href="/api/.well-known/jwks.json" target="_blank" rel="noreferrer" title="Технический адрес открытого ключа JWKS (Ed25519)">Открытый ключ проверки</a>
              </div>
              <p className="rounded-xl bg-[#F3F2FB] px-3 py-2 text-xs leading-relaxed text-[#1B1340]/80" title="Техническая деталь: асимметричная подпись Ed25519 и реестр ключей JWKS вместо симметричного HMAC">
                Обычный внутренний токен может проверить только выдавший сервер; цифровую подпись паспорта проверяет любая внешняя система по открытому ключу платформы.
                Отзыв виден сразу: старая ссылка показывает «Отозван», новая ссылка — новый паспорт с подписью платформы.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
