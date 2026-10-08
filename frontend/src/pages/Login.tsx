import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthShell, FormError } from "../components/AuthShell";
import { FspIdLogin } from "../integrations/FspId";
import { api, ApiError, isChallenge, type AuthResult } from "../lib/api";
import { cabinetPath, useAuth } from "../lib/auth";
import { challengePath } from "../lib/twofa";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [busy, setBusy] = useState(false);
  const { signIn } = useAuth();
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null); setUnverified(false); setBusy(true);
    try {
      const r = await api<AuthResult>("/auth/login", { auth: false, body: { email, password } });
      // второй фактор: пароль принят, код — на отдельном экране (или обязательное подключение для admin/fsp_analyst)
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
      subtitle="Кабинет кандидата или работодателя откроется автоматически."
      footer={<>Нет аккаунта? <Link to="/register" className="font-semibold text-brand hover:text-brand-soft">Зарегистрироваться</Link></>}
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div>
          <label className="label" htmlFor="email">Почта</label>
          <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </div>
        <div>
          <label className="label" htmlFor="password">Пароль</label>
          <input id="password" type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        <FormError message={error} />
        {unverified && (
          <Link to={`/verify?email=${encodeURIComponent(email)}`} className="btn-ghost w-full">Ввести код подтверждения</Link>
        )}
        <button type="submit" className="btn-primary w-full" disabled={busy || !email || !password}>{busy ? "Входим…" : "Войти"}</button>
      </form>
      <FspIdLogin />
      <p className="mt-5 rounded-lg bg-brand-blush/40 px-3 py-2 text-xs leading-relaxed text-brand-ink/80">
        Эксперту жюри: готовые учётки — вход в один клик на <Link to="/#jury" className="font-semibold text-brand hover:text-brand-soft">главной</Link>.
        Доступ к стенду: demo / ***.
      </p>
    </AuthShell>
  );
}
