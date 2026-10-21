// Знак: два пересекающихся круга — работодатель и кандидат идут навстречу; общая зона — подтверждённые факты.
import { useProductName } from "../lib/meta";

export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" fill="none">
      <rect width="32" height="32" rx="9" fill="#0F132E" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="8.5" stroke="#5E52FF" strokeOpacity="0.45" />
      <circle cx="12.5" cy="16" r="6.8" stroke="#6355FF" strokeWidth="2.6" />
      <circle cx="19.5" cy="16" r="6.8" stroke="#FF3B56" strokeWidth="2.6" />
      <circle cx="16" cy="12.2" r="1.4" fill="#EDEDED" />
      <circle cx="16" cy="19.8" r="1.4" fill="#EDEDED" />
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
