import { useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, History, Level, Loading, Seg, Status, catTitle, dt, errText, range, rub, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { AtsInvitationActions } from "../../integrations/Ats";

type Market = { from: number; to: number; median?: number } | null | undefined;

function SalaryFields({ from, to, setFrom, setTo, market }: { from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void; market: Market }) {
  const wide = Number(from) > 0 && Number(to) > Number(from) * SALARY_MAX_RATIO;
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Вилка от, ₽ в месяц" htmlFor="sf"><input id="sf" required type="number" min={1} step={5000} className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="Вилка до, ₽ в месяц" htmlFor="st"><input id="st" required type="number" min={1} step={5000} className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <p className={`mt-2 text-xs ${wide ? "font-semibold text-brand-plum" : "text-brand-ink/60"}`}>
        {wide ? `Вилка слишком широкая: при «от» ${rub(Number(from))} «до» — не выше ${rub(maxTo(from))}.` : "«До» — не больше чем в 1,5 раза выше «от»: узкая вилка показывает кандидату реальное предложение."}
      </p>
      {market && <p className="mt-1 text-xs text-brand-ink/60">Рынок категории: {range(market.from, market.to)}{market.median ? `, медиана ${rub(market.median)}` : ""} (Хабр Карьера). Минимум кандидата вам не показывается.</p>}
    </div>
  );
}

/** «До» не больше чем в 1,5 раза выше «от» — то же правило проверяет сервер (salary_range_too_wide). */
export const SALARY_MAX_RATIO = 1.5;
const maxTo = (from: string | number) => Math.floor((Number(from) * SALARY_MAX_RATIO) / 1000) * 1000;
const round5k = (v: number) => Math.round(v / 5000) * 5000;

/** Вилка по умолчанию: из потребности, иначе вокруг медианы рынка категории — в пределах допустимой ширины. */
export function defaultRange(market: Market, need?: { from?: number | null; to?: number | null } | null): [string, string] {
  if (need?.from && need?.to && need.to <= need.from * SALARY_MAX_RATIO) return [String(need.from), String(need.to)];
  if (!market) return ["", ""];
  const mid = market.median ?? (market.from + market.to) / 2;
  const lo = Math.max(market.from, round5k(mid * 0.9));
  return [String(lo), String(Math.min(maxTo(lo), Math.max(lo, round5k(mid * 1.25))))];
}

function salaryError(from: string, to: string) {
  if (!from || !to || Number(from) <= 0 || Number(to) <= 0) return "Укажите вилку зарплаты «от» и «до» — это обязательно";
  if (Number(from) > Number(to)) return "Нижняя граница вилки больше верхней";
  if (Number(to) > Number(from) * SALARY_MAX_RATIO) return `Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от» (не выше ${rub(maxTo(from))})`;
  return null;
}

