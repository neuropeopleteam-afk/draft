import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, History, Level, Loading, Seg, Status, Toggle, catTitle, dt, dtt, errText, plural, rub, useApi } from "../../components/ui";
import { InlineThread } from "../../components/Chat";
import { BasisSeg, MARKET_SOURCE, MarketNote, otherBasis, salaryText, type Basis } from "../../components/Salary";
import { ApiError, api } from "../../lib/api";
import { daysText, useRules } from "../../lib/meta";
import { AtsInvitationActions, AtsStageBadge } from "../../integrations/Ats";
import { EmploymentTermsText } from "../../integrations/Youth";
import { HhMarketNote } from "../../integrations/HhImport";  // Я12: «Рынок по hh.ru» у вилки (только при HH_ENABLED)
import { EmployerHiring, HiringChip, HiringReminders } from "../../components/Hiring";
import { AiInterviewEmployer } from "../../components/Interview";  // Я15: этап найма «ИИ-интервью»
import { OfferFitHint } from "../mutual/Employer";  // подсказка до отправки: подходит ли предложение кандидату (Н9)
import { InvitesLeft } from "./Tariffs";  // Я29: «осталось приглашений» (только при TARIFFS_ENABLED)

type Market = { from: number; to: number; median?: number | null } | null | undefined;
/** Вилка из потребности: разбор текста отдаёт и основание («на руки» — salary_net), need_parser. */
export type NeedSalary = { from?: number | null; to?: number | null; net?: boolean | null } | null | undefined;
const basisOf = (need: NeedSalary): Basis => (need?.net ? "net" : "gross");

function SalaryFields({ from, to, setFrom, setTo, basis, setBasis, market, hh }: {
  from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void; basis: Basis; setBasis: (b: Basis) => void; market: Market;
  hh?: { cref?: string | null; needId?: string | null };
}) {
  const f = Number(from), t = Number(to);
  const wide = f > 0 && t > f * SALARY_MAX_RATIO;
  return (
    <div className="space-y-3">
      <div><p className="label">Сумма указана</p><BasisSeg value={basis} onChange={setBasis} /></div>
      <div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Вилка от, ₽ в месяц" htmlFor="sf"><input id="sf" required type="number" min={1} step={5000} className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="Вилка до, ₽ в месяц" htmlFor="st"><input id="st" required type="number" min={1} step={5000} className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
        <p className={`mt-2 text-xs ${wide ? "font-semibold text-brand-plum" : "text-brand-ink/65"}`}>
          {wide ? `Вилка слишком широкая: при «от» ${rub(f)} «до» — не выше ${rub(maxTo(from))}.`
            : f > 0 && t >= f ? `${otherBasis(f, t, basis)} · по шкале НДФЛ 13–22 %. «До» — не больше чем в 1,5 раза выше «от».`
              : "«До» — не больше чем в 1,5 раза выше «от»: узкая вилка показывает кандидату реальное предложение."}
        </p>
      </div>
      {/* UX-2 (аудит №3): два источника подписаны по смыслу, объяснение — одна раскрывашка «Как считали» */}
      {hh ? <>
        <MarketNote m={market} title="Ожидания кандидатов этой категории" short />
        <HhMarketNote cref={hh.cref} needId={hh.needId} title="Вакансии на hh.ru" how={<>
          <b>Ожидания кандидатов этой категории</b> — {MARKET_SOURCE}, на руки{market?.median ? `, медиана ${rub(market.median)}` : ""}.{" "}
          <b>Вакансии на hh.ru</b> — живые вакансии с зарплатой по категории и региону. Источники разные, поэтому и медианы разные. Минимум кандидата вам не показывается.{" "}
        </>} />
      </> : <MarketNote m={market} extra="Минимум кандидата вам не показывается." />}
    </div>
  );
}

/** «До» не больше чем в 1,5 раза выше «от» — то же правило проверяет сервер (salary_range_too_wide). */
export const SALARY_MAX_RATIO = 1.5;
const maxTo = (from: string | number) => Math.floor((Number(from) * SALARY_MAX_RATIO) / 1000) * 1000;
const round5k = (v: number) => Math.round(v / 5000) * 5000;

/** Вилка по умолчанию: из потребности; иначе вокруг медианы рынка категории — в пределах допустимой ширины и
 *  не выше бюджета потребности («до» потребности — потолок: кандидату не предлагаем больше, чем заложено). */
