import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { BASIS_TITLE, BasisSeg, basisTitle, grossOf, netOf, type Basis } from "./Salary";
import { Alert, Field, NB, dateOnly, errText, rub } from "./ui";

/** Дата выхода (ГГГГ-ММ-ДД) без «г.» — чтобы точка в конце фразы не удваивалась: «26 октября 2026». */
const day = (v?: string | null) => dateOnly(v).replace(/ г\.$/, "");

/**
 * Найм после принятия приглашения (Н8): собеседование (1–3 слота), оффер со встречным, исход найма.
 * Правила — на сервере (backend/app/modules/hiring/service.py); здесь — формы и подсказки. Время слотов — московское.
 */

export const HIRING_CHANGED = "hiring:changed";
const fire = () => window.dispatchEvent(new Event(HIRING_CHANGED));
const MSK = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", weekday: "short", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
export const mskText = (iso?: string | null) => (iso ? `${MSK.format(new Date(iso))}${NB}МСК` : "—");
const FORMAT: Record<string, string> = { video: "Видеозвонок", phone: "Телефон", office: "В офисе" };
/** ISO → значение поля datetime-local по Москве (UTC+3, без перехода на летнее время). */
const toMskInput = (iso: string) => new Date(new Date(iso).getTime() + 3 * 3600e3).toISOString().slice(0, 16);
const fromMskInput = (v: string) => `${v}:00+03:00`;
const isLink = (s?: string | null) => !!s && /^https?:\/\//i.test(s);
/** Одна сумма в другом основании НДФЛ (≈, до тысячи). */
const otherOne = (v: number, basis?: string | null) => (basis || "gross") === "gross"
  ? `≈${NB}${rub(Math.round(netOf(v) / 1000) * 1000)} на руки` : `≈${NB}${rub(Math.round(grossOf(v) / 1000) * 1000)} до вычета НДФЛ`;

type Slot = { id?: string; starts_at: string; duration_min: number; format: string; place?: string | null };

function useHiring(path: string | null, onChange?: () => void) {
  const [st, setSt] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try { const r = await api<any>(path); if (alive.current) setSt(r); } catch (e) { if (alive.current) setErr(errText(e)); }
  }, [path]);
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [load]);
  /** Шаг найма; ats — этап уходит в ATS в фоне: перечитываем состояние, пока не вернётся (до ~9 с). */
  async function act(sub: string, body: unknown = {}, ats = false): Promise<boolean> {
    setBusy(true); setErr(null);
    try {
      setSt(await api<any>(`${path}/${sub}`.replace("/hiring/", "/"), { body }));
      fire(); onChange?.();
      if (ats) for (let k = 1; k <= 6; k++) window.setTimeout(() => { void load(); if (k === 6) onChange?.(); }, k * 1500);
      return true;
    } catch (e) { setErr(errText(e)); return false; } finally { setBusy(false); }
  }
  return { st, err, busy, act, setErr };
}

const STEP_OF: Record<string, number> = { contact: 0, slots: 0, reschedule: 0, interview: 0, interview_done: 1, offer: 1, offer_accepted: 2, hired: 3 };

/** Три шага найма: собеседование → оффер → выход на работу. */
function Steps({ stage, outcome }: { stage: string; outcome?: any }) {
  const cur = STEP_OF[stage] ?? 0;
  const closed = stage === "rejected" || stage === "declined";
  const items = ["Собеседование", "Оффер", closed ? outcome?.title ?? "Завершено" : "Выход на работу"];
  const short = ["Интервью", "Оффер", closed ? (stage === "declined" ? "Отказ" : outcome?.title ?? "Итог") : "Выход"];
  return (
    <ol className="grid grid-cols-3 gap-1.5 text-xs" aria-label="Этапы найма">
      {items.map((t, k) => {
        const done = !closed ? k < cur : false;
        const now = closed ? k === 2 : k === cur;
        const c = done ? "border-emerald-200 bg-emerald-50 text-emerald-800" : now ? (closed ? "border-gray-200 bg-gray-100 text-gray-700" : "border-brand/30 bg-brand-blush text-brand-night")
          : "border-brand-night/10 bg-white text-brand-ink/65";
        return <li key={t} className={`min-w-0 rounded-lg border px-2 py-1.5 font-semibold ${c}`} aria-current={now ? "step" : undefined}><span className="hidden truncate sm:block">{k + 1}. {t}</span><span className="block truncate sm:hidden">{short[k]}</span></li>;
      })}
    </ol>
  );
}

