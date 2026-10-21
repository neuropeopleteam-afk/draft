import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell, FormError } from "../components/AuthShell";
import { FspIdLogin } from "../integrations/FspId";
import { api, ApiError, isChallenge, type AuthResult } from "../lib/api";
import { cabinetPath, useAuth } from "../lib/auth";
import { challengePath } from "../lib/twofa";
import { juryLogin, type Persona } from "../lib/jury";
import { useDemoUi } from "../lib/juryMode";
import { usePageTitle } from "../lib/meta";
import { errText } from "../components/ui";

export default function Login() {
  usePageTitle("Вход в личный кабинет", "Войдите в кабинет работодателя, кандидата или партнёра ФСП на платформе «Драфт».");
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState<Persona | null>(null);
  const [emailTouched, setEmailTouched] = useState(false);
  const { signIn } = useAuth();
  const demoUi = useDemoUi();
  const showDemoButtons = demoUi || params.get("demo") === "1";
  const navigate = useNavigate();
  const fspLogin = !!email.trim() && !email.includes("@") && (emailTouched || /^fsp-/i.test(email.trim()));

  async function demo(p: Persona) {
    setDemoBusy(p); setError(null);
    try { navigate(await juryLogin(p, signIn)); }
    catch (e) { setError(errText(e)); } finally { setDemoBusy(null); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null); setUnverified(false); setBusy(true);
    try {
      const r = await api<AuthResult>("/auth/login", { auth: false, body: { email, password } });
      if (isChallenge(r)) { navigate(challengePath(r, cabinetPath(r.role))); return; }
      const me = await signIn(r.access_token);
      navigate(cabinetPath(me.role), { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_not_verified") setUnverified(true);
      setError(err instanceof ApiError ? err.message : "Не удалось связаться с сервером");
    } finally { setBusy(false); }
  }

  return (
    <AuthShell
      title="Вход"
      subtitle="Это страница входа в личный кабинет: введите почту и пароль или войдите через единый профиль ФСП — ваш рабочий кабинет откроется автоматически."
      lead={<>Нет аккаунта? <Link to="/register" className="font-semibold text-brand hover:text-brand-soft">Зарегистрироваться</Link></>}
      footer={<>Нет аккаунта? <Link to="/register" className="font-semibold text-brand hover:text-brand-soft">Зарегистрироваться</Link> · <Link to="/support" className="font-semibold text-brand-plum hover:underline">Поддержка</Link></>}
    >
      {showDemoButtons && (
        <>
          <div className="grid grid-cols-2 gap-2" data-testid="login-demo">
            {([["candidate", "Демо: кандидат"], ["employer", "Демо: работодатель"]] as const).map(([p, t]) => (
              <button key={p} type="button" className="btn-ghost px-3" disabled={!!demoBusy} onClick={() => demo(p)}>{demoBusy === p ? "Входим…" : t}</button>
            ))}
          </div>
          <div className="my-5 flex items-center gap-3 text-xs uppercase tracking-[0.14em] text-brand-ink/65"><span className="h-px flex-1 bg-brand-night/10" />или по почте<span className="h-px flex-1 bg-brand-night/10" /></div>
        </>
      )}
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div>
          <label className="label" htmlFor="email">Почта</label>
          <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} onBlur={() => setEmailTouched(true)}
            autoComplete="email" aria-describedby={fspLogin ? "email-fsp-hint" : undefined} />
          {fspLogin && <p id="email-fsp-hint" className="mt-1.5 text-sm text-brand-plum" data-testid="login-fsp-hint">Это логин ФСП ID — нажмите «Войти через ФСП ID»</p>}
        </div>
        <div>
          <div className="flex items-center justify-between gap-2">
            <label className="label !mb-0" htmlFor="password">Пароль</label>
            <Link
              to={email.trim() ? `/forgot?email=${encodeURIComponent(email.trim())}` : "/forgot"}
              className="text-xs font-semibold text-brand hover:text-brand-soft hover:underline"
              data-testid="login-forgot-link"
            >
              Забыли пароль?
            </Link>
          </div>
          <input id="password" type="password" className="input mt-1.5" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        <FormError message={error} />
        {unverified && (
          <Link to={`/verify?email=${encodeURIComponent(email)}`} className="btn-ghost w-full">Ввести код подтверждения</Link>
        )}
        <button type="submit" className="btn-primary w-full" disabled={busy || !email || !password}>{busy ? "Входим…" : "Войти"}</button>
      </form>
      <FspIdLogin />
    </AuthShell>
  );
}
