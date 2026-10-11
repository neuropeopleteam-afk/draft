import { Link } from "react-router-dom";
import { dt, num, signed } from "./ui";

/** Подтверждение относится к направлению, а не ко всему профилю. */
// showTheta — θ на виду (кабинет кандидата); у работодателя θ только в подсказке (SIMPLIFY п.5)
export function Specializations({ items, testing = false, showTheta = testing }: { items?: any[]; testing?: boolean; showTheta?: boolean }) {
  if (!items?.length) return null;
  return (
    <div className="grid min-w-0 gap-3 sm:grid-cols-2" aria-label="Специализации кандидата">
      {items.map((s) => (
        <div key={s.direction} className="min-w-0 rounded-xl border border-brand-night/10 bg-white p-3 text-sm">
          <p className="text-xs font-semibold text-brand-lavender">{s.is_primary ? "Основное направление" : "Дополнительное направление"}</p>
          <p className="mt-1 font-bold text-brand-night">{s.category_title ?? s.direction_title}</p>
          <p className="mt-1 text-brand-ink/75" title={!showTheta && s.theta != null ? `Оценка уровня по шкале теста: θ = ${signed(s.theta)} ± ${num(s.se)}` : undefined}>
            {s.confirmed_by === "test" ? "Подтверждено отдельным тестом · T1"
              : s.status === "provisional" ? "Предварительная категория" : "Ожидает подтверждения тестом"}
          </p>
          {showTheta && s.theta != null && <p className="mt-1 text-xs text-brand-ink/65">θ = {signed(s.theta)} ± {num(s.se)}</p>}
          {testing && (
            <div className="mt-3 space-y-2">
              <p className="text-xs text-brand-ink/65">{s.lock_active ? `Смена грейда — с ${dt(s.locked_until)}` : "Тест в этом направлении доступен"}</p>
              <Link className="btn-ghost !px-3 !py-1.5 text-xs" to={`/candidate/assessment?direction=${s.direction}&grade=${s.grade ?? "junior"}`}>
                {s.active_session_id ? "Продолжить тест" : "Выбрать грейд и пройти тест"}
              </Link>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
