// И27: быстрый разбор потребности. Карточка рисуется из словаря сразу, модель уточняет разбор в фоне
// (POST /employer/needs/parse → parse_job, опрос GET /employer/needs/parse/{id}). Пока работодатель ничего не
// правил, итог модели заменяет карточку целиком; после подтверждения или правки — только предложения
// «модель предлагает: …» с «Принять» / «Отклонить», молча ничего не перезаписывается.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { DIRECTIONS, GRADES, num } from "../../components/ui";
import type { Ev } from "../../components/Quotes";
import type { Req, StackItem } from "./Needs";

export interface DeltaItem {
  id: string; kind: "add_tag" | "set_scalar" | "confirm_tag" | "suggest_scalar" | "remove_tag"; auto: boolean;
  zone?: "required" | "desired" | null; tag?: string; name?: string; weight?: number; evidence?: (Ev & { confirmed_by?: string }) | null;
  field?: "direction" | "grade" | "experience_years_min" | "work_format"; value?: any; current?: any; reason?: string; by?: string;
}
type Phase = "idle" | "pending" | "done" | "cached" | "failed" | "off";
interface State { phase: Phase; llm?: any; applied: DeltaItem[]; offers: DeltaItem[]; waited?: number; edited?: boolean }

const POLL_MS = 700, POLL_MAX_MS = 60000;
const FORMAT: Record<string, string> = { office: "офис", hybrid: "гибрид", remote: "удалённо" };
const FIELD: Record<string, string> = { direction: "направление", grade: "грейд", experience_years_min: "опыт", work_format: "формат" };

/** Подпись происхождения цитаты: словарь, словарь + подтверждено моделью, модель. */
export function evSource(ev: Ev & { confirmed_by?: string }): string {
  if (ev.source === "llm") return `${ev.model ?? "модель"}, цитата найдена в тексте`;
  const base = ev.basis === "stack" ? "по технологиям" : ev.basis === "experience" ? "по опыту" : "словарь";
  return ev.confirmed_by ? `${base} · подтверждено: ${ev.confirmed_by}` : base;
}

function valueText(field: string | undefined, v: any): string {
  if (v == null) return "не указано";
  if (field === "direction") return DIRECTIONS[v] ?? v;
  if (field === "grade") return GRADES[v] ?? v;
  if (field === "experience_years_min") return `от ${num(v)} лет`;
  if (field === "work_format") return FORMAT[v] ?? v;
  return String(v);
}

export function deltaText(d: DeltaItem): string {
  if (d.kind === "add_tag") return `${d.zone === "desired" ? "желательно" : "обязательно"}: ${d.name ?? d.tag}`;
  if (d.kind === "remove_tag") return `убрать «${d.name ?? d.tag}»${d.reason ? ` — ${d.reason}` : ""}`;
  if (d.kind === "set_scalar") return `${FIELD[d.field!]}: ${valueText(d.field, d.value)}`;
  if (d.kind === "suggest_scalar") return `${FIELD[d.field!]}: ${valueText(d.field, d.value)} вместо «${valueText(d.field, d.current)}»`;
  return `подтверждено: ${d.name ?? d.tag}`;
}

const zoneKey = (z?: string | null) => (z === "desired" ? "stack_desired" : "stack_required") as "stack_required" | "stack_desired";

/** Применить одно изменение модели к требованиям (по «Принять» или само, пока карточку не правили). */
export function applyDelta(req: Req, d: DeltaItem): Req {
  const all = [...req.stack_required, ...req.stack_desired];
  if (d.kind === "add_tag") {
    if (!d.tag || all.some((x) => x.tag === d.tag)) return req;
    const item: StackItem = { tag: d.tag, weight: d.weight ?? (d.zone === "desired" ? 0.3 : 0.8), evidence: d.evidence ?? null, status: "extracted" };
    return { ...req, [zoneKey(d.zone)]: [...req[zoneKey(d.zone)], item] } as Req;
  }
  if (d.kind === "remove_tag") {
    return { ...req, stack_required: req.stack_required.filter((x) => x.tag !== d.tag), stack_desired: req.stack_desired.filter((x) => x.tag !== d.tag) };
  }
  if (d.kind === "confirm_tag") {
    const mark = (x: StackItem) => (x.tag === d.tag && x.evidence ? { ...x, evidence: { ...x.evidence, confirmed_by: d.by ?? (x.evidence as any).confirmed_by } } : x);
    return { ...req, stack_required: req.stack_required.map(mark), stack_desired: req.stack_desired.map(mark) };
  }
  if (d.field) {
    const review = { ...(req.review ?? {}) }; delete review[d.field];
    const extra = d.field === "work_format" ? { work_formats: null } : {};
    return { ...req, ...extra, [d.field]: d.value, evidence: { ...(req.evidence ?? {}), [d.field]: d.evidence ?? null }, review } as Req;
  }
  return req;
}

