// Общие помощники нестандартных решений 9 и 10: «Кубок работодателя» и «Кабинет ФСП».
import { useEffect, useState, type ReactNode } from "react";

export const PHASE: Record<string, [string, string]> = {
  upcoming: ["Скоро старт", "bg-[#ECEAF8] text-brand-night"],
  active: ["Идёт", "bg-brand text-white"],
  judging: ["Подведение итогов", "bg-brand-blush text-brand-plum"],
  finished: ["Завершён", "bg-emerald-50 text-emerald-700"],
  cancelled: ["Отменён", "bg-gray-100 text-gray-500"],
};
export const MODE_SHORT: Record<string, string> = { auto: "Автопроверка", rubric: "Рубрика", employer: "Оценка работодателя" };
export const ENTRY: Record<string, string> = {
  joined: "Записан", in_progress: "Решает", submitted: "На оценке", scored: "Оценено", expired: "Время вышло",
};

export function Phase({ p }: { p: string }) {
  const [t, c] = PHASE[p] ?? [p, "bg-gray-100 text-gray-600"];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${c}`}>{t}</span>;
}

/** Число людей с правилом K = 5: null — группа меньше пяти. */
export const kn = (v: number | null | undefined) => (v === null ? "< 5" : v === undefined ? "—" : v.toLocaleString("ru-RU"));
export const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)} %`);
export const mins = (s?: number | null) => (s ? `${Math.floor(s / 60)} мин ${String(s % 60).padStart(2, "0")} с` : "—");
export const thousand = (v?: number | null) => (v ? `${Math.round(v / 1000).toLocaleString("ru-RU")} тыс.` : "—");

export function Hidden({ children }: { children?: ReactNode }) {
  return <span title="Скрыто: группа меньше 5 человек" className="cursor-help text-brand-ink/40">{children ?? "< 5"}</span>;
}

export function Bar({ value, max, tone = "brand" }: { value: number | null | undefined; max: number; tone?: "brand" | "night" | "lavender" }) {
  const w = value && max > 0 ? Math.max(2, Math.round((100 * value) / max)) : 0;
  const c = tone === "night" ? "bg-brand-night" : tone === "lavender" ? "bg-brand-lavender" : "bg-brand";
  return (
    <div className="h-2 w-full rounded-full bg-brand-blush/50" aria-hidden>
      <div className={`h-2 rounded-full ${c}`} style={{ width: `${w}%` }} />
    </div>
  );
}

export function Countdown({ until, onEnd, endedText }: { until: string; onEnd?: () => void; endedText?: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const left = Math.max(0, Math.floor((new Date(until).getTime() - now) / 1000));
  useEffect(() => { if (left === 0) onEnd?.(); }, [left, onEnd]);
  const m = Math.floor(left / 60), s = left % 60;
  return (
    <span className="inline-flex flex-col items-end">
      <span role="timer" aria-label={`Осталось ${m} мин ${s} с`} className={`font-mono text-lg font-bold tabular-nums ${left < 120 ? "text-brand" : "text-brand-night"}`}>
        {String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
      </span>
      {left === 0 && endedText && <span className="text-xs font-semibold text-brand" role="status">{endedText}</span>}
    </span>
  );
}

export function CodeBlock({ code, numbered }: { code: string; numbered?: boolean }) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <pre className="mt-3 overflow-x-auto rounded-xl bg-brand-night p-4 text-xs leading-relaxed text-white">
      {lines.map((l, i) => (
        <div key={i} className="whitespace-pre">
          {numbered && <span className="mr-4 inline-block w-6 select-none text-right text-white/40">{i + 1}</span>}
          {l || " "}
        </div>
      ))}
    </pre>
  );
}
