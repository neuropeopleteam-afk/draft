// Кандидат: интересы для взаимного подбора (Н9) и «почему меня выбрали» в приглашении.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Loading, Toggle, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { FitBadge, FitFactors, type Fit } from "./shared";

interface PrefsData {
  preferences: { offers_status: string | null; interest_tags: string[]; interest_tasks: string[]; salary_signal: boolean } | null;
  survey_stack: string[]; options: { offers: Record<string, string>; tasks: Record<string, string> }; note: string;
}
interface Tag { id: string; title: string }

/** Интересы: готовность к предложениям, стек, задачи, сигнал по вилке. Сохраняется сразу после изменения. */
export function MutualPrefs({ compact = false, suggest = [] }: { compact?: boolean; suggest?: string[] }) {
  const d = useApi<PrefsData>("/candidate/preferences");
  const tags = useApi<Tag[]>("/catalog/stack-tags");
  const [st, setSt] = useState<string | null>(null);
  const [mine, setMine] = useState<string[]>([]);
  const [tasks, setTasks] = useState<string[]>([]);
  const [signal, setSignal] = useState(true);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const loaded = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    if (!d.data || loaded.current) return;
    const p = d.data.preferences;
    setSt(p?.offers_status ?? null); setMine(p?.interest_tags ?? []); setTasks(p?.interest_tasks ?? []); setSignal(p?.salary_signal ?? true);
    loaded.current = true;
  }, [d.data]);
  function save(next: { offers_status: string | null; interest_tags: string[]; interest_tasks: string[]; salary_signal: boolean }) {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api("/candidate/preferences", { method: "PUT", body: next })
        .then(() => setMsg({ k: "ok", t: "Интересы сохранены" })).catch((e) => setMsg({ k: "error", t: errText(e) }));
    }, 500);
  }
  const cur = { offers_status: st, interest_tags: mine, interest_tasks: tasks, salary_signal: signal };
  const upd = (patch: Partial<typeof cur>) => {
    const n = { ...cur, ...patch };
    setSt(n.offers_status); setMine(n.interest_tags); setTasks(n.interest_tasks); setSignal(n.salary_signal); save(n);
  };
  if (d.loading && !d.data) return <Loading />;
  if (!d.data) return <Alert>{d.error}</Alert>;
  const title = Object.fromEntries((tags.data ?? []).map((t) => [t.id, t.title]));
  const pool = [...new Set([...mine, ...suggest, ...d.data.survey_stack])];
  const chip = (on: boolean) => `rounded-full border px-3 py-1.5 text-sm ${on ? "border-brand bg-brand-blush/40 font-semibold" : "border-brand-night/15"}`;
  const H = compact ? "p" : "h2";
  return (
    <div className={compact ? "space-y-4 rounded-xl border border-brand-night/10 p-4" : "card space-y-4"}>
      <div>
        <H className={compact ? "label !mb-0" : "font-bold text-brand-night"}>Что вам интересно (взаимный подбор)</H>
        <p className="mt-1 text-xs text-brand-ink/65">{d.data.note}</p>
      </div>
      <div>
        <p className="label">Готовность к предложениям</p>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Готовность к предложениям">
          {Object.entries(d.data.options.offers).map(([id, t]) => (
            <button key={id} type="button" role="radio" aria-checked={st === id} className={chip(st === id)} onClick={() => upd({ offers_status: st === id ? null : id })}>{t}</button>
          ))}
        </div>
      </div>
      <div>
        <p className="label">Интересные задачи</p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(d.data.options.tasks).map(([id, t]) => (
            <button key={id} type="button" aria-pressed={tasks.includes(id)} className={chip(tasks.includes(id))}
              onClick={() => upd({ interest_tasks: tasks.includes(id) ? tasks.filter((x) => x !== id) : [...tasks, id] })}>{t}</button>
          ))}
        </div>
      </div>
      <div>
        <p className="label">С чем хочется работать</p>
        <div className="flex flex-wrap gap-2">
          {pool.map((id) => (
            <button key={id} type="button" aria-pressed={mine.includes(id)} className={chip(mine.includes(id))}
              onClick={() => upd({ interest_tags: mine.includes(id) ? mine.filter((x) => x !== id) : [...mine, id].slice(0, 20) })}>{title[id] ?? id}</button>
          ))}
          <select className="input !w-auto max-w-full !py-1.5 text-sm" aria-label="Добавить технологию" value=""
            onChange={(e) => e.target.value && upd({ interest_tags: [...new Set([...mine, e.target.value])].slice(0, 20) })}>
            <option value="">Добавить технологию…</option>
            {(tags.data ?? []).filter((t) => !pool.includes(t.id)).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
        </div>
        <p className="mt-1 text-xs text-brand-ink/65">{mine.length ? `Отмечено: ${mine.length}.` : "Не отмечено — работодатель видит совпадение со стеком из опроса."}</p>
      </div>
      <Toggle checked={signal} onChange={(v) => upd({ salary_signal: v })} label="Сообщать работодателю, если вилка ниже моих ожиданий"
        hint="Только «в ожиданиях / ниже ожиданий» — сам минимум не показывается. Если выключить, работодатель увидит «не сообщает»." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
    </div>
  );
}

