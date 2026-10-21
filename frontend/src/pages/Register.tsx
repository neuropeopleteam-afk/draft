import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell, FormError, PasswordInput } from "../components/AuthShell";
import { Alert, errText, useApi } from "../components/ui";
import { FspIdMark } from "../integrations/FspId";
import { api, ApiError, type RegisterOut, type Role } from "../lib/api";
import { useAuth } from "../lib/auth";
import { juryLogin } from "../lib/jury";
import { useDemoAccess, useDemoUi } from "../lib/juryMode";
import { usePageTitle } from "../lib/meta";

const DEMO_PRESETS: Record<"candidate" | "employer", { email: string; password: string; full_name: string; company_name: string }> = {
  candidate: {
    email: "candidate.tour@draft-demo.ru",
    password: "DemoPassword2026",
    full_name: "Алексей Соколов",
    company_name: "",
  },
  employer: {
    email: "hr.tour@draft-demo.ru",
    password: "DemoPassword2026",
    full_name: "Мария Орлова",
    company_name: "ООО «Инженерный Контур»",
  },
};

function isDemoTourEmail(email: string): boolean {
  const clean = email.trim().toLowerCase();
  return (
    clean.endsWith("@draft-demo.ru") ||
    clean.endsWith("@jury.example.com") ||
    clean.endsWith("@tour.local")
  );
}

