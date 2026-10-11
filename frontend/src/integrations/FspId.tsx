// «Войти через ФСП ID (демо)»: кнопка, подсказка с демо-учётками, страница возврата из Keycloak (билет → JWT).
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell } from "../components/AuthShell";
import { Alert, Field, Level, Loading, Toggle, errText, useApi } from "../components/ui";
import { api } from "../lib/api";
import { cabinetPath, useAuth } from "../lib/auth";
import { dateOnly } from "./Trust";
import { NO_FSP } from "../components/Origin";

interface FspConfig { enabled: boolean; demo: boolean; title: string; demo_accounts: { username: string; title: string }[]; demo_password: string | null; note: string }

export function FspIdMark({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden fill="none">
      <rect x="1.5" y="1.5" width="21" height="21" rx="6" stroke="currentColor" strokeWidth="2" />
      <path d="M8 16.5V7.5h6M8 12h4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <circle cx="16.5" cy="15.5" r="1.6" fill="currentColor" />
    </svg>
  );
}

async function start(intent: "login" | "link", role: "candidate" | "employer" = "candidate") {
  const r = await api<{ authorize_url: string }>("/fsp-id/start", { body: { intent, registration_role: role } });
  window.location.assign(r.authorize_url);
}

/** Кнопка входа на странице «Вход» + раскрывающаяся подсказка с демо-учётками realm fsp. */
export function FspIdLogin({ role = "candidate", compact = false }: { role?: "candidate" | "employer"; compact?: boolean }) {
  const { data } = useApi<FspConfig>("/fsp-id/config");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState(false);
  if (!data) return null;
  // UX-2: на регистрации — кнопка и одна строка, демо-учётки свёрнуты (страница «Вход» — без изменений)
  if (compact) return (
    <div className="mt-6 space-y-2">
      <div className="flex items-center gap-3 text-xs uppercase tracking-[0.14em] text-brand-ink/65"><span className="h-px flex-1 bg-brand-night/10" />или<span className="h-px flex-1 bg-brand-night/10" /></div>
      <button type="button" data-testid="button-fsp-login" className="btn-ghost w-full gap-2 !border-brand-plum/30 !bg-[#F3F2FB] !text-brand-night" disabled={busy || !data.enabled}
        onClick={async () => { setBusy(true); setErr(null); try { await start("login", role); } catch (e) { setErr(errText(e)); setBusy(false); } }}>
        <FspIdMark /> {busy ? "Переходим в ФСП ID…" : "Войти через ФСП ID"}
      </button>
      <p className="text-center text-xs text-brand-ink/70">{data.enabled ? (role === "candidate" ? "Без пароля, достижения ФСП — сразу в паспорт." : "Без пароля: кабинет компании создадим при первом входе.") : "ФСП ID на этом сервере ещё не подключён."}</p>
      <Alert>{err}</Alert>
      {data.demo_accounts.length > 0 && (
        <details className="text-xs text-brand-night" data-testid="fsp-demo-accounts">
          <summary className="cursor-pointer text-center font-semibold text-brand-plum hover:text-brand">Демо-учётки ФСП ID</summary>
          <div className="mt-2 rounded-xl bg-[#F3F2FB] p-4 leading-relaxed">
            <ul className="space-y-1.5">
              {data.demo_accounts.map((a) => <li key={a.username}><code className="rounded bg-white px-1.5 py-0.5 font-semibold">{a.username}</code> — {a.title}</li>)}
            </ul>
            {data.demo_password && <p className="mt-2">Пароль для всех демо-учёток: <code className="rounded bg-white px-1.5 py-0.5 font-semibold">{data.demo_password}</code></p>}
            <p className="mt-2 text-brand-ink/65">{data.note}</p>
          </div>
        </details>
      )}
    </div>
  );
  return (
    <div className="mt-6 space-y-3">
      <div className="flex items-center gap-3 text-xs uppercase tracking-[0.14em] text-brand-ink/65"><span className="h-px flex-1 bg-brand-night/10" />или<span className="h-px flex-1 bg-brand-night/10" /></div>
      <button type="button" data-testid="button-fsp-login" className="btn-ghost w-full gap-2 !border-brand-plum/30 !bg-[#F3F2FB] !text-brand-night" disabled={busy || !data.enabled}
        onClick={async () => { setBusy(true); setErr(null); try { await start("login", role); } catch (e) { setErr(errText(e)); setBusy(false); } }}>
        <FspIdMark /> {busy ? "Переходим в ФСП ID…" : "Войти через ФСП ID"}
      </button>
      <p className="text-center text-xs leading-relaxed text-brand-ink/70">{data.enabled ? `ФСП ID ↔ профиль${role === "candidate" ? " ↔ достижения" : " компании"}${data.demo ? " · демо-Keycloak" : ""}. При первом входе создадим кабинет ${role === "candidate" ? "кандидата" : "работодателя"}.` : "ФСП ID ↔ профиль ↔ достижения. Подключение к ФСП ID на этом сервере ещё не настроено."}</p>
      <Alert>{err}</Alert>
      {data.demo_accounts.length > 0 && <button type="button" className="w-full text-center text-xs font-semibold text-brand-plum hover:text-brand" onClick={() => setHint(!hint)} aria-expanded={hint}>
        {hint ? "Скрыть демо-учётки" : "Демо-учётки ФСП ID для проверки"}
      </button>}
      {hint && (
        <div className="rounded-xl bg-[#F3F2FB] p-4 text-xs leading-relaxed text-brand-night">
          <ul className="space-y-1.5">
            {data.demo_accounts.map((a) => <li key={a.username}><code className="rounded bg-white px-1.5 py-0.5 font-semibold">{a.username}</code> — {a.title}</li>)}
          </ul>
          {data.demo_password && <p className="mt-2">Пароль для всех демо-учёток: <code className="rounded bg-white px-1.5 py-0.5 font-semibold">{data.demo_password}</code></p>}
          <p className="mt-2 text-brand-ink/65">{data.note}</p>
        </div>
      )}
    </div>
  );
}