export function ProbeForm({ refs, needId, market, needSalary, onDone }: { refs: string[]; needId?: string; market: Market; needSalary?: { from?: number | null; to?: number | null } | null; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [task, setTask] = useState("");
  const [mode, setMode] = useState<"any" | "solution" | "approach">("any");
  const [mins, setMins] = useState("30");
  const [from, setFrom] = useState(() => defaultRange(market, needSalary)[0]);
  const [to, setTo] = useState(() => defaultRange(market, needSalary)[1]);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<any>(null);
  async function send() {
    const se = salaryError(from, to);
    if (se) { setErr(se); return; }
    setErr(null);
    try {
      setRes(await api<any>("/employer/probes", { body: { candidate_refs: refs, need_id: needId ?? null, title, task_text: task, answer_mode: mode, time_limit_min: Number(mins), salary_from: Number(from), salary_to: Number(to) } }));
    } catch (e) { setErr(errText(e)); }
  }
  if (res) return (
    <div className="space-y-3 text-sm">
      <Alert kind="ok">Зонд отправлен: {res.created.length}. Кандидаты получат уведомление; контакты не раскрываются.</Alert>
      {res.skipped.length > 0 && <Alert kind="info">Пропущено: {res.skipped.map((s: any) => `${s.ref} — ${s.reason}`).join("; ")}</Alert>}
      <button className="btn-primary" onClick={onDone}>Готово</button>
    </div>
  );
  return (
    <div className="space-y-4">
      <p className="text-sm text-brand-ink/65">Короткая задача на 15–30 минут. Кандидат ответит решением или подходом; ваша оценка станет подтверждённым фактом (T1).</p>
      <Field label="Название" htmlFor="pt"><input id="pt" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например, медленный запрос" /></Field>
      <Field label="Задача" htmlFor="ptask"><textarea id="ptask" className="input min-h-[120px]" value={task} onChange={(e) => setTask(e.target.value)} placeholder="Запрос с JOIN по двум таблицам выполняется 8 секунд. Опишите план диагностики и исправления." /></Field>
      <div className="flex flex-wrap items-end gap-4">
        <div><p className="label">Формат ответа</p><Seg label="Формат ответа" value={mode} onChange={setMode} options={[{ id: "any", title: "На выбор" }, { id: "approach", title: "Подход" }, { id: "solution", title: "Решение" }]} /></div>
        <Field label="Время, мин" htmlFor="pm"><input id="pm" type="number" min={5} max={240} className="input w-28" value={mins} onChange={(e) => setMins(e.target.value)} /></Field>
      </div>
      <SalaryFields from={from} to={to} setFrom={setFrom} setTo={setTo} market={market} />
      <Alert>{err}</Alert>
      <button className="btn-primary" disabled={title.length < 3 || task.length < 20} onClick={send}>Отправить зонд</button>
    </div>
  );
}

export function InviteForm({ cref, needId, probeId, market, needSalary, onDone }: { cref: string; needId?: string | null; probeId?: string | null; market: Market; needSalary?: { from?: number | null; to?: number | null } | null; onDone: (inv: any) => void }) {
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [contact, setContact] = useState("");
  const [from, setFrom] = useState(() => defaultRange(market, needSalary)[0]);
  const [to, setTo] = useState(() => defaultRange(market, needSalary)[1]);
  const [err, setErr] = useState<string | null>(null);
  async function send() {
    const se = salaryError(from, to);
    if (se) { setErr(se); return; }
    setErr(null);
    try {
      onDone(await api<any>("/employer/invitations", { body: { candidate_ref: cref, need_id: needId ?? null, probe_id: probeId ?? null, position_title: title, offer_description: desc, contact_method: contact, salary_from: Number(from), salary_to: Number(to) } }));
    } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="space-y-4">
      <Field label="Позиция" htmlFor="it"><input id="it" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Python-разработчик в команду платежей" /></Field>
      <Field label="Суть предложения" htmlFor="idesc"><textarea id="idesc" className="input min-h-[110px]" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Задачи, команда, формат, что предлагаем" /></Field>
      <Field label="Как с вами связаться" htmlFor="ic"><input id="ic" className="input" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Telegram @hr_company или hr@company.ru" /></Field>
      <SalaryFields from={from} to={to} setFrom={setFrom} setTo={setTo} market={market} />
      <p className="text-xs text-brand-ink/55">К приглашению автоматически приложатся подтверждённые факты (T1/T2) о соответствии. Одно приглашение кандидату — не чаще раза в 30 дней.</p>
      <Alert>{err}</Alert>
      <button className="btn-primary" disabled={title.length < 3 || desc.length < 20 || contact.length < 3} onClick={send}>Отправить приглашение</button>
    </div>
  );
}

export function EmployerProbes() {
  const { data, loading, error, reload } = useApi<any[]>("/employer/probes");
  const [err, setErr] = useState<string | null>(null);
  const [comment, setComment] = useState<Record<string, string>>({});
  async function review(id: string, verdict: string) {
    setErr(null);
    try { await api(`/employer/probes/${id}/review`, { body: { verdict, comment: comment[id] || null } }); await reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Зонды" subtitle="Короткие задачи с вилкой зарплаты до раскрытия контактов. Оценка ответа становится фактом T1 в профиле кандидата." />
      <Alert>{err}</Alert>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Зондов пока нет" text="Отметьте кандидатов в подборке и отправьте им короткую задачу." action={<Link to="/employer/needs" className="btn-primary">К подборкам</Link>} />
      ) : data.map((p) => (
        <article key={p.id} className="card space-y-3 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-bold text-brand-night">{p.title}</p>
              <p className="text-brand-ink/60"><Link className="font-semibold text-brand" to={`/employer/candidates/${p.candidate_ref}`}>{p.candidate_ref}</Link> · {catTitle(p.candidate_category)} · {range(p.salary_from, p.salary_to)} · {dt(p.created_at)}</p>
            </div>
            <Status s={p.status} />
          </div>
          {p.answer && <div className="rounded-xl bg-[#F3F2FB] p-3"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{p.answer.mode === "solution" ? "Решение" : "Подход"}</p><p className="mt-1 whitespace-pre-line">{p.answer.text}</p>{p.answer.link && <p className="mt-1 break-all text-brand">{p.answer.link}</p>}</div>}
          {p.status === "submitted" && (
            <div className="space-y-2">
              <input className="input" placeholder="Комментарий кандидату (необязательно)" value={comment[p.id] ?? ""} onChange={(e) => setComment({ ...comment, [p.id]: e.target.value })} />
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary !py-2" onClick={() => review(p.id, "strong")}>Сильное</button>
                <button className="btn-ghost !py-2" onClick={() => review(p.id, "ok")}>Хорошее</button>
                <button className="btn-ghost !py-2" onClick={() => review(p.id, "weak")}>Слабое</button>
              </div>
            </div>
          )}
          {p.review && <p className="flex items-center gap-2"><Level level="T1" /> {p.review.verdict_title}{p.review.comment ? ` — «${p.review.comment}»` : ""}</p>}
          <details><summary className="cursor-pointer text-brand-ink/60">История</summary><div className="mt-2"><History items={p.events} /></div></details>
        </article>
      ))}
    </div>
  );
}

