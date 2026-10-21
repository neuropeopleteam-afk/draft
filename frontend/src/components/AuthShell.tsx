import { useState, type InputHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Logo } from "./Logo";

export function AuthShell({ title, subtitle, lead, children, footer }: { title: string; subtitle?: string; lead?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[0.9fr_1.1fr]">
      <aside className="relative hidden overflow-hidden bg-brand-night p-12 text-white lg:flex lg:flex-col lg:justify-between" style={{ background: "radial-gradient(120% 90% at 85% 15%, rgba(64, 47, 255, 0.45) 0%, transparent 55%), radial-gradient(80% 80% at 15% 90%, rgba(236, 29, 53, 0.22) 0%, transparent 55%), linear-gradient(160deg, #0B0D1E 0%, #121636 60%, #0B0D1E 100%)" }}>
        <div className="pointer-events-none absolute -left-32 bottom-0 h-96 w-96 rounded-full bg-brand/30 blur-3xl" />
        <Link to="/" className="relative"><Logo light /></Link>
        <div className="relative max-w-sm">
          <p className="text-3xl font-extrabold leading-tight">Категория по тесту, а не по резюме.</p>
          <p className="mt-4 text-white/70">Работодатель видит подтверждённые факты и приходит с конкретной зарплатой. Контакты — только с вашего согласия.</p>
        </div>
        <p className="relative text-sm text-white/50">Платформа подтверждённого ИТ-найма · команда Neuropeople</p>
      </aside>
      <main id="main" className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <Link to="/" className="mb-10 inline-block lg:hidden"><Logo /></Link>
          <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">{title}</h1>
          {subtitle && <p className="mt-2 text-sm leading-relaxed text-brand-ink/75" data-testid="auth-subtitle">{subtitle}</p>}
          {/* UX-2: «Уже есть аккаунт? Войти» / «Нет аккаунта? Зарегистрироваться» */}
          {lead && <p className="mt-2 text-sm text-brand-ink/70" data-testid="auth-lead">{lead}</p>}
          <div className="mt-8">{children}</div>
          {footer && <div className="mt-8 text-sm text-brand-ink/70">{footer}</div>}
        </div>
      </main>
    </div>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return <p role="alert" className="rounded-xl bg-brand-blush/60 px-4 py-3 text-sm font-medium text-brand-plum">{message}</p>;
}

/** Поле пароля с кнопкой «Показать / Скрыть пароль» (глаз). */
export function PasswordInput({
  className = "input",
  toggleTestId,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { toggleTestId?: string }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input
        {...props}
        type={visible ? "text" : "password"}
        className={`${className} pr-11`}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Скрыть пароль" : "Показать пароль"}
        aria-pressed={visible}
        title={visible ? "Скрыть пароль" : "Показать пароль"}
        data-testid={toggleTestId ?? (props.id ? `${props.id}-toggle-visibility` : "password-toggle-visibility")}
        className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex h-8 w-8 items-center justify-center rounded-lg text-brand-ink/55 transition hover:bg-brand-blush/50 hover:text-brand-night"
      >
        {visible ? (
          <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
            <path d="M3 3l18 18M10.6 10.6a2 2 0 002.8 2.8M9.9 5.1A10.4 10.4 0 0112 5c5.2 0 9.3 3.9 10.5 7-.5 1.4-1.5 3-2.9 4.3M6.5 6.5C4.5 7.9 3.1 9.8 2.5 12c1.2 3.1 5.3 7 10.5 7 1.8 0 3.5-.5 5-1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
            <path d="M2.5 12C3.7 8.9 7.8 5 13 5s9.3 3.9 10.5 7c-1.2 3.1-5.3 7-10.5 7S3.7 15.1 2.5 12z" strokeLinejoin="round" />
            <circle cx="13" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}