/** Связать существующий аккаунт кандидата с ФСП ID (страница «Паспорт ФСП»). */
export function FspIdLinkButton({ linkedVia }: { linkedVia?: string | null }) {
  const { data } = useApi<FspConfig>("/fsp-id/config");
  const [err, setErr] = useState<string | null>(null);
  if (!data?.enabled) return null;
  return (
    <div className="space-y-2">
      <button className="btn-primary gap-2" onClick={async () => { setErr(null); try { await start("link"); } catch (e) { setErr(errText(e)); } }}>
        <FspIdMark /> {linkedVia === "keycloak" ? "Обновить из ФСП ID" : "Связать через ФСП ID"}
      </button>
      <p className="text-xs text-brand-ink/65">Достижения из ФСП ID попадут в паспорт с уровнем доказанности T2 — «подтверждено реестром».</p>
      <Alert>{err}</Alert>
    </div>
  );
}

interface Preview { fsp_id: string | null; sport_rank: string | null; disciplines: string[]; achievements: { discipline: string; event: string; level: string; date: string | null; place: number | null; result: string | null }[]; has_history: boolean; email: string | null; username: string | null }
const LEVEL_RU: Record<string, string> = { school: "школьный", regional: "региональный", interregional: "межрегиональный", national: "всероссийский", international: "международный" };

/** /fsp-id/done?ticket=… — возврат из Keycloak. */
export function FspIdDone() {
  const [sp] = useSearchParams();
  const ticket = sp.get("ticket");
  const [state, setState] = useState<{ status: string; passport?: Preview; email_taken?: boolean; registration_role?: string } | null>(null);
  const [company, setCompany] = useState("");
  const [err, setErr] = useState<string | null>(sp.get("error"));
  const [pub, setPub] = useState(true);
  const [ok, setOk] = useState(false);
  const { signIn } = useAuth();
  const navigate = useNavigate();

  async function finish(r: any) {
    const me = await signIn(r.token.access_token);
    navigate(r.intent === "link" || me.role === "candidate" ? "/candidate/fsp?linked=1" : cabinetPath(me.role), { replace: true });
  }
  useEffect(() => {
    if (!ticket) return;
    api<any>("/fsp-id/exchange", { auth: false, body: { ticket } })
      .then((r) => (r.status === "ok" ? finish(r) : setState(r)))
      .catch((e) => setErr(errText(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticket]);

  async function complete() {
    setErr(null);
    try { await finish(await api<any>("/fsp-id/complete", { auth: false, body: { ticket, consent_processing: ok, consent_publication: pub, company_name: company || null } })); }
    catch (e) { setErr(errText(e)); }
  }

  const p = state?.passport;
  return (
    <AuthShell title="ФСП ID" subtitle="Вход через единую учётную запись участника соревнований ФСП."
      footer={<Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Вернуться ко входу</Link>}>
      {err ? <Alert>{err}</Alert> : !state ? <Loading text="Проверяем ответ ФСП ID…" /> : (
        <div className="space-y-4 text-sm">
          <Alert kind="info">Учётная запись {p?.username ? <b>{p.username}</b> : null} подтверждена ФСП ID. Создадим кабинет {state.registration_role === "employer" ? "работодателя" : "кандидата"} — пароль не нужен, вход всегда через ФСП ID.</Alert>
          {state.registration_role === "employer" && <Field label="Название компании" htmlFor="fsp-company"><input id="fsp-company" className="input" value={company} onChange={e => setCompany(e.target.value)} /></Field>}
          <div className="rounded-xl border border-brand-night/10 p-4">
            <p className="font-semibold text-brand-night">Что придёт в паспорт ФСП</p>
            {p?.has_history ? (
              <ul className="mt-2 space-y-1.5">
                {p.sport_rank && <li className="flex items-center gap-2"><Level level="T2" /> Спортивный разряд: {p.sport_rank}</li>}
                {p.achievements.map((a, i) => (
                  <li key={i} className="flex items-start gap-2"><Level level="T2" /><span>{a.event} — {a.result ?? (a.place ? `${a.place} место` : "участие")}, {LEVEL_RU[a.level] ?? a.level} уровень{a.date ? `, ${dateOnly(a.date)}` : ""}</span></li>
                ))}
              </ul>
            ) : <p className="mt-1 text-brand-ink/65">{NO_FSP}.</p>}
            <p className="mt-2 text-xs text-brand-ink/65">ФИО и контакты из ФСП ID в карточку не попадают; работодатель увидит их только после вашего согласия.</p>
          </div>
          {state.email_taken && <Alert kind="info">Аккаунт с почтой {p?.email} уже есть. Войдите паролем и свяжите ФСП ID в разделе «Паспорт ФСП».</Alert>}
          <Toggle checked={ok} onChange={setOk} label="Согласен на обработку персональных данных (152-ФЗ)" hint="Обязательно для создания кабинета" />
          {state.registration_role !== "employer" && <Toggle checked={pub} onChange={setPub} label="Показывать обезличенный профиль работодателям" hint="Можно изменить позже в настройках" />}
          <button className="btn-primary w-full" disabled={!ok || state.email_taken} onClick={complete}>Создать кабинет и войти</button>
        </div>
      )}
    </AuthShell>
  );
}