export function EmployerInvitations() {
  const { data, loading, error, reload } = useApi<any[]>("/employer/invitations");
  const [err, setErr] = useState<string | null>(null);
  async function withdraw(id: string) {
    try { await api(`/employer/invitations/${id}/withdraw`, { method: "POST" }); await reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Приглашения" subtitle="Статусы и история по каждому приглашению. Контакты кандидата открываются после принятия." />
      <Alert>{err}</Alert>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Приглашений пока нет" text="Откройте карточку кандидата из подборки или поиска и отправьте приглашение с вилкой." />
      ) : data.map((i) => (
        <article key={i.id} className="card space-y-3 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-bold text-brand-night">{i.position_title}</p>
              <p className="text-brand-ink/60"><Link className="font-semibold text-brand" to={`/employer/candidates/${i.candidate_ref}`}>{i.candidate_ref}</Link> · {catTitle(i.candidate_category)} · {range(i.salary_from, i.salary_to)}</p>
            </div>
            <Status s={i.status} />
          </div>
          {i.contacts ? (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-emerald-900">
              <p className="font-semibold">Контакты кандидата</p>
              <p className="mt-1">{[i.contacts.full_name, i.contacts.email, i.contacts.phone, i.contacts.telegram].filter(Boolean).join(" · ")}</p>
            </div>
          ) : <p className="text-brand-ink/55">Контакты откроются после принятия приглашения.</p>}
          <AtsInvitationActions invitationId={i.id} status={i.status} candidateRef={i.candidate_ref} />
          {i.complaint ? (
            <p className="rounded-xl bg-amber-50 px-3 py-2 text-amber-900">Жалоба кандидата: <b>{i.complaint.reason_title.toLowerCase()}</b>. Жалобы снижают индекс доверия компании — его видят кандидаты.</p>
          ) : i.decline_reason && <p className="text-brand-ink/70">Причина отказа: «{i.decline_reason}»</p>}
          <History items={i.history} />
          {["sent", "viewed"].includes(i.status) && <button className="text-sm font-semibold text-brand-plum hover:underline" onClick={() => withdraw(i.id)}>Отозвать</button>}
        </article>
      ))}
    </div>
  );
}
