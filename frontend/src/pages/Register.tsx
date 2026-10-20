import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell, FormError } from "../components/AuthShell";
import { api, ApiError, type RegisterOut, type Role } from "../lib/api";
import { FspIdMark } from "../integrations/FspId";
import { Alert, errText, useApi } from "../components/ui";

export default function Register() {
  const [params] = useSearchParams();
  const [role, setRole] = useState<Role>(params.get("role") === "employer" ? "employer" : "candidate");
  const [form, setForm] = useState({ email: "", password: "", full_name: "", company_name: "" });
  const [consent, setConsent] = useState(false);
  const [terms, setTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [legal, setLegal] = useState<{ title: string; text: string } | null>(null);
  const navigate = useNavigate();
  async function toggleLegal() {
    if (legal) { setLegal(null); return; }
    try { setLegal(await api<{ title: string; text: string }>("/legal/consents/processing", { auth: false })); } catch { setLegal(null); }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!terms) { setError("Нужно принять Пользовательское соглашение"); return; }
    if (!consent) { setError("Нужно согласие на обработку персональных данных"); return; }
    setBusy(true);
    try {
      const r = await api<RegisterOut>("/auth/register", {
        auth: false,
        body: {
          email: form.email, password: form.password, role, consent_processing: true,
          full_name: form.full_name || null, company_name: role === "employer" ? form.company_name || null : null,
        },
      });
      if (r.dev_verification_code) sessionStorage.setItem("fsp_dev_code", r.dev_verification_code);
      navigate(`/verify?email=${encodeURIComponent(r.email)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось связаться с сервером");
    } finally { setBusy(false); }
  }

  return (
    <AuthShell
      title="Регистрация"
      lead={<>Уже есть аккаунт? <Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Войти</Link></>}
    >
      {/* UX-2: жюри регистрироваться не нужно — одна строка со ссылкой на вход в один клик */}
      <p className="mb-6 rounded-xl bg-[#F3F2FB] px-4 py-3 text-sm text-brand-night" data-testid="register-jury-hint">
        Для проверки регистрироваться не нужно — <Link to="/" className="font-semibold text-brand hover:underline">на главной есть вход в один клик</Link>
      </p>
      <div className="mb-6 grid grid-cols-2 gap-1 rounded-xl bg-brand-blush/50 p-1" role="tablist" aria-label="Роль">
        {(["candidate", "employer"] as Role[]).map((r) => (
          <button key={r} type="button" role="tab" aria-selected={role === r} onClick={() => setRole(r)}
            className={`rounded-lg py-2.5 text-sm font-semibold transition-colors ${role === r ? "bg-white text-brand-night shadow-sm" : "text-brand-plum/70 hover:text-brand-plum"}`}>
            {r === "candidate" ? "Я кандидат" : "Я работодатель"}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="space-y-4" noValidate>
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
          <input id="password" type="password" required minLength={8} className="input" value={form.password} onChange={set("password")} autoComplete="new-password" placeholder="От 8 символов, буквы и цифры" />
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
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4 rounded accent-brand" />
          <span>Согласен на обработку персональных данных по 152-ФЗ (<button type="button" className="font-semibold text-brand hover:underline" onClick={toggleLegal}>текст согласия</button>).{role === "candidate" && " Контакты — работодателю только после моего согласия."}</span>
        </label>
        {legal && <div className="max-h-56 overflow-y-auto rounded-xl bg-[#F3F2FB] p-4 text-xs leading-relaxed text-brand-ink/80"><p className="mb-2 font-semibold">{legal.title}</p><p className="whitespace-pre-line">{legal.text}</p></div>}
        <FormError message={error} />
        <button type="submit" className="btn-primary w-full" disabled={busy}>{busy ? "Отправляем…" : "Зарегистрироваться"}</button>
      </form>
      <RegisterFspId role={role} />
    </AuthShell>
  );
}

interface FspConfig { enabled: boolean; demo_accounts: { username: string; title: string }[]; demo_password: string | null; note: string }

/** UX-2: ФСП ID на регистрации — кнопка и одна строка, демо-учётки свёрнуты. Свой блок: FspIdLogin («Вход») не меняем. */
function RegisterFspId({ role }: { role: Role }) {
  const { data } = useApi<FspConfig>("/fsp-id/config");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api<{ authorize_url: string }>("/fsp-id/start", { body: { intent: "login", registration_role: role === "employer" ? "employer" : "candidate" } });
      window.location.assign(r.authorize_url);
    } catch (e) { setErr(errText(e)); setBusy(false); }
  };
  return (
    <div className="mt-6 space-y-2">
      <div className="flex items-center gap-3 text-xs uppercase tracking-[0.14em] text-brand-ink/65"><span className="h-px flex-1 bg-brand-night/10" />или<span className="h-px flex-1 bg-brand-night/10" /></div>
      <button type="button" data-testid="button-fsp-login" className="btn-ghost w-full gap-2 !border-brand-plum/30 !bg-[#F3F2FB] !text-brand-night" disabled={busy || !data.enabled} onClick={go}>
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
}
