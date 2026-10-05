import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell, FormError } from "../components/AuthShell";
import { api, ApiError, type TokenOut } from "../lib/api";
import { cabinetPath, useAuth } from "../lib/auth";

export default function Verify() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [code, setCode] = useState("");
  const [devCode, setDevCode] = useState<string | null>(sessionStorage.getItem("fsp_dev_code"));
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { signIn } = useAuth();
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      const r = await api<TokenOut>("/auth/verify-email", { auth: false, body: { email, code } });
      sessionStorage.removeItem("fsp_dev_code");
      const me = await signIn(r.access_token);
      navigate(cabinetPath(me.role), { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось связаться с сервером");
    } finally { setBusy(false); }
  }

  async function resend() {
    setError(null); setInfo(null);
    try {
      const r = await api<{ sent: boolean; dev_verification_code: string | null }>("/auth/resend-code", { auth: false, body: { email } });
      if (r.dev_verification_code) { sessionStorage.setItem("fsp_dev_code", r.dev_verification_code); setDevCode(r.dev_verification_code); }
      setInfo("Если адрес зарегистрирован и не подтверждён, мы отправили новый код.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось связаться с сервером");
    }
  }

  return (
    <AuthShell
      title="Подтверждение почты"
      subtitle={email ? `Мы отправили 6-значный код на ${email}.` : "Введите почту и код из письма."}
      footer={<>Уже подтвердили? <Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Войти</Link></>}
    >
      {devCode && (
        <div className="mb-6 rounded-xl border border-dashed border-brand-lavender bg-brand-lavender/10 px-4 py-3 text-sm text-brand-night">
          <p className="font-semibold">Режим разработки</p>
          <p className="mt-1">Код продублирован на экране, пока подключается почтовая рассылка: <button type="button" className="font-mono text-base font-bold tracking-widest text-brand" onClick={() => setCode(devCode)}>{devCode}</button></p>
        </div>
      )}
      <form onSubmit={submit} className="space-y-4" noValidate>
        {!params.get("email") && (
          <div>
            <label className="label" htmlFor="email">Почта</label>
            <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </div>
        )}
        <div>
          <label className="label" htmlFor="code">Код из письма</label>
          <input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="input text-center font-mono text-2xl tracking-[0.5em]"
            value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="••••••" />
        </div>
        <FormError message={error} />
        {info && <p className="text-sm text-brand-ink/70">{info}</p>}
        <button type="submit" className="btn-primary w-full" disabled={busy || code.length !== 6 || !email}>{busy ? "Проверяем…" : "Подтвердить"}</button>
        <button type="button" onClick={resend} className="w-full text-sm font-semibold text-brand-plum hover:text-brand" disabled={!email}>Отправить код ещё раз</button>
      </form>
    </AuthShell>
  );
}