export function defaultRange(market: Market, need?: { from?: number | null; to?: number | null } | null): [string, string] {
  const cap = need?.to || null;
  if (need?.from && need?.to && need.to <= need.from * SALARY_MAX_RATIO) return [String(need.from), String(need.to)];
  let lo = 0, hi = 0;
  if (market) {
    const mid = market.median ?? (market.from + market.to) / 2;
    lo = Math.max(market.from, round5k(mid * 0.9));
    hi = Math.min(maxTo(lo), Math.max(lo, round5k(mid * 1.25)));
  } else if (cap) { hi = cap; lo = need?.from ?? round5k(cap / 1.25); }
  if (!lo || !hi) return ["", ""];
  if (cap) {
    hi = Math.min(hi, cap);
    if (need?.from) lo = Math.max(lo, need.from);
    lo = Math.min(lo, hi);
    if (hi > maxTo(lo)) lo = Math.min(hi, Math.ceil(hi / SALARY_MAX_RATIO / 1000) * 1000);  // не шире, чем разрешает правило 1,5
  }
  return [String(lo), String(hi)];
}

function salaryError(from: string, to: string) {
  if (!from || !to || Number(from) <= 0 || Number(to) <= 0) return "Укажите вилку зарплаты «от» и «до» — это обязательно";
  if (Number(from) > Number(to)) return "Нижняя граница вилки больше верхней";
  if (Number(to) > Number(from) * SALARY_MAX_RATIO) return `Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от» (не выше ${rub(maxTo(from))})`;
  return null;
}

/** Текст на странице после отправки зонда (окно закрывается само, если отправлено всем). */
export const probeSentText = (r: any) => r?.created?.length
  ? `Зонд отправлен: ${r.created.length} ${plural(r.created.length, "кандидату", "кандидатам", "кандидатам")}. Ответ появится в разделе «Зонды»; контакты не раскрываются.`
  : null;

export function ProbeForm({ refs, needId, market, needSalary, onDone, init }: { refs: string[]; needId?: string; market: Market; needSalary?: NeedSalary; onDone: (res?: any) => void; init?: { title?: string; task?: string } | null }) {
  const [title, setTitle] = useState(init?.title ?? "");  // Я10: заготовка вопроса на навык, который тест не проверяет
  const [task, setTask] = useState(init?.task ?? "");
  const [mode, setMode] = useState<"any" | "solution" | "approach">("any");
  const [mins, setMins] = useState("30");
  const [from, setFrom] = useState(() => defaultRange(market, needSalary)[0]);
  const [to, setTo] = useState(() => defaultRange(market, needSalary)[1]);
  const [basis, setBasis] = useState<Basis>(() => basisOf(needSalary));
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<any>(null);
  async function send() {
    const se = salaryError(from, to);
    if (se) { setErr(se); return; }
    setErr(null);
    try {
      const r = await api<any>("/employer/probes", { body: { candidate_refs: refs, need_id: needId ?? null, title, task_text: task, answer_mode: mode, time_limit_min: Number(mins), salary_from: Number(from), salary_to: Number(to), salary_basis: basis } });
      // Ф6: отправлено всем — окно закрывается, итог — на странице; есть пропуски — показываем причины в окне
      if (r.created?.length && !r.skipped?.length) onDone(r); else setRes(r);
    } catch (e) { setErr(errText(e)); }
  }
  if (res) return (
    <div className="space-y-3 text-sm">
      {res.created.length > 0
        ? <Alert kind="ok">Зонд отправлен: {res.created.length} {plural(res.created.length, "кандидату", "кандидатам", "кандидатам")}. {res.created.length === 1 ? "Кандидат получит" : "Кандидаты получат"} уведомление; контакты не раскрываются.</Alert>
        : <Alert kind="info">Зонд никому не отправлен: причины ниже.</Alert>}
      {res.skipped.length > 0 && <Alert kind="info">Пропущено: {res.skipped.map((s: any) => `${s.ref} — ${s.reason}`).join("; ")}</Alert>}
      <button className="btn-primary" onClick={() => onDone(res)}>Готово</button>
    </div>
  );
  return (
    <div className="space-y-4">
      <p className="text-sm text-brand-ink/65">Короткая задача на 15–30 минут. Кандидат ответит решением или подходом; ваша оценка станет проверенным фактом в профиле кандидата.</p>
      <Field label="Название" htmlFor="pt"><input id="pt" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например, медленный запрос" /></Field>
      <Field label="Задача" htmlFor="ptask"><textarea id="ptask" className="input min-h-[120px]" value={task} onChange={(e) => setTask(e.target.value)} placeholder="Запрос с JOIN по двум таблицам выполняется 8 секунд. Опишите план диагностики и исправления." /></Field>
      <div className="flex flex-wrap items-end gap-4">
        <div><p className="label">Формат ответа</p><Seg label="Формат ответа" value={mode} onChange={setMode} options={[{ id: "any", title: "На выбор" }, { id: "approach", title: "Подход" }, { id: "solution", title: "Решение" }]} /></div>
        <Field label="Время, мин" htmlFor="pm"><input id="pm" type="number" min={5} max={240} className="input w-28" value={mins} onChange={(e) => setMins(e.target.value)} /></Field>
      </div>
      <SalaryFields from={from} to={to} setFrom={setFrom} setTo={setTo} basis={basis} setBasis={setBasis} market={market} />
      <Alert>{err}</Alert>
      <button className="btn-primary" disabled={title.length < 3 || task.length < 20} onClick={send}>Отправить зонд</button>
    </div>
  );
}