/** Состояние фонового уточнения; touch() — работодатель правил карточку (дальше — только предложения). */
export function useFastParse(setReq: (f: (r: Req | null) => Req | null) => void) {
  const [st, setSt] = useState<State>({ phase: "idle", applied: [], offers: [] });
  const cur = useRef(st); cur.current = st;
  const gen = useRef(0);
  const dirty = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const stop = () => { if (timer.current) window.clearTimeout(timer.current); timer.current = undefined; };
  useEffect(() => stop, []);

  const finish = useCallback((g: number, res: any, delta: DeltaItem[], llm: any, phase: Phase) => {
    if (g !== gen.current) return;
    const offers = delta.filter((d) => d.kind !== "confirm_tag" && (!d.auto || dirty.current));
    const applied = delta.filter((d) => d.auto && (d.kind === "confirm_tag" || !dirty.current));
    if (!dirty.current) setReq(() => ({ ...res, llm }));
    else setReq((r) => (r ? delta.filter((d) => d.kind === "confirm_tag").reduce(applyDelta, r) : r));
    setSt({ phase, llm, applied, offers, edited: dirty.current });
  }, [setReq]);

  const start = useCallback((r: any) => {
    stop(); const g = ++gen.current; dirty.current = false;
    const job = r?.parse_job;
    if (job?.status === "done" && r.llm?.cached) {
      const delta: DeltaItem[] = r.delta ?? [];
      setSt({ phase: "cached", llm: r.llm, applied: delta.filter((d) => d.auto), offers: delta.filter((d) => !d.auto) });
      return;
    }
    if (!job || job.status !== "pending") {
      setSt({ phase: r?.llm?.reason && r.llm.reason !== "not_configured" ? "failed" : "off", llm: r?.llm, applied: [], offers: [] });
      return;
    }
    setSt({ phase: "pending", applied: [], offers: [], waited: 0 });
    const t0 = Date.now();
    const tick = async () => {
      if (g !== gen.current) return;
      try {
        const j = await api<any>(`/employer/needs/parse/${job.id}`);
        if (g !== gen.current) return;
        if (j.status === "done") return finish(g, j.result, j.delta ?? [], j.llm, "done");
        if (j.status === "failed") return setSt({ phase: "failed", llm: j.llm, applied: [], offers: [] });
      } catch { /* сеть мигнула — следующая попытка */ }
      if (Date.now() - t0 > POLL_MAX_MS) return setSt({ phase: "failed", llm: { reason: "timeout" }, applied: [], offers: [] });
      setSt((s) => ({ ...s, waited: Date.now() - t0 }));
      timer.current = window.setTimeout(tick, POLL_MS);
    };
    timer.current = window.setTimeout(tick, POLL_MS);
  }, [finish]);

  const reset = useCallback(() => { stop(); gen.current++; setSt({ phase: "idle", applied: [], offers: [] }); }, []);
  const touch = useCallback(() => { dirty.current = true; }, []);
  const decide = useCallback((ids: string[] | "all", accept: boolean) => {
    const pick = cur.current.offers.filter((d) => ids === "all" || ids.includes(d.id));
    if (!pick.length) return;
    if (accept) { dirty.current = true; setReq((r) => (r ? pick.reduce(applyDelta, r) : r)); }
    setSt((s) => ({ ...s, offers: s.offers.filter((d) => !pick.some((p) => p.id === d.id)), applied: accept ? [...s.applied, ...pick] : s.applied }));
  }, [setReq]);
  return { ...st, start, reset, touch, decide };
}
export type FastParse = ReturnType<typeof useFastParse>;

