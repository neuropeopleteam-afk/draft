// Подписка на потребность (И25): «следить за новыми подходящими», частота, список новых, отметка «новый» в подборке.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Seg, Toggle, dtt, errText, num, useApi } from "../../components/ui";
import { api } from "../../lib/api";

export interface SubOut {
  need_id: string; exists: boolean; enabled: boolean; frequency: "instant" | "daily" | "weekly"; frequency_title?: string;
  top_n: number; new_count: number; new_refs: string[]; in_top: number; computed_at: string | null; baseline_at: string | null;
  new: { ref: string; rank: number; score: number; card?: any; entered_at: string }[];
  frequencies: { id: string; title: string }[];
}

const FREQ_SHORT: Record<string, string> = { instant: "Сразу", daily: "Раз в день", weekly: "Раз в неделю" };

export function useSub(needId?: string) {
  const r = useApi<SubOut>(needId ? `/employer/needs/${needId}/subscription` : null);
  // песочница жюри: «смоделировать нового кандидата» обновляет подписку без перезагрузки страницы
  const reload = r.reload;
  useWindowEvent("subs:changed", () => { void reload(); });
  return r;
}

function useWindowEvent(name: string, fn: () => void) {
  useEffect(() => { window.addEventListener(name, fn); return () => window.removeEventListener(name, fn); });
}

/** Чип «новый» у карточки кандидата в подборке. */
export function NewChip() {
  return <span className="inline-flex items-center rounded-full bg-brand px-2.5 py-0.5 text-xs font-bold text-white" title="Вошёл в топ-10 после того, как вы подписались">новый</span>;
}

export function SubscriptionPanel({ needId, sub, versionNo, onNewVersion }: { needId: string; sub: ReturnType<typeof useSub>; versionNo?: number; onNewVersion?: (v: number) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const s = sub.data;
  const base = `/employer/needs/${needId}/subscription`;
  async function call(path: string, method: string, body?: unknown) {
    setErr(null); setBusy(true);
    try { sub.setData(await api<SubOut>(path, { method, body })); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function newVersion() {
    setErr(null); setBusy(true);
    try { const r = await api<{ version: number }>(`${base}/new-version`, { method: "POST", body: {} }); onNewVersion?.(r.version); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  if (!s) return sub.error ? <Alert>{sub.error}</Alert> : null;
  return (
    <section className="card space-y-3" aria-label="Слежение за потребностью">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-bold text-brand-night">Следить за новыми подходящими{s.enabled && s.new_count > 0 ? ` · новых: ${s.new_count}` : ""}</h2>
          <p className="mt-0.5 text-xs text-brand-ink/65">
            Потребность остаётся активной: когда новый подтверждённый кандидат попадёт в топ-{s.top_n} подборки (после теста, смены грейда или нового навыка), мы сообщим. Кто в топе сейчас, новым не считается.
          </p>
        </div>
        <div className="w-full sm:w-auto sm:min-w-[16rem]">
          <Toggle checked={s.enabled} onChange={(v) => call(base, "PUT", { enabled: v, frequency: s.frequency })} label={s.enabled ? "Слежу" : "Не слежу"} />
        </div>
      </div>
      {s.enabled && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Seg value={s.frequency} label="Как сообщать" onChange={(f) => call(base, "PUT", { enabled: true, frequency: f })}
              options={s.frequencies.map((f) => ({ id: f.id as SubOut["frequency"], title: FREQ_SHORT[f.id] ?? f.title }))} />
            <p className="text-xs text-brand-ink/65">{s.frequencies.find((f) => f.id === s.frequency)?.title}. Письма и push можно выключить в разделе <Link className="font-semibold text-brand hover:underline" to="/employer/notifications">«Уведомления»</Link>.</p>
          </div>
          <p className="text-xs text-brand-ink/65">
            Условия слежения — последняя версия подборки{versionNo ? ` (v${versionNo})` : ""}: изменили условия — база сравнения обновится без уведомлений.
            {" "}Проверено: {s.computed_at ? dtt(s.computed_at) : "ещё не проверялось"} · в топе: {s.in_top}.
          </p>
          <Alert>{err}</Alert>
          {s.new_count > 0 ? (
            <div className="rounded-xl border border-brand/30 bg-brand-blush/30 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-bold text-brand-night">Новые подходящие: {s.new_count}</p>
                <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <button type="button" className="text-sm font-semibold text-brand hover:underline" disabled={busy} onClick={newVersion}>Обновить подборку (новая версия)</button>
                  <button type="button" className="text-sm font-semibold text-brand hover:underline" disabled={busy} onClick={() => call(`${base}/seen`, "POST", { refs: null })}>Отметить просмотренными</button>
                </span>
              </div>
              <ul className="mt-2 space-y-1.5">
                {s.new.map((n) => (
                  <li key={n.ref} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <NewChip />
                    <Link className="font-semibold text-brand-night hover:underline" to={`/employer/candidates/${n.ref}?need=${needId}`}>{n.ref}</Link>
                    <span className="text-brand-ink/75">{n.card?.category?.title ?? "категория"}</span>
                    <span className="text-brand-ink/65">соответствие {num(n.score * 100, 0)} из 100 · место {n.rank} в топе</span>
                    <span className="text-xs text-brand-ink/50">{dtt(n.entered_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : <p className="text-sm text-brand-ink/65">Новых подходящих пока нет.</p>}
          <button type="button" className="btn-ghost" disabled={busy} onClick={() => call(`${base}/check`, "POST")}>{busy ? "Проверяем…" : "Проверить сейчас"}</button>
        </>
      )}
    </section>
  );
}
