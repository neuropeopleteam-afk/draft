// Знак: два пересекающихся круга — работодатель и кандидат идут навстречу; общая зона — подтверждённые факты.
import { useProductName } from "../lib/meta";

export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" fill="none">
      <defs>
        <linearGradient id="fsp-logo-bg" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#191E42" />
          <stop offset="100%" stopColor="#0B0D1E" />
        </linearGradient>
        <linearGradient id="fsp-logo-indigo" x1="5" y1="8" x2="21" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#7C70FF" />
          <stop offset="100%" stopColor="#402FFF" />
        </linearGradient>
        <linearGradient id="fsp-logo-red" x1="12" y1="8" x2="27" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FF5468" />
          <stop offset="100%" stopColor="#EC1D35" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#fsp-logo-bg)" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="8.5" stroke="rgba(165,157,255,0.28)" />
      <circle cx="12.5" cy="16" r="6.8" stroke="url(#fsp-logo-indigo)" strokeWidth="2.5" />
      <circle cx="19.5" cy="16" r="6.8" stroke="url(#fsp-logo-red)" strokeWidth="2.5" />
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