const FORMAT_TITLES: Record<string, string> = { employment: "Работа", internship: "Стажировка", light_work: "Лёгкий труд (для 16–17 лет)" };

/** Я11 (С3-6): подтверждение сразу после ответа POST — кому, что и когда; контакты — после согласия. */
export const inviteSentText = (inv: any, cref: string) => {
  const at = inv?.created_at ? new Date(inv.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : null;
  const pos = inv?.position_title ? ` «${inv.position_title}»` : "";
  const fork = inv?.salary_from && inv?.salary_to ? `, вилка ${salaryText(inv.salary_from, inv.salary_to, inv.salary_basis)}` : "";
  return `Приглашение отправлено кандидату ${cref}${at ? ` в ${at}` : ""}:${pos}${fork}. Кандидат увидит компанию, условия и вилку; контакты откроются после его согласия.`;
};

/** Я11 (С3-6): почему «Пригласить» неактивна — для подсказки у кнопки (title и текст рядом). */
export const inviteBlockedText = (c: any) =>
  `Приглашение этому кандидату уже отправлено. Следующее — с ${c?.invite_available_at ? dt(c.invite_available_at) : "окончания срока"}${c?.invitation_cooldown_days ? ` (не чаще раза в ${c.invitation_cooldown_days} дней)` : ""}.`;

/** FIX7 В1 (замечание владельца): почему «Отправить приглашение» неактивна — живой список того, что осталось заполнить
 *  (с числом недостающих знаков). Те же условия, что у disabled кнопки; сервер проверяет их же (employer/invitations). */
export const INVITE_MIN = { title: 3, desc: 20, contact: 3 } as const;
const left = (n: number) => `ещё ${n} ${plural(n, "знак", "знака", "знаков")}`;
export function inviteMissing(o: { title: string; desc: string; contact: string; minor?: boolean; offerAllowed?: boolean; format: string; reduced: boolean; ack: boolean }) {
  const out: { field: "title" | "desc" | "contact" | "format" | "reduced" | "ack" | "offer"; text: string }[] = [];
  const t = o.title.trim().length, d = o.desc.trim().length, c = o.contact.trim().length;
  if (t < INVITE_MIN.title) out.push({ field: "title", text: `«Позиция» — ${left(INVITE_MIN.title - t)}` });
  if (d < INVITE_MIN.desc) out.push({ field: "desc", text: `«Суть предложения» — ${left(INVITE_MIN.desc - d)} (минимум ${INVITE_MIN.desc})` });
  if (c < INVITE_MIN.contact) out.push({ field: "contact", text: `«Как с вами связаться» — Telegram, почта или телефон (${left(INVITE_MIN.contact - c)})` });
  if (o.minor) {
    if (!o.offerAllowed) out.push({ field: "offer", text: "оффер этому кандидату недоступен (14–15 лет или нет отметки согласия) — см. пояснение выше" });
    else {
      if (o.format === "employment") out.push({ field: "format", text: "«Формат предложения» — для 16–17 лет стажировка или лёгкий труд" });
      if (!o.reduced) out.push({ field: "reduced", text: "отметку «Сокращённое рабочее время» — обязательно для 16–17 лет" });
      if (!o.ack) out.push({ field: "ack", text: "отметку «Проверю документы и ограничения перед оформлением»" });
    }
  }
  return out;
}
const warnRing = (on: boolean) => (on ? " !border-amber-500 ring-2 ring-amber-200" : "");

export function InviteForm({ cref, needId, probeId, market, needSalary, onDone }: { cref: string; needId?: string | null; probeId?: string | null; market: Market; needSalary?: NeedSalary; onDone: (inv: any) => void }) {
  const candidate = useApi<any>(`/employer/candidates/${cref}`);
  const safety = candidate.data?.employment_safety;
  const rules = useRules();
  // форматы — от возраста кандидата: взрослому — работа и стажировка, «лёгкий труд» только для 16–17 лет (backend/modules/fsp/youth.py)
  const formats: string[] = safety?.allowed_formats ?? ["employment", "internship"];
  const [format, setFormat] = useState("employment");
  useEffect(() => { if (safety && !formats.includes(format)) setFormat(formats[0]); }, [safety]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [reduced, setReduced] = useState(false);
  const [ack, setAck] = useState(false);
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [contact, setContact] = useState("");
  const [from, setFrom] = useState(() => defaultRange(market, needSalary)[0]);
  const [to, setTo] = useState(() => defaultRange(market, needSalary)[1]);
  const [basis, setBasis] = useState<Basis>(() => basisOf(needSalary));
  const [err, setErr] = useState<string | null>(null);
  const [limitHit, setLimitHit] = useState(false);  // Я29: 409 tariff_limit — ссылка на тарифы
  const [sending, setSending] = useState(false);  // Я11 (С3-6): «Отправляем…» сразу, повторное нажатие не шлёт второй POST
  const inFlight = useRef(false);
  // В1: что мешает отправке — список под кнопкой; поля подсвечиваем, когда пользователь начал заполнять форму
  const missing = inviteMissing({ title, desc, contact, minor: !!safety?.minor, offerAllowed: !!safety?.offer_allowed, format, reduced, ack });
  const miss = new Set<string>(missing.map((m) => m.field));
  const [touched, setTouched] = useState(false);
  const show = touched || !!(title || desc || contact);
  const hl = (f: string) => warnRing(show && miss.has(f));
  async function send() {
    if (inFlight.current) return;
    const se = salaryError(from, to);
    if (se) { setErr(se); return; }
    setErr(null);
    inFlight.current = true; setSending(true);
    try {
      onDone(await api<any>("/employer/invitations", { body: { candidate_ref: cref, need_id: needId ?? null, probe_id: probeId ?? null, position_title: title, offer_description: desc, contact_method: contact, salary_from: Number(from), salary_to: Number(to), employment_terms: { format, reduced_time: reduced, employer_acknowledged: ack }, salary_basis: basis } }));
    } catch (e) { setErr(errText(e)); setLimitHit(e instanceof ApiError && e.code === "tariff_limit"); } finally { inFlight.current = false; setSending(false); }
  }
  return (
    <div className="space-y-4">
      <Field label="Позиция" htmlFor="it"><input id="it" className={`input${hl("title")}`} aria-invalid={(show && miss.has("title")) || undefined} aria-describedby="invite-missing" value={title} onBlur={() => setTouched(true)} onChange={(e) => setTitle(e.target.value)} placeholder="Python-разработчик в команду платежей" /></Field>
      <Field label="Суть предложения" htmlFor="idesc"><textarea id="idesc" className={`input min-h-[110px]${hl("desc")}`} aria-invalid={(show && miss.has("desc")) || undefined} aria-describedby="invite-desc-count invite-missing" value={desc} onBlur={() => setTouched(true)} onChange={(e) => setDesc(e.target.value)} placeholder="Задачи, команда, формат, что предлагаем" />
        <p id="invite-desc-count" className={`mt-1 text-xs ${desc.trim().length < INVITE_MIN.desc ? "text-amber-800" : "text-brand-ink/65"}`} data-testid="invite-desc-count">{desc.trim().length} / {INVITE_MIN.desc} знаков минимум</p></Field>
      <Field label="Как с вами связаться" htmlFor="ic"><input id="ic" className={`input${hl("contact")}`} aria-invalid={(show && miss.has("contact")) || undefined} aria-describedby="invite-missing" value={contact} onBlur={() => setTouched(true)} onChange={(e) => setContact(e.target.value)} placeholder="Telegram @hr_company или hr@company.ru" /></Field>
      <SalaryFields from={from} to={to} setFrom={setFrom} setTo={setTo} basis={basis} setBasis={setBasis} market={market} hh={{ cref, needId }} />
      <OfferFitHint cref={cref} needId={needId} from={Number(from) || undefined} to={Number(to) || undefined} basis={basis} />
      {safety?.minor && <Alert kind="info">{safety.warning} {!safety.offer_allowed && "Оффер недоступен: возраст 14–15 лет или ещё нет отметки согласия."}</Alert>}
      <Field label="Формат предложения" htmlFor="offer-format"><select id="offer-format" className={`input${hl("format")}`} value={format} onChange={e => setFormat(e.target.value)}>
        {formats.map((f) => <option key={f} value={f}>{FORMAT_TITLES[f] ?? f}</option>)}
      </select></Field>
      {/* В1: сокращённое время — условие только для 16–17 лет (backend/modules/fsp/youth.py); взрослым переключатель не нужен */}
      {safety?.minor && <Toggle checked={reduced} onChange={setReduced} label="Сокращённое рабочее время" />}
      {safety?.minor && <Toggle checked={ack} onChange={setAck} label="Проверю документы и ограничения перед оформлением" />}
      <p className="text-xs text-brand-ink/65">К приглашению автоматически приложатся проверенные факты о соответствии: тест, задания, достижения ФСП. {rules ? `Одно приглашение кандидату — не чаще раза в ${daysText(rules.invitation_cooldown_days)}. ` : ""}До принятия кандидат может задать вопрос в переписке или предложить свою вилку.</p>
      <Alert>{err && <>{err}{limitHit && <> <Link to="/employer/tariffs" className="font-semibold underline">Открыть тарифы</Link></>}</>}</Alert>
      <InvitesLeft />
      <button className="btn-primary" aria-busy={sending || undefined} aria-describedby="invite-missing" disabled={sending || candidate.loading || !!candidate.error || missing.length > 0} onClick={send}>{sending ? "Отправляем приглашение…" : "Отправить приглашение"}</button>
      <div id="invite-missing" aria-live="polite" data-testid="invite-missing">
        {missing.length > 0 && (
          <div className="rounded-xl bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-950 ring-1 ring-amber-200">
            <p className="font-semibold">Чтобы отправить, заполните:</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">{missing.map((m) => <li key={m.field}>{m.text}</li>)}</ul>
          </div>
        )}
        {missing.length === 0 && candidate.loading && <p className="text-xs text-brand-ink/65">Загружаем данные кандидата…</p>}
      </div>
      <p className="sr-only" role="status" aria-live="polite">{sending ? `Отправляем приглашение кандидату ${cref}` : ""}</p>
      {candidate.error && <Alert>{candidate.error}</Alert>}
    </div>
  );
}

export function EmployerProbes() {
  const { data: all, loading, error, reload } = useApi<any[]>("/employer/probes");
  const need = new URLSearchParams(useLocation().search).get("need");  // Я10: из подборки — «зонды по этой потребности»
  const data = need && all ? all.filter((p) => p.need_id === need) : all;
  const [err, setErr] = useState<string | null>(null);
  const [comment, setComment] = useState<Record<string, string>>({});
  async function review(id: string, verdict: string) {
    setErr(null);
    try { await api(`/employer/probes/${id}/review`, { body: { verdict, comment: comment[id] || null } }); await reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Зонды" subtitle="Короткая задача с вилкой до раскрытия контактов; оценка ответа — подтверждённый факт." />
      <p className="text-sm text-brand-ink/70">Рядом с зондом со свободным ответом — <Link className="font-semibold text-brand hover:underline" to="/employer/assignments">задания с автопроверкой</Link>: 3–5 заданий банка по стеку потребности, проверяет система.</p>
      {need && all && <p className="text-sm text-brand-ink/70" data-testid="probes-need-filter">Показаны зонды по одной потребности: {data?.length ?? 0} из {all.length}. <Link className="font-semibold text-brand hover:underline" to={`/employer/needs/${need}`}>К подборке</Link> · <Link className="font-semibold text-brand hover:underline" to="/employer/probes">Все зонды</Link></p>}
      <Alert>{err}</Alert>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Зондов пока нет" text="Отметьте кандидатов в подборке и отправьте им короткую задачу." action={<Link to="/employer/needs" className="btn-primary">К подборкам</Link>} />
      ) : data.map((p) => (
        <article key={p.id} className="card space-y-3 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-bold text-brand-night">{p.title}</p>
              <p className="text-brand-ink/65">{p.candidate_deleted ? <><span className="font-semibold">{p.candidate_ref}</span> · кандидат удалил учётную запись</> : <><Link className="font-semibold text-brand" to={`/employer/candidates/${p.candidate_ref}`}>{p.candidate_ref}</Link> · {catTitle(p.candidate_category)}</>} · {salaryText(p.salary_from, p.salary_to, p.salary_basis)} · {dt(p.created_at)}</p>
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
          <details><summary className="cursor-pointer text-brand-ink/65">История</summary><div className="mt-2"><History items={p.events} /></div></details>
        </article>
      ))}
    </div>
  );
}

/** Ответ POST по приглашению (та же форма, что строка списка) — сразу в список, без ожидания повторного GET (В-2). */
export const replaceInvitation = (list: any[] | null, inv: any): any[] | null =>
  list && inv?.id ? list.map((x) => (x.id === inv.id ? inv : x)) : list;

export function EmployerInvitations() {
  const { data, loading, error, reload, setData } = useApi<any[]>("/employer/invitations");
  const [err, setErr] = useState<string | null>(null);
  // карточка обновляется ответом POST сразу; полный список (передачи в ATS после принятия) — следом, в фоне
  const applyUpdated = (inv?: any) => { if (inv?.id) setData((d) => replaceInvitation(d, inv)); void reload(); };
  async function withdraw(id: string) {
    try { await api(`/employer/invitations/${id}/withdraw`, { method: "POST" }); await reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Приглашения" subtitle="Статусы и история; контакты кандидата — после принятия приглашения." />
      <InvitesLeft />
      <Alert>{err}</Alert>
      <HiringReminders />
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Приглашений пока нет" text="Откройте карточку кандидата из подборки или поиска и отправьте приглашение с вилкой." />
      ) : data.map((i) => (
        <article key={i.id} className="card space-y-3 text-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-bold text-brand-night">{i.position_title}</p>
              <p className="text-brand-ink/65">{i.candidate_deleted ? <><span className="font-semibold">{i.candidate_ref}</span> · кандидат удалил учётную запись</> : <><Link className="font-semibold text-brand" to={`/employer/candidates/${i.candidate_ref}`}>{i.candidate_ref}</Link> · {catTitle(i.candidate_category)}</>} · {salaryText(i.salary_from, i.salary_to, i.salary_basis)}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {i.counter && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">Встречное ждёт решения</span>}
              <HiringChip h={i.hiring} /><AtsStageBadge s={i.ats_stage} employer /><Status s={i.contacts_revoked ? "contacts_revoked" : i.status} />
            </div>
          </div>
          {i.contacts ? (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-emerald-900">
              <p className="font-semibold">Контакты кандидата</p>
              <p className="mt-1">{[i.contacts.full_name, i.contacts.email, i.contacts.phone, i.contacts.telegram].filter(Boolean).join(" · ")}</p>
            </div>
          ) : i.contacts_revoked ? (
            <p className="rounded-xl bg-amber-50 px-3 py-2 text-amber-900">Кандидат отозвал доступ к контактам {i.contacts_revoked_at ? dt(i.contacts_revoked_at) : ""} — карточка снова обезличена, передача в ATS и PDF с контактами закрыты. Переписка — в формате «вопрос — ответ». Вернуть доступ может только кандидат.</p>
          ) : <p className="text-brand-ink/65">Контакты откроются после принятия приглашения.</p>}
          <EmploymentTermsText terms={i.employment_terms} />
          <CounterDecision inv={i} onDone={applyUpdated} />
          <AtsInvitationActions invitationId={i.id} status={i.contacts_revoked ? "contacts_revoked" : i.status} candidateRef={i.candidate_ref} transfers={i.ats_transfers} onChanged={reload} />
          <EmployerHiring inv={i} onChange={reload} />
          <AiInterviewEmployer inv={i} />
          {i.complaint ? (
            <p className="rounded-xl bg-amber-50 px-3 py-2 text-amber-900">Жалоба кандидата: <b>{i.complaint.reason_title.toLowerCase()}</b>. Жалобы снижают индекс доверия компании — его видят кандидаты.</p>
          ) : i.decline_reason && <p className="text-brand-ink/70">Причина отказа: «{i.decline_reason}»</p>}
          <InlineThread kind="invitation" id={i.id} thread={i.thread} onUpdate={reload} />
          <History items={i.history} />
          {["sent", "viewed"].includes(i.status) && <button className="text-sm font-semibold text-brand-plum hover:underline" onClick={() => withdraw(i.id)}>Отозвать</button>}
        </article>
      ))}
    </div>
  );
}

/** Встречное предложение кандидата: принять (вилка заменяется, приглашение принято, контакты открыты) или отклонить. */
function CounterDecision({ inv, onDone }: { inv: any; onDone: (updated?: any) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"" | "accept" | "decline">("");
  const [err, setErr] = useState<string | null>(null);
  const inFlight = useRef(false);  // второй клик до ответа сервера не уходит вторым POST
  const c = inv.counter;
  const decided = (inv.counters ?? []).filter((x: any) => x.status !== "pending");
  async function decide(kind: "accept" | "decline") {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(kind); setErr(null);
    try {
      // В-2: ответ — обновлённое приглашение (статус, контакты, история): карточка меняется сразу, без перезагрузки
      const updated = await api<any>(`/employer/invitations/${inv.id}/counter/${kind}`, { body: { note: note || null } });
      setNote(""); onDone(updated);
    }
    catch (e) { setErr(errText(e)); } finally { inFlight.current = false; setBusy(""); }
  }
  if (!c) {
    const last = decided[decided.length - 1];
    if (!last) return null;
    return (
      <p className="text-xs text-brand-ink/65">
        {last.status === "accepted" ? `Принято на условиях встречного предложения кандидата: ${salaryText(last.salary_from, last.salary_to, last.salary_basis)} (ваша вилка была ${salaryText(last.offer_from, last.offer_to, inv.salary_basis)}).`
          : last.status === "declined" ? `Встречное предложение ${salaryText(last.salary_from, last.salary_to, last.salary_basis)} отклонено ${dtt(last.decided_at ?? last.created_at)}; в силе ваша вилка.`
            : `Встречное предложение ${salaryText(last.salary_from, last.salary_to, last.salary_basis)} закрыто вместе с приглашением.`}
      </p>
    );
  }
  return (
    <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4" aria-label="Встречное предложение кандидата">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-brand-night">Встречное предложение кандидата</p>
          <p className="mt-1 text-lg font-extrabold text-brand-night">{salaryText(c.salary_from, c.salary_to, c.salary_basis)}</p>
          <p className="text-xs text-brand-ink/65">{otherBasis(c.salary_from, c.salary_to, c.salary_basis)} · ваша вилка: {salaryText(c.offer_from, c.offer_to, inv.salary_basis)} · {dtt(c.created_at)}</p>
        </div>
      </div>
      {c.comment && <p className="rounded-lg bg-white/80 px-3 py-2 text-brand-ink/85">«{c.comment}»</p>}
      <p className="text-xs text-brand-ink/70">Если принять — вилка приглашения заменится на встречную, приглашение станет принятым и откроются контакты кандидата (он согласился на это, отправляя встречное). Если отклонить — приглашение останется открытым с вашей вилкой: кандидат сможет принять её, отказаться или предложить ещё раз.</p>
      <input className="input" placeholder="Комментарий кандидату (необязательно)" aria-label="Комментарий кандидату к решению по встречному" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary !py-2" disabled={!!busy} aria-busy={busy === "accept"} onClick={() => decide("accept")}>{busy === "accept" ? "Принимаем…" : "Принять встречное"}</button>
        <button className="btn-ghost !py-2" disabled={!!busy} aria-busy={busy === "decline"} onClick={() => decide("decline")}>{busy === "decline" ? "Отклоняем…" : "Отклонить встречное"}</button>
      </div>
      <Alert>{err}</Alert>
    </section>
  );
}