export default function Register({ demoPreview = false }: { demoPreview?: boolean }) {
  usePageTitle("Регистрация", "Создайте аккаунт работодателя или ИТ-специалиста на платформе подтверждённого найма «Драфт».");
  const demoUi = useDemoUi();
  const demoAccess = useDemoAccess();
  const { signIn } = useAuth();
  const [params, setParams] = useSearchParams();
  const initialRole: Role = params.get("role") === "employer" ? "employer" : "candidate";
  const isTourMode =
    demoAccess &&
    (demoPreview ||
      params.get("demo") === "1" ||
      params.get("tour") === "1" ||
      (typeof window !== "undefined" && Boolean((window as any).__fspRegisterDemoMode)));
  const shouldAutofill = isTourMode && params.get("autofill") !== "0";

  const [role, setRole] = useState<Role>(initialRole);
  const [form, setForm] = useState(() =>
    shouldAutofill
      ? DEMO_PRESETS[initialRole === "employer" ? "employer" : "candidate"]
      : { email: "", password: "", full_name: "", company_name: "" }
  );
  const [passwordConfirm, setPasswordConfirm] = useState(() =>
    shouldAutofill ? DEMO_PRESETS[initialRole === "employer" ? "employer" : "candidate"].password : ""
  );
  const [consent, setConsent] = useState(shouldAutofill);
  const [terms, setTerms] = useState(shouldAutofill);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [legal, setLegal] = useState<{ title: string; text: string } | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!shouldAutofill) return;
    const preset = DEMO_PRESETS[role === "employer" ? "employer" : "candidate"];
    setForm(preset);
    setPasswordConfirm(preset.password);
    setConsent(true);
    setTerms(true);
  }, [shouldAutofill, role]);

  async function toggleLegal() {
    if (legal) { setLegal(null); return; }
    try { setLegal(await api<{ title: string; text: string }>("/legal/consents/processing", { auth: false })); } catch { setLegal(null); }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function enterDemoRole(targetRole: "candidate" | "employer") {
    setError(null);
    setBusy(true);
    try {
      const dest = await juryLogin(targetRole, signIn, targetRole === "employer" ? "/employer" : "/candidate");
      navigate(dest, { replace: true });
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  const passwordMismatch = passwordConfirm.length > 0 && form.password !== passwordConfirm;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!terms) { setError("Нужно принять Пользовательское соглашение"); return; }
    if (!consent) { setError("Нужно согласие на обработку персональных данных"); return; }
    if (isTourMode || (demoAccess && isDemoTourEmail(form.email))) {
      await enterDemoRole(role === "employer" ? "employer" : "candidate");
      return;
    }
    if (form.password !== passwordConfirm) {
      setError("Пароли не совпадают");
      return;
    }
    setBusy(true);
    try {
      const r = await api<RegisterOut>("/auth/register", {
        auth: false,
        body: {
          email: form.email, password: form.password, role, consent_processing: true,
          full_name: form.full_name || null, company_name: role === "employer" ? form.company_name || null : null,
        },
      });
      if (r.dev_verification_code) {
        sessionStorage.setItem("fsp_dev_code", r.dev_verification_code);
      } else {
        sessionStorage.removeItem("fsp_dev_code");
      }
      navigate(`/verify?email=${encodeURIComponent(r.email)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось связаться с сервером");
    } finally { setBusy(false); }
  }

  return (
    <AuthShell
      title="Регистрация"
      subtitle={
        isTourMode
          ? "Это безопасный демонстрационный режим регистрации: проверьте шаги анкеты и нажмите кнопку отправки, чтобы сразу войти в готовый демо-кабинет без создания тестовой записи."
          : "Это страница создания учётной записи: выберите роль кандидата или работодателя, заполните анкету и подтвердите почту 6-значным кодом."
      }
      lead={<>Уже есть аккаунт? <Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Войти</Link></>}
    >
      {isTourMode ? (
        <div
          className="mb-6 rounded-xl border border-brand-plum/25 bg-[#F3F2FB] px-4 py-3 text-sm text-brand-night"
          data-testid="register-demo-preview"
          data-tour="register-demo-preview"
        >
          <p className="font-semibold">Режим демонстрации регистрации (экскурсия)</p>
          <p className="mt-1 text-xs leading-relaxed text-brand-ink/80">
            Демонстрация шагов регистрации и согласия 152-ФЗ без записи тестовых аккаунтов в БД — отправка формы сразу открывает готовый демо-кабинет выбранной роли.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              data-testid="register-demo-enter-candidate"
              data-tour="register-demo-candidate"
              onClick={() => void enterDemoRole("candidate")}
              className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white hover:bg-brand-deep"
            >
              Демо-вход: кандидат →
            </button>
            <button
              type="button"
              disabled={busy}
              data-testid="register-demo-enter-employer"
              data-tour="register-demo-employer"
              onClick={() => void enterDemoRole("employer")}
              className="rounded-lg border border-brand-night/20 bg-white px-3 py-1.5 text-xs font-semibold text-brand-night hover:bg-brand-blush/40"
            >
              Демо-вход: работодатель →
            </button>
            <button
              type="button"
              disabled={busy}
              data-testid="register-demo-exit-preview"
              onClick={() => {
                const next = new URLSearchParams(params);
                next.delete("demo");
                next.delete("tour");
                setParams(next, { replace: true });
                setForm({ email: "", password: "", full_name: "", company_name: "" });
                setPasswordConfirm("");
                setConsent(false);
                setTerms(false);
              }}
              className="rounded-lg px-2 py-1.5 text-xs font-medium text-brand-plum hover:underline"
            >
              Обычная форма
            </button>
          </div>
        </div>
      ) : demoUi ? (
        <div className="mb-6 rounded-xl bg-[#F3F2FB] px-4 py-3 text-sm text-brand-night" data-testid="register-jury-hint">
          <p>
            Для проверки регистрироваться не нужно —{" "}
            <Link to="/demo" className="font-semibold text-brand hover:underline">в разделе «Демо для жюри» есть вход в один клик</Link>.
          </p>
          <button
            type="button"
            data-testid="register-enable-demo-preview"
            onClick={() => {
              const next = new URLSearchParams(params);
              next.set("demo", "1");
              setParams(next, { replace: true });
            }}
            className="mt-1.5 text-xs font-semibold text-brand-plum hover:text-brand hover:underline"
          >
            Включить режим показа формы без записи в БД →
          </button>
        </div>
      ) : null}
      <div className="mb-6 grid grid-cols-2 gap-1 rounded-xl bg-brand-blush/50 p-1" role="tablist" aria-label="Роль" data-tour="register-role-tabs">
        {(["candidate", "employer"] as Role[]).map((r) => (
          <button key={r} type="button" role="tab" aria-selected={role === r} onClick={() => setRole(r)}
            data-testid={`register-tab-${r}`}
            className={`rounded-lg py-2.5 text-sm font-semibold transition-colors ${role === r ? "bg-white text-brand-night shadow-sm" : "text-brand-plum/70 hover:text-brand-plum"}`}>
            {r === "candidate" ? "Я кандидат" : "Я работодатель"}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="space-y-4" noValidate data-tour="register-form">
        {role === "employer" ? (
          <div>
            <label className="label" htmlFor="company">Компания</label>
            <input id="company" className="input" value={form.company_name} onChange={set("company_name")} autoComplete="organization" placeholder="ООО «Пример»" />
          </div>
        ) : (
          <div>
            <label className="label" htmlFor="full_name">Имя и фамилия</label>
            <input id="full_name" className="input" value={form.full_name} onChange={set("full_name")} autoComplete="name" placeholder="Анна Смирнова" />
          </div>
        )}
        <div>
          <label className="label" htmlFor="email">Почта</label>
          <input id="email" type="email" required className="input" value={form.email} onChange={set("email")} autoComplete="email" placeholder="name@example.ru" />
        </div>
        <div>
          <label className="label" htmlFor="password">Пароль</label>
          <PasswordInput id="password" required minLength={8} className="input" value={form.password} onChange={set("password")} autoComplete="new-password" placeholder="От 8 символов, буквы и цифры" />
        </div>
        <div>
          <label className="label" htmlFor="password_confirm">Повторите пароль</label>
          <PasswordInput
            id="password_confirm"
            required
            minLength={8}
            className="input"
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
            autoComplete="new-password"
            placeholder="Повторите пароль ещё раз"
            aria-invalid={passwordMismatch || undefined}
          />
          {passwordMismatch && (
            <p className="mt-1 text-xs font-semibold text-brand-plum" role="alert" data-testid="register-password-mismatch">
              Пароли не совпадают
            </p>
          )}
        </div>
        {/* UX-2: контактное лицо работодателя — необязательно, свёрнуто */}
        {role === "employer" && (
          <details className="text-sm">
            <summary className="cursor-pointer font-semibold text-brand-plum hover:text-brand">Контактное лицо — по желанию</summary>
            <div className="mt-3">
              <label className="label" htmlFor="full_name">Ваше имя</label>
              <input id="full_name" className="input" value={form.full_name} onChange={set("full_name")} autoComplete="name" placeholder="Анна Смирнова" />
            </div>
          </details>
        )}
        <label className="flex items-start gap-3 text-sm text-brand-ink/75">
          <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} className="mt-0.5 h-4 w-4 rounded accent-brand" data-testid="terms-checkbox" />
          <span>Принимаю <a href="/terms" target="_blank" rel="noopener" className="font-semibold text-brand hover:underline">Пользовательское соглашение</a> и ознакомлен с <a href="/privacy" target="_blank" rel="noopener" className="font-semibold text-brand hover:underline">Политикой обработки персональных данных</a>.</span>
        </label>
        <label className="flex items-start gap-3 text-sm text-brand-ink/75">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4 rounded accent-brand" data-testid="consent-checkbox" />
          <span>Согласен на обработку персональных данных по 152-ФЗ (<button type="button" className="font-semibold text-brand hover:underline" onClick={toggleLegal}>текст согласия</button>).{role === "candidate" && " Контакты — работодателю только после моего согласия."}</span>
        </label>
        {legal && <div className="max-h-56 overflow-y-auto rounded-xl bg-[#F3F2FB] p-4 text-xs leading-relaxed text-brand-ink/80"><p className="mb-2 font-semibold">{legal.title}</p><p className="whitespace-pre-line">{legal.text}</p></div>}
        <FormError message={error} />
        <button type="submit" className="btn-primary w-full" disabled={busy} data-testid="register-submit" data-tour="register-submit">
          {busy
            ? "Переходим…"
            : isTourMode
              ? `Продолжить в демо-кабинет (${role === "employer" ? "работодатель" : "кандидат"})`
              : "Зарегистрироваться"}
        </button>
      </form>
      <RegisterFspId role={role} showDemo={demoUi} isTourMode={isTourMode} onTourEnter={enterDemoRole} />
    </AuthShell>
  );
}

interface FspConfig { enabled: boolean; demo_accounts: { username: string; title: string }[]; demo_password: string | null; note: string }

function RegisterFspId({
  role,
  showDemo = false,
  isTourMode = false,
  onTourEnter,
}: {
  role: Role;
  showDemo?: boolean;
  isTourMode?: boolean;
  onTourEnter?: (r: "candidate" | "employer") => Promise<void>;
}) {
  const { data } = useApi<FspConfig>("/fsp-id/config");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const go = async () => {
    if (isTourMode && onTourEnter) {
      await onTourEnter(role === "employer" ? "employer" : "candidate");
      return;
    }
    setBusy(true); setErr(null);
    try {
      const r = await api<{ authorize_url: string }>("/fsp-id/start", { body: { intent: "login", registration_role: role === "employer" ? "employer" : "candidate" } });
      window.location.assign(r.authorize_url);
    } catch (e) { setErr(errText(e)); setBusy(false); }
  };
  return (
    <div className="mt-6 space-y-2">
      <div className="flex items-center gap-3 text-xs uppercase tracking-[0.14em] text-brand-ink/65"><span className="h-px flex-1 bg-brand-night/10" />или<span className="h-px flex-1 bg-brand-night/10" /></div>
      <button type="button" data-testid="button-fsp-login" className="btn-ghost w-full gap-2 !border-brand-plum/30 !bg-[#F3F2FB] !text-brand-night" disabled={busy || (!data.enabled && !isTourMode)} onClick={go}>
        <FspIdMark /> {busy ? "Переходим в ФСП ID…" : "Войти через ФСП ID"}
      </button>
      <p className="text-center text-xs text-brand-ink/70">{data.enabled || isTourMode ? (role === "candidate" ? "Без пароля, достижения ФСП — сразу в паспорт." : "Без пароля: кабинет компании создадим при первом входе.") : "ФСП ID на этом сервере ещё не подключён."}</p>
      <Alert>{err}</Alert>
      {showDemo && data.demo_accounts.length > 0 && (
        <details className="text-xs text-brand-night" data-testid="fsp-demo-accounts">
          <summary className="cursor-pointer text-center font-semibold text-brand-plum hover:text-brand">Демо-учётки ФСП ID</summary>
          <div className="mt-2 rounded-xl bg-[#F3F2FB] p-4 leading-relaxed">
            <ul className="space-y-1.5">
              {data.demo_accounts.map((a) => <li key={a.username}><code className="rounded bg-white px-1.5 py-0.5 font-semibold">{a.username}</code> — {a.title}</li>)}
            </ul>
            {data.demo_password && <p className="mt-2">Пароль для всех демо-учёток: <code className="rounded bg-white px-1.5 py-0.5 font-semibold">{data.demo_password}</code></p>}
            <p className="mt-2 font-semibold text-amber-900">Демо-стенд: учётные данные показаны здесь вместо письма. В рабочей системе вход идёт через ФСП ID.</p>
            <p className="mt-1 text-brand-ink/65">{data.note}</p>
          </div>
        </details>
      )}
    </div>
  );
}
