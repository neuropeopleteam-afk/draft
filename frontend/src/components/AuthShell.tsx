import type { ReactNode } from "react";
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