/** Этап найма в списке приглашений. */
export function HiringChip({ h }: { h?: any }) {
  if (!h || h.stage === "contact") return null;
  const c = h.todo ? "bg-amber-50 text-amber-800" : h.stage === "hired" ? "bg-emerald-50 text-emerald-700" : ["rejected", "declined"].includes(h.stage) ? "bg-gray-100 text-gray-600" : "bg-[#ECEAF8] text-brand-night";
  return <span className={`inline-flex max-w-full items-center truncate rounded-full px-2.5 py-1 text-xs font-semibold ${c}`} title={h.line}>{h.title}</span>;
}

function SlotLine({ s }: { s: Slot }) {
  return (
    <span className="min-w-0">
      <b className="text-brand-night">{mskText(s.starts_at)}</b>, {s.duration_min}{NB}мин · {FORMAT[s.format] ?? s.format}
      {s.place && <> · {isLink(s.place) ? <a className="break-all font-semibold text-brand-deep hover:underline" href={s.place} target="_blank" rel="noreferrer">ссылка на встречу</a> : <span className="break-words">{s.place}</span>}</>}
    </span>
  );
}

// ------------------------------------------------------------------ работодатель

function SlotsForm({ st, busy, onSubmit, onCancel }: { st: any; busy: boolean; onSubmit: (b: unknown) => Promise<boolean>; onCancel?: () => void }) {
  const preset: Slot[] = st.presets?.slots ?? [];
  const [title, setTitle] = useState(st.interview?.title ?? "");
  const [note, setNote] = useState("");
  const [rows, setRows] = useState(() => preset.map((s) => ({ at: toMskInput(s.starts_at), dur: String(s.duration_min), format: s.format, place: s.place ?? "" })));
  const set = (k: number, patch: Partial<(typeof rows)[number]>) => setRows((r) => r.map((x, i) => (i === k ? { ...x, ...patch } : x)));
  const send = () => onSubmit({ title: title || null, note: note || null, slots: rows.map((r) => ({ starts_at: fromMskInput(r.at), duration_min: Number(r.dur), format: r.format, place: r.place || null })) });
  return (
    <div className="space-y-3 rounded-xl border border-brand-night/10 p-3 sm:p-4">
      <p className="font-semibold text-brand-night">{st.interview ? "Новые слоты собеседования" : "Время собеседования"}</p>
      <p className="text-xs text-brand-ink/65">От одного до трёх вариантов, время по Москве. Кандидат выберет один или попросит другое время. Подставлены ближайшие рабочие дни — поправьте под себя.</p>
      <Field label="Название (необязательно)" htmlFor="hr-title"><input id="hr-title" className="input" maxLength={120} placeholder="Например, техническое собеседование" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
      {rows.map((r, k) => (
        <fieldset key={k} className="min-w-0 space-y-2 rounded-lg bg-brand-blush/25 p-2.5">
          <legend className="sr-only">Слот {k + 1}</legend>
          <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_9rem]">
            <input className="input min-w-0" type="datetime-local" aria-label={`Слот ${k + 1}: дата и время по Москве`} value={r.at} onChange={(e) => set(k, { at: e.target.value })} />
            <select className="input min-w-0" aria-label={`Слот ${k + 1}: длительность`} value={r.dur} onChange={(e) => set(k, { dur: e.target.value })}>
              {[30, 45, 60, 90, 120].map((m) => <option key={m} value={m}>{m} мин</option>)}
            </select>
            <select className="input min-w-0" aria-label={`Слот ${k + 1}: формат`} value={r.format} onChange={(e) => set(k, { format: e.target.value })}>
              {Object.entries(FORMAT).map(([id, t]) => <option key={id} value={id}>{t}</option>)}
            </select>
          </div>
          <div className="flex min-w-0 gap-2">
            <input className="input min-w-0 flex-1" aria-label={`Слот ${k + 1}: ссылка или адрес`} maxLength={500} placeholder={r.format === "office" ? "Адрес офиса" : r.format === "video" ? "Ссылка на видеозвонок, https://…" : "Номер или комментарий (необязательно)"} value={r.place} onChange={(e) => set(k, { place: e.target.value })} />
            {rows.length > 1 && <button type="button" className="shrink-0 text-xs font-semibold text-brand-plum hover:underline" onClick={() => setRows((x) => x.filter((_, i) => i !== k))}>Убрать</button>}
          </div>
        </fieldset>
      ))}
      {rows.length < 3 && <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={() => setRows((x) => [...x, { ...(x[x.length - 1] ?? { at: "", dur: "60", format: "video", place: "" }) }])}>Добавить слот</button>}
      <Field label="Комментарий кандидату (необязательно)" htmlFor="hr-note"><input id="hr-note" className="input" maxLength={1000} placeholder="Например, будет тимлид и разбор задачи" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary !py-2" disabled={busy || !rows.length || rows.some((r) => !r.at)} onClick={send}>Предложить кандидату</button>
        {onCancel && <button className="btn-ghost !py-2" disabled={busy} onClick={onCancel}>Назад</button>}
      </div>
    </div>
  );
}