interface WhyData {
  need: { title: string; category: string | null } | null;
  place: { version: number; rank: number; total: number } | null;
  matched: { requirement: string; level: string; status: string; text: string }[];
  counts: { confirmed?: number; declared?: number; missing?: number };
  to_confirm: string[]; offer: Fit;
}
const GROUPS: [string, string, (s: string, l: string) => boolean][] = [
  ["Подтверждено", "тестом, заданиями или ФСП", (s, l) => (s === "confirmed" || s === "partial") && (l === "T1" || l === "T2")],
  ["Заявлено вами", "можно подтвердить — тогда это войдёт в подбор", (s) => s === "declared"],
  ["Не хватило", "в профиле нет данных", (s) => s === "missing"],
];

/** «Почему вас выбрали»: требования потребности с уровнем доказанности, место в подборке, совпадение условий. */
export function WhyChosen({ invitationId }: { invitationId: string }) {
  const d = useApi<WhyData>(`/candidate/invitations/${invitationId}/why`, [invitationId]);
  if (d.loading && !d.data) return null;
  if (!d.data) return null;
  const w = d.data;
  return (
    <section className="space-y-3 rounded-xl border border-brand-night/10 p-4" aria-label="Почему вас выбрали">
      <h3 className="font-bold text-brand-night">Почему вас выбрали</h3>
      {w.need && <p className="text-sm text-brand-ink/80">Потребность «{w.need.title}»{w.need.category ? ` (${w.need.category})` : ""}{w.place ? `: ${w.place.rank}-е место из ${w.place.total} в подборке v${w.place.version}` : ""}. Порядок подборки — только по подтверждённым фактам.</p>}
      {GROUPS.map(([t, hint, f]) => {
        const items = w.matched.filter((x) => f(x.status, x.level));
        return items.length ? (
          <div key={t}>
            <p className="text-sm font-semibold text-brand-night">{t} <span className="font-normal text-brand-ink/65">— {hint}</span></p>
            <ul className="mt-1 space-y-0.5 text-sm text-brand-ink/80">{items.map((x) => <li key={x.requirement}>{x.requirement.replace(/^(Обязательно|Желательно): /, "")}{x.requirement.startsWith("Желательно") ? " (желательно)" : ""}: <span className="text-brand-ink/65">{x.text}</span></li>)}</ul>
          </div>
        ) : null;
      })}
      {!!w.to_confirm.length && <p className="text-sm">Подтвердите {w.to_confirm.join(", ")} — <Link className="font-semibold text-brand hover:underline" to="/candidate/assignments">задания для вас</Link> или задание работодателя: подтверждённое поднимает место в подборках.</p>}
      <div className="space-y-2 border-t border-brand-night/5 pt-3">
        <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-semibold text-brand-night">Условия предложения и ваши ожидания</p><FitBadge fit={w.offer} /></div>
        <FitFactors factors={w.offer.factors} />
        <p className="text-xs text-brand-ink/65">Работодатель видит только итог и строку объяснения; сумма вашего минимума не показывается. <Link className="font-semibold text-brand hover:underline" to="/candidate/settings">Изменить интересы</Link></p>
      </div>
    </section>
  );
}
