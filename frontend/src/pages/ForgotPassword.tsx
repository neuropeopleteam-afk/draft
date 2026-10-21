import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell, FormError } from "../components/AuthShell";
import { Alert } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { usePageTitle } from "../lib/meta";

interface ForgotOut {
  sent: boolean;
  dev_reset_code?: string | null;
}

interface ResetOut {
  ok: boolean;
}

export function ForgotPassword() {
  usePageTitle("Восстановление пароля", "Запросите одноразовый код на почту для смены пароля на платформе «Драфт».");
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const r = await api<ForgotOut>("/auth/forgot", {
        auth: false,
        body: { email: email.trim() },
      });
      if (r.dev_reset_code) {
        sessionStorage.setItem("fsp_dev_reset_code", r.dev_reset_code);
      } else {
        sessionStorage.removeItem("fsp_dev_reset_code");
      }
      navigate(`/reset?email=${encodeURIComponent(email.trim())}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отправить запрос. Повторите попытку позже.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Восстановление пароля"
      subtitle="Это страница восстановления доступа: укажите почту своего аккаунта, чтобы получить 6-значный код для установки нового пароля."
      lead={<>Вспомнили пароль? <Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Войти</Link></>}
      footer={<><Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Вернуться ко входу</Link> · <Link to="/support" className="font-semibold text-brand-plum hover:underline">Помощь</Link></>}
    >
      <form onSubmit={submit} className="space-y-4" noValidate data-testid="forgot-form">
        <div>
          <label className="label" htmlFor="forgot-email">Почта</label>
          <input
            id="forgot-email"
            type="email"
            required
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="name@example.ru"
            autoFocus
          />
        </div>
        <FormError message={error} />
        <button type="submit" className="btn-primary w-full" disabled={busy || !email.trim()} data-testid="forgot-submit">
          {busy ? "Отправляем код…" : "Получить код для сброса"}
        </button>
      </form>
    </AuthShell>
  );
}

export function ResetPassword() {
  usePageTitle("Новый пароль", "Введите код из письма и задайте новый пароль для входа на платформе «Драфт».");
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [devCode, setDevCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const saved = sessionStorage.getItem("fsp_dev_reset_code");
    if (saved) {
      setDevCode(saved);
      setCode(saved);
    }
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api<ResetOut>("/auth/reset", {
        auth: false,
        body: {
          email: email.trim(),
          code: code.trim(),
          new_password: password,
        },
      });
      sessionStorage.removeItem("fsp_dev_reset_code");
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сменить пароль");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Новый пароль"
      subtitle="Это страница смены пароля: введите 6-значный код из письма и задайте новый пароль не короче 8 символов (буквы и цифры)."
      lead={<><Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Ко входу</Link></>}
      footer={<>Код не пришёл? <Link to={`/forgot?email=${encodeURIComponent(email)}`} className="font-semibold text-brand hover:text-brand-soft">Запросить повторно</Link></>}
    >
      {done ? (
        <div className="space-y-4" data-testid="reset-success">
          <Alert kind="ok">Пароль успешно обновлён. Все прежние сеансы завершены для безопасности.</Alert>
          <Link to="/login" className="btn-primary w-full justify-center">
            Войти с новым паролем
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate data-testid="reset-form">
          {devCode && (
            <Alert kind="info">
              Код показан для проверки, в рабочем режиме приходит письмом: <b className="font-mono">{devCode}</b>
            </Alert>
          )}
          <div>
            <label className="label" htmlFor="reset-email">Почта</label>
            <input
              id="reset-email"
              type="email"
              required
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </div>
          <div>
            <label className="label" htmlFor="reset-code">Код из письма (6 цифр)</label>
            <input
              id="reset-code"
              type="text"
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              required
              className="input font-mono text-lg tracking-[0.2em]"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="123456"
              autoComplete="one-time-code"
            />
          </div>
          <div>
            <label className="label" htmlFor="reset-password">Новый пароль</label>
            <input
              id="reset-password"
              type="password"
              minLength={8}
              required
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="От 8 символов, буквы и цифры"
            />
          </div>
          <FormError message={error} />
          <button
            type="submit"
            className="btn-primary w-full"
            disabled={busy || !email.trim() || code.length !== 6 || password.length < 8}
            data-testid="reset-submit"
          >
            {busy ? "Сохраняем…" : "Сохранить новый пароль"}
          </button>
        </form>
      )}
    </AuthShell>
  );
}

export default ForgotPassword;
