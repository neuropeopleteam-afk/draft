// Знак: два пересекающихся круга — работодатель и кандидат идут навстречу; общая зона — подтверждённые факты.
import { useProductName } from "../lib/meta";

export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" fill="none">
      <rect width="32" height="32" rx="8" fill="#310F53" />
      <circle cx="12.5" cy="16" r="7" stroke="#FFD6E4" strokeWidth="2.5" />
      <circle cx="19.5" cy="16" r="7" stroke="#FF0053" strokeWidth="2.5" />
    </svg>
  );
}

export function Logo({ light = false }: { light?: boolean }) {
  const name = useProductName();
  return (
    <span className="inline-flex items-center gap-2.5" aria-label={`${name} — на главную`}>
      <LogoMark />
      <span className={`min-w-[6rem] text-lg font-extrabold tracking-tight ${light ? "text-white" : "text-brand-night"}`}>{name}</span>
    </span>
  );
}