/** Чип «кто разобрал текст» с состоянием фона. */
export function ParseStatus({ req, fp }: { req: Req; fp: FastParse }) {
  const label = fp.llm?.model_label ?? req.llm?.model_label ?? "модель";
  if (fp.phase === "pending") {
    return (
      <span className="chip inline-flex items-center gap-1.5" role="status" aria-live="polite" title="Требования найдены словарём сразу; модель проверяет текст в фоне — карточка обновится сама">
        <span className="h-2 w-2 animate-pulse rounded-full bg-brand" aria-hidden="true" />
        разбор по словарю · уточняем моделью…{fp.waited && fp.waited > 3000 ? ` ${num(Math.round(fp.waited / 1000))} с` : ""}
      </span>
    );
  }
  if (fp.phase === "done" || fp.phase === "cached") {
    const ms = fp.llm?.latency_ms;
    const title = fp.phase === "cached" ? "Этот текст уже разбирался моделью — ответ из кэша, без повторного запроса"
      : `Ответила модель ${label}${fp.llm?.fallback ? " (запасная: основная не ответила)" : ""}${ms ? `, ${num(ms / 1000)} с` : ""}`;
    return <span className="chip" role="status" title={title}>разбор: словарь + {label}, цитаты проверены{fp.phase === "cached" ? " · из кэша" : ""}</span>;
  }
  if (fp.phase === "failed") {
    return <span className="chip" role="status" title="Модель не ответила вовремя — технологии, грейд и опыт найдены по словарю и правилам">разобрано словарём: модель не ответила</span>;
  }
  const note = req.llm?.used ? `Ответила модель ${label}${req.llm.fallback ? " (запасная: основная не ответила)" : ""}, ${num((req.llm.latency_ms ?? 0) / 1000)} с`
    : req.llm?.reason && req.llm.reason !== "not_configured" ? "Модели не ответили — разбор по словарю технологий и правилам" : undefined;
  return <span className="chip" title={note}>{req.method === "rules" ? (req.llm?.reason && req.llm.reason !== "not_configured" ? "разбор по словарю: модель не ответила" : "разбор по словарю") : `разбор: словарь + ${label}, цитаты проверены`}</span>;
}

/** Что изменила модель (строка) и её предложения после правок работодателя (принять / отклонить). */
export function Suggestions({ fp }: { fp: FastParse }) {
  const label = fp.llm?.model_label ?? "Модель";
  const added = fp.applied.filter((d) => d.kind !== "confirm_tag");
  const confirmed = fp.applied.filter((d) => d.kind === "confirm_tag");
  if (!added.length && !confirmed.length && !fp.offers.length) {
    return fp.phase === "done" || fp.phase === "cached" ? <p className="text-xs text-brand-ink/65">{label}: к разбору словаря добавить нечего.</p> : null;
  }
  return (
    <div className="space-y-2">
      {(added.length > 0 || confirmed.length > 0) && (
        <p className="text-xs text-brand-ink/75" data-testid="model-added">
          {added.length > 0 && <>{label} добавила: {added.map(deltaText).join("; ")}. </>}
          {confirmed.length > 0 && <>Подтвердила найденное словарём: {confirmed.map((d) => d.name ?? d.tag).join(", ")}.</>}
        </p>
      )}
      {fp.offers.length > 0 && (
        <div className="rounded-xl border border-brand/30 bg-brand-blush/20 p-3" data-testid="model-offers">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-brand-night">{label} предлагает</p>
            {fp.offers.length > 1 && (
              <div className="flex gap-1">
                <button type="button" className="rounded-lg px-2.5 py-1 text-xs font-semibold text-emerald-800 hover:bg-emerald-50" onClick={() => fp.decide("all", true)}>Принять все</button>
                <button type="button" className="rounded-lg px-2.5 py-1 text-xs font-semibold text-brand-plum hover:bg-brand-blush/60" onClick={() => fp.decide("all", false)}>Отклонить все</button>
              </div>
            )}
          </div>
          <ul className="mt-2 space-y-2">
            {fp.offers.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="break-words text-brand-night">{deltaText(d)}</p>
                  {d.evidence?.quote && <p className="break-words text-xs text-brand-ink/65">«{d.evidence.quote}» · {d.evidence.model ?? label}, цитата найдена в тексте</p>}
                </div>
                <div className="flex gap-1">
                  <button type="button" className="rounded-lg border border-emerald-600/40 px-2.5 py-1 text-xs font-semibold text-emerald-800 hover:bg-emerald-50" onClick={() => fp.decide([d.id], true)}>Принять</button>
                  <button type="button" className="rounded-lg px-2.5 py-1 text-xs font-semibold text-brand-plum hover:bg-brand-blush/60" onClick={() => fp.decide([d.id], false)}>Отклонить</button>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-brand-ink/65">{fp.edited ? "Вы уже проверяли требования — изменения модели применяются только по вашему решению." : "Здесь модель не согласна со словарём — требования не изменены, решите сами."}</p>
        </div>
      )}
    </div>
  );
}