function OfferForm({ st, busy, onSubmit, onCancel }: { st: any; busy: boolean; onSubmit: (b: unknown) => Promise<boolean>; onCancel: () => void }) {
  const p = st.presets?.offer ?? {};
  const [salary, setSalary] = useState(String(p.salary ?? st.salary_to));
  const [basis, setBasis] = useState<Basis>(p.salary_basis ?? st.salary_basis ?? "gross");
  const [start, setStart] = useState<string>(p.start_date ?? "");
  const [until, setUntil] = useState<string>(p.respond_until ?? "");
  const [comment, setComment] = useState("");
  const s = Number(salary);
  return (
    <div className="space-y-3 rounded-xl border border-brand-night/10 p-3 sm:p-4">
      <p className="font-semibold text-brand-night">Оффер</p>
      <p className="text-xs text-brand-ink/65">Вилка приглашения: {rub(st.salary_from)}{NB}– {rub(st.salary_to)} {basisTitle(st.salary_basis)}. Оффер — не ниже «от» вилки, выше «до» — можно. Кандидат примет, отклонит или ответит встречной суммой.</p>
      <div><p className="label">Сумма указана</p><BasisSeg value={basis} onChange={setBasis} /></div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Сумма, ₽ в месяц" htmlFor="of-s"><input id="of-s" type="number" min={1} step={5000} className="input" value={salary} onChange={(e) => setSalary(e.target.value)} /></Field>
        <Field label="Дата выхода" htmlFor="of-d"><input id="of-d" type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="Ответить до" htmlFor="of-u"><input id="of-u" type="date" className="input" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
      </div>
      {s > 0 && <p className="text-xs text-brand-ink/65">{otherOne(s, basis)}</p>}
      <Field label="Комментарий (необязательно)" htmlFor="of-c"><input id="of-c" className="input" maxLength={1000} placeholder="Например, ДМС с первого дня, испытательный срок 3 месяца" value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary !py-2" disabled={busy || !s || !start} onClick={() => onSubmit({ salary: s, salary_basis: basis, start_date: start, respond_until: until || null, comment: comment || null })}>Отправить оффер</button>
        <button className="btn-ghost !py-2" disabled={busy} onClick={onCancel}>Назад</button>
      </div>
    </div>
  );
}

const offerText = (o: any) => `${rub(o.salary)} ${BASIS_TITLE[o.salary_basis as Basis] ?? ""}`;

