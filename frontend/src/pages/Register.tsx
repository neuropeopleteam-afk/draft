import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell, FormError } from "../components/AuthShell";
import { api, ApiError, type RegisterOut, type Role } from "../lib/api";
import { FspIdLogin } from "../integrations/FspId";

export default function Register() {
  const [params] = useSearchParams();
  const [role, setRole] = useState<Role>(params.get("role") === "employer" ? "employer" : "candidate");
  const [form, setForm] = useState({ email: "", password: "", full_name: "", company_name: "" });
  const [consent, setConsent] = useState(false);
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
      subtitle="Подтвердим почту кодом — это займёт минуту."
      footer={<>Уже есть аккаунт? <Link to="/login" className="font-semibold text-brand hover:text-brand-soft">Войти</Link></>}
    >
      <div className="mb-6 grid grid-cols-2 gap-1 rounded-xl bg-brand-blush/50 p-1" role="tablist" aria-label="Роль">
        {(["candidate", "employer"] as Role[]).map((r) => (
          <button key={r} type="button" role="tab" aria-selected={role === r} onClick={() => setRole(r)}
            className={`rounded-lg py-2.5 text-sm font-semibold transition-colors ${role === r ? "bg-white text-brand-night shadow-sm" : "text-brand-plum/70 hover:text-brand-plum"}`}>
            {r === "candidate" ? "Я кандидат" : "Я работодатель"}
          </button>
        ))}
      </div>
      <div className="mb-6"><FspIdLogin role={role === "employer" ? "employer" : "candidate"} /></div>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div>
          <label className="label" htmlFor="full_name">{role === "employer" ? "Ваше имя (контактное лицо)" : "Имя и фамилия"}</label>
          <input id="full_name" className="input" value={form.full_name} onChange={set("full_name")} autoComplete="name" placeholder="Анна Смирнова" />
        </div>
        {role === "employer" && (
          <div>
            <label className="label" htmlFor="company">Компания</label>
            <input id="company" className="input" value={form.company_name} onChange={set("company_name")} autoComplete="organization" placeholder="ООО «Пример»" />
          </div>
        )}
        <div>
          <label className="label" htmlFor="email">Почта</label>
          <input id="email" type="email" required className="input" value={form.email} onChange={set("email")} autoComplete="email" placeholder="name@example.ru" />
        </div>
        <div>
          <label className="label" htmlFor="password">Пароль</label>
          <input id="password" type="password" required minLength={8} className="input" value={form.password} onChange={set("password")} autoComplete="new-password" placeholder="Не менее 8 символов, буквы и цифры" />
        </div>
        <label className="flex items-start gap-3 text-sm text-brand-ink/75">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4 rounded accent-brand" />
          <span>Согласен на обработку персональных данных в соответствии с 152-ФЗ (<button type="button" className="font-semibold text-brand hover:underline" onClick={toggleLegal}>текст согласия</button>). Контакты работодатель увидит только после того, как я приму приглашение.</span>
        </label>
        {legal && <div className="max-h-56 overflow-y-auto rounded-xl bg-[#F3F2FB] p-4 text-xs leading-relaxed text-brand-ink/80"><p className="mb-2 font-semibold">{legal.title}</p><p className="whitespace-pre-line">{legal.text}</p></div>}
        <FormError message={error} />
        <button type="submit" className="btn-primary w-full" disabled={busy}>{busy ? "Отправляем…" : "Зарегистрироваться"}</button>
      </form>
    </AuthShell>
  );
}