/** Найм в карточке приглашения у работодателя. */
export function EmployerHiring({ inv, onChange }: { inv: any; onChange?: () => void }) {
  const { st, err, busy, act } = useHiring(inv.status === "accepted" ? `/employer/invitations/${inv.id}/hiring` : null, onChange);
  const [form, setForm] = useState<"" | "slots" | "offer" | "rejected" | "declined">("");
  const [note, setNote] = useState("");
  if (inv.status !== "accepted" || !st) return null;
  const iv = st.interview, o = st.offer, can = st.can ?? {};
  const go = async (sub: string, body: unknown = {}, ats = false) => { if (await act(sub, body, ats)) { setForm(""); setNote(""); } };
  const lastDone = st.interviews?.find((x: any) => x.status === "done");
  const transfers = (st.ats ?? []).filter((a: any) => a.target !== "webhook");
  return (
    <section className="space-y-3 rounded-xl border border-brand-night/10 bg-white p-3 sm:p-4" aria-label={`Найм: ${inv.position_title ?? ""} · ${inv.candidate_ref ?? inv.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-brand-night">Найм</p>
        <span className="text-xs font-semibold text-brand-ink/65">{st.stage_title}</span>
      </div>
      <Steps stage={st.stage} outcome={st.outcome} />
      {!inv.ats_transfers && transfers.map((a: any) => (
        <p key={a.target} className={`text-xs ${a.status === "ok" ? "text-brand-ink/70" : "font-semibold text-amber-800"}`}>
          {a.status === "ok" ? <>Передано: {a.target_title}{a.stage_title ? ` · этап «${a.stage_title}»` : ""}</> : a.status === "pending" ? <>Передаём в {a.target_title}…</> : <>{a.target_title}: этап не передан — {a.error}</>}
        </p>
      ))}
      {st.paused && <Alert kind="info">Кандидат отозвал доступ к контактам — найм на паузе, пока он не вернёт доступ.</Alert>}
      {st.outcome && (
        <Alert kind={st.outcome.outcome === "hired" ? "ok" : "info"}>
          Найм завершён: <b>{st.outcome.title.toLowerCase()}</b>{st.outcome.start_date ? `, выход ${day(st.outcome.start_date)}` : ""}{st.outcome.note ? ` — «${st.outcome.note}»` : ""}.{transfers.some((a: any) => a.status === "ok") ? (inv.ats_stage ? " Этап передан в ATS и вернулся обратным каналом." : " Этап передан в ATS.") : ""}
        </Alert>
      )}

      {/* собеседование */}
      {iv?.status === "proposed" && form !== "slots" && (
        <div className="space-y-1.5">
          <p className="text-brand-ink/80"><b className="text-brand-night">{iv.title}</b>: ждём, какой слот выберет кандидат.</p>
          <ul className="space-y-1 text-brand-ink/80">{iv.slots.map((s: Slot) => <li key={s.id}><SlotLine s={s} /></li>)}</ul>
        </div>
      )}
      {iv?.status === "reschedule" && form !== "slots" && <Alert kind="info">Кандидат просит другое время: «{iv.candidate_note}». Предложите новые слоты.</Alert>}
      {iv?.status === "scheduled" && form !== "slots" && (
        <div className="space-y-2 rounded-lg bg-[#ECEAF8]/60 p-3">
          <p className="text-brand-night"><b>{iv.title}</b> назначено: <SlotLine s={{ starts_at: iv.starts_at, duration_min: iv.duration_min, format: iv.format, place: iv.place }} /></p>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary !py-2" disabled={busy} onClick={() => go(`interviews/${iv.id}/done`)}>Собеседование прошло</button>
            <button className="btn-ghost !py-2" disabled={busy} onClick={() => setForm("slots")}>Перенести</button>
            <button className="btn-ghost !py-2" disabled={busy} onClick={() => go(`interviews/${iv.id}/cancel`)}>Отменить</button>
          </div>
          {st.rules?.demo_done_anytime && <p className="text-xs text-brand-ink/65">Демо-компания: отметить «прошло» можно до начала, чтобы пройти путь за минуту.</p>}
        </div>
      )}
      {form === "slots" ? <SlotsForm st={st} busy={busy} onSubmit={(b) => act("interviews", b).then((ok) => { if (ok) setForm(""); return ok; })} onCancel={() => setForm("")} />
        : can.propose && (!iv || iv.status !== "scheduled") && !o && (
          <button className={iv?.status === "reschedule" || !iv ? "btn-primary !py-2" : "btn-ghost !py-2"} disabled={busy} onClick={() => setForm("slots")}>
            {iv ? "Предложить другие слоты" : lastDone ? "Назначить ещё одно собеседование" : "Предложить время собеседования"}
          </button>
        )}
      {lastDone && !iv && <p className="text-xs text-brand-ink/65">{lastDone.title} прошло{lastDone.starts_at ? ` (${mskText(lastDone.starts_at)})` : ""}{lastDone.result_note ? ` — «${lastDone.result_note}»` : ""}.</p>}

      {/* оффер */}
      {o?.status === "sent" && (
        <div className="space-y-2 rounded-lg border border-brand-night/10 p-3">
          <p className="text-brand-night">Оффер отправлен: <b>{offerText(o)}</b> · выход {day(o.start_date)} · ответ до {mskText(o.respond_until)}</p>
          {o.counter ? (
            <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
              <p className="font-semibold text-brand-night">Встречное кандидата: {rub(o.counter.salary)} {basisTitle(o.counter.salary_basis)}</p>
              {o.counter.comment && <p className="text-brand-ink/80">«{o.counter.comment}»</p>}
              <p className="text-xs text-brand-ink/70">Принять — оффер будет принят на сумме кандидата. Отклонить — в силе ваш оффер, кандидат может принять его или ответить ещё раз.</p>
              <input className="input" aria-label="Комментарий кандидату к решению по встречному" placeholder="Комментарий кандидату (необязательно)" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary !py-2" disabled={busy} onClick={() => go("offer/counter/accept", { note: note || null })}>Принять встречное</button>
                <button className="btn-ghost !py-2" disabled={busy} onClick={() => go("offer/counter/decline", { note: note || null })}>Отклонить встречное</button>
              </div>
            </div>
          ) : <p className="text-xs text-brand-ink/65">Ждём ответа кандидата{o.counters?.length ? ` · встречных было: ${o.counters.length}` : ""}.</p>}
          <button className="text-sm font-semibold text-brand-plum hover:underline" disabled={busy} onClick={() => go("offer/withdraw")}>Отозвать оффер</button>
        </div>
      )}
      {o?.status === "accepted" && !st.outcome && <Alert kind="ok">Кандидат принял оффер: <b>{offerText(o)}</b>, выход {day(o.start_date)}. Отметьте выход на работу — этап уйдёт в ATS.</Alert>}
      {o && ["declined", "withdrawn", "expired"].includes(o.status) && !st.outcome && <p className="text-xs text-brand-ink/65">Оффер {offerText(o)} {o.status === "declined" ? "отклонён кандидатом" : o.status === "withdrawn" ? "отозван" : "истёк"}.</p>}
      {form === "offer" ? <OfferForm st={st} busy={busy} onSubmit={(b) => act("offer", b, true).then((ok) => { if (ok) setForm(""); return ok; })} onCancel={() => setForm("")} />
        : can.offer && form !== "slots" && (
          <button className={lastDone && !iv ? "btn-primary !py-2" : "btn-ghost !py-2"} disabled={busy} onClick={() => setForm("offer")}>Отправить оффер</button>
        )}

      {/* исход */}
      {can.hired && <button className="btn-primary !py-2" disabled={busy} onClick={() => go("outcome", { outcome: "hired" }, true)}>Вышел на работу</button>}
      {(form === "rejected" || form === "declined") ? (
        <div className="space-y-2 rounded-lg border border-brand-night/10 p-3">
          <p className="font-semibold text-brand-night">{form === "rejected" ? "Кандидат не прошёл" : "Кандидат отказался"}</p>
          <p className="text-xs text-brand-ink/65">Исход окончательный: открытые собеседование и оффер закроются, этап уйдёт в ATS{form === "rejected" ? ", кандидат получит уведомление" : ""}.</p>
          <input className="input" aria-label="Комментарий к исходу" placeholder={form === "rejected" ? "Комментарий кандидату (необязательно)" : "Причина (необязательно)"} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary !py-2" disabled={busy} onClick={() => go("outcome", { outcome: form, note: note || null }, true)}>Зафиксировать</button>
            <button className="btn-ghost !py-2" disabled={busy} onClick={() => setForm("")}>Назад</button>
          </div>
        </div>
      ) : st.open && (
        <p className="text-xs text-brand-ink/65">Завершить найм: <button className="font-semibold text-brand-plum hover:underline" onClick={() => setForm("rejected")}>не прошёл</button> · <button className="font-semibold text-brand-plum hover:underline" onClick={() => setForm("declined")}>отказ кандидата</button></p>
      )}
      <Alert>{err}</Alert>
    </section>
  );
}

// ------------------------------------------------------------------ кандидат

/** Найм в окне приглашения у кандидата. */
export function CandidateHiring({ inv, onChange }: { inv: any; onChange?: () => void }) {
  const { st, err, busy, act, setErr } = useHiring(inv.status === "accepted" ? `/candidate/invitations/${inv.id}/hiring` : null, onChange);
  const [pick, setPick] = useState<string>("");
  const [mode, setMode] = useState<"" | "other" | "decline" | "counter">("");
  const [note, setNote] = useState("");
  const [salary, setSalary] = useState("");
  const [basis, setBasis] = useState<Basis>("gross");
  if (inv.status !== "accepted" || !st) return null;
  const iv = st.interview, o = st.offer, can = st.can ?? {};
  const go = async (sub: string, body: unknown = {}, ats = false) => { if (await act(sub, body, ats)) { setMode(""); setNote(""); } };
  const lastDone = st.interviews?.find((x: any) => x.status === "done");
  const quiet = st.stage === "contact" && !lastDone && !o && !st.outcome;
  return (
    <section className="space-y-3 rounded-xl border border-brand-night/10 p-3 sm:p-4" aria-label={`Собеседование и оффер: ${inv.position_title ?? inv.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-brand-night">Собеседование и оффер</p>
        <span className="text-xs font-semibold text-brand-ink/65">{st.stage_title}</span>
      </div>
      {!quiet && <Steps stage={st.stage} outcome={st.outcome} />}
      {quiet && <p className="text-brand-ink/70">Работодатель предложит здесь время собеседования, а потом — оффер. Ответить можно прямо в кабинете.</p>}
      {st.outcome && (
        <Alert kind={st.outcome.outcome === "hired" ? "ok" : "info"}>
          {st.outcome.outcome === "hired" ? <>Работодатель отметил выход на работу{st.outcome.start_date ? ` с ${day(st.outcome.start_date)}` : ""}. Успехов на новом месте.</>
            : st.outcome.outcome === "rejected" ? <>Работодатель завершил рассмотрение{st.outcome.note ? `: «${st.outcome.note}».` : "."}</>
              : <>Найм завершён: вы отказались от предложения.</>}
        </Alert>
      )}

      {iv?.status === "proposed" && mode !== "other" && (
        <div className="space-y-2">
          <p className="text-brand-night"><b>{iv.title}</b>: выберите удобное время{iv.note ? ` — «${iv.note}»` : ""}</p>
          <div className="space-y-1.5" role="radiogroup" aria-label="Слоты собеседования">
            {iv.slots.map((s: Slot) => (
              <label key={s.id} className={`flex min-w-0 cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 ${pick === s.id ? "border-brand bg-brand-blush/40" : "border-brand-night/10"}`}>
                <input type="radio" name={`slot-${iv.id}`} className="mt-1" checked={pick === s.id} onChange={() => setPick(s.id!)} />
                <SlotLine s={s} />
              </label>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary !py-2" disabled={busy || !pick} onClick={() => go(`interviews/${iv.id}/choose`, { slot_id: pick }, true)}>Подтвердить время</button>
            {can.reschedule && <button className="btn-ghost !py-2" disabled={busy} onClick={() => { setMode("other"); setErr(null); }}>Ни один не подходит</button>}
          </div>
        </div>
      )}
      {iv?.status === "reschedule" && <Alert kind="info">Вы попросили другое время: «{iv.candidate_note}». Работодатель предложит новые слоты.</Alert>}
      {iv?.status === "scheduled" && mode !== "other" && (
        <div className="space-y-2 rounded-lg bg-[#ECEAF8]/60 p-3">
          <p className="text-brand-night"><b>{iv.title}</b> назначено: <SlotLine s={{ starts_at: iv.starts_at, duration_min: iv.duration_min, format: iv.format, place: iv.place }} /></p>
          <p className="text-xs text-brand-ink/65">Напомним за сутки — уведомлением и письмом.{can.reschedule ? "" : " Перенести можно в переписке с работодателем."}</p>
          {can.reschedule && <button className="text-sm font-semibold text-brand-plum hover:underline" onClick={() => setMode("other")}>Попросить перенести</button>}
        </div>
      )}
      {mode === "other" && (
        <div className="space-y-2 rounded-lg border border-brand-night/10 p-3">
          <Field label="Когда вам удобно" htmlFor="hr-other" hint={`Осталось просьб о другом времени: ${iv?.reschedules_left ?? 0}`}>
            <textarea id="hr-other" className="input min-h-[64px]" maxLength={500} placeholder="Например, в будни после 18:00 или в субботу днём" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary !py-2" disabled={busy || !note.trim()} onClick={() => go(`interviews/${iv.id}/reschedule`, { note })}>Попросить другое время</button>
            <button className="btn-ghost !py-2" disabled={busy} onClick={() => setMode("")}>Назад</button>
          </div>
        </div>
      )}
      {lastDone && !iv && !o && !st.outcome && <p className="text-brand-ink/70">{lastDone.title} прошло. Если работодатель решит сделать предложение, оффер появится здесь.</p>}

      {o?.status === "sent" && (
        <div className="space-y-2 rounded-lg border border-brand/30 bg-brand-blush/25 p-3">
          <p className="font-semibold text-brand-night">Оффер</p>
          <p className="text-lg font-extrabold text-brand-night">{offerText(o)} <span className="text-sm font-semibold text-brand-ink/65">в месяц</span></p>
          <p className="text-xs text-brand-ink/70">{otherOne(o.salary, o.salary_basis)} · выход {day(o.start_date)} · ответить до {mskText(o.respond_until)}</p>
          {o.comment && <p className="text-brand-ink/80">«{o.comment}»</p>}
          {o.counter ? <Alert kind="info">Встречное отправлено: <b>{rub(o.counter.salary)} {basisTitle(o.counter.salary_basis)}</b>. Ждём ответа работодателя; пока можно принять оффер как есть.</Alert>
            : o.counters?.length > 0 && o.counters[o.counters.length - 1].status === "declined" && <p className="text-xs text-brand-ink/70">Работодатель не принял встречное {rub(o.counters[o.counters.length - 1].salary)}{o.counters[o.counters.length - 1].note ? `: «${o.counters[o.counters.length - 1].note}»` : ""}. В силе оффер.</p>}
          {mode === "counter" ? (
            <div className="space-y-2">
              <p className="text-xs text-brand-ink/65">Ваша сумма — выше оффера и не выше чем в 1,5 раза. Если работодатель примет её, оффер будет принят.</p>
              <div><p className="label">Сумма указана</p><BasisSeg value={basis} onChange={setBasis} /></div>
              <Field label="Моя сумма, ₽ в месяц" htmlFor="hr-cs"><input id="hr-cs" type="number" min={1} step={5000} className="input" value={salary} onChange={(e) => setSalary(e.target.value)} /></Field>
              <input className="input" aria-label="Комментарий к встречному" placeholder="Почему такая сумма (необязательно)" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary !py-2" disabled={busy || !Number(salary)} onClick={() => go("offer/counter", { salary: Number(salary), salary_basis: basis, comment: note || null })}>Отправить встречное</button>
                <button className="btn-ghost !py-2" disabled={busy} onClick={() => setMode("")}>Назад</button>
              </div>
            </div>
          ) : mode === "decline" ? (
            <div className="space-y-2">
              <input className="input" aria-label="Причина отказа от оффера" placeholder="Причина (необязательно)" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary !py-2" disabled={busy} onClick={() => go("offer/decline", { reason: note || null }, true)}>Отклонить оффер</button>
                <button className="btn-ghost !py-2" disabled={busy} onClick={() => setMode("")}>Назад</button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button className="btn-primary !py-2" disabled={busy} onClick={() => go("offer/accept", {}, true)}>Принять оффер</button>
              {!o.counter && o.counters_left > 0 && <button className="btn-ghost !py-2" disabled={busy} onClick={() => { setMode("counter"); setBasis(o.salary_basis); setSalary(String(Math.round(o.salary * 1.1 / 5000) * 5000)); setNote(""); }}>Предложить свою сумму</button>}
              <button className="btn-ghost !py-2" disabled={busy} onClick={() => { setMode("decline"); setNote(""); }}>Отклонить</button>
            </div>
          )}
        </div>
      )}
      {o?.status === "accepted" && !st.outcome && <Alert kind="ok">Вы приняли оффер: <b>{offerText(o)}</b>, выход {day(o.start_date)}. Работодатель отметит выход на работу.</Alert>}
      {o && ["withdrawn", "expired"].includes(o.status) && !st.outcome && <p className="text-xs text-brand-ink/65">Оффер {offerText(o)} {o.status === "withdrawn" ? "отозван работодателем" : "истёк"}.</p>}
      <Alert>{err}</Alert>
    </section>
  );
}

// ------------------------------------------------------------------ напоминания и значок в меню

const TODO_TITLE: Record<string, string> = {
  choose_slot: "Выберите время собеседования", interview_soon: "Скоро собеседование", answer_offer: "Ответьте на оффер",
  reschedule: "Кандидат просит другое время собеседования", mark_done: "Отметьте, прошло ли собеседование", counter: "Встречное на оффер ждёт решения",
};

function useTodo(on: boolean) {
  const [t, setT] = useState<{ total: number; items: any[] }>({ total: 0, items: [] });
  useEffect(() => {
    if (!on) return;
    let alive = true;
    const load = () => { if (document.visibilityState === "visible") api<any>("/hiring/todo").then((r) => alive && setT(r)).catch(() => undefined); };
    load();
    const timer = window.setInterval(load, 60000);
    window.addEventListener(HIRING_CHANGED, load);
    return () => { alive = false; window.clearInterval(timer); window.removeEventListener(HIRING_CHANGED, load); };
  }, [on]);
  return t;
}

/** Число шагов найма, ждущих ответа, — значок у «Приглашений» в меню кабинета. */
export function useHiringTodo(on: boolean | null | undefined): number {
  return useTodo(!!on).total;
}

/** Плашка-напоминание на странице приглашений: что ждёт ответа и ближайшее собеседование. */
export function HiringReminders() {
  const t = useTodo(true);
  if (!t.total) return null;
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="status">
      <ul className="space-y-1">
        {t.items.slice(0, 3).map((x, k) => (
          <li key={k}><b>{TODO_TITLE[x.kind] ?? x.kind}</b>: «{x.position_title}»{x.starts_at && ["interview_soon", "mark_done"].includes(x.kind) ? ` — ${mskText(x.starts_at)}${x.format_title ? ` · ${x.format_title.toLowerCase()}` : ""}` : ""}</li>
        ))}
      </ul>
      {t.total > 3 && <p className="mt-1 text-xs">И ещё {t.total - 3}.</p>}
    </div>
  );
}
