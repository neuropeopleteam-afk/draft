// KF3 «Оффер в один клик»: приглашение из сравнения кандидатов одним окном — вилка (с ориентиром медианы hh.ru),
// предпросмотр вероятности согласия (Mutual Draft Score, POST /employer/mutual/offer-check), до трёх слотов
// собеседования (proposed_slots: кандидат бронирует слот при принятии) и альтернатива «Мало кандидатов? —
// отборочный кубок ФСП по вакансии» (POST /employer/cups/from-need/{need_id}).
// Поля заполнены заранее (позиция — из потребности, контакт — из прошлого приглашения или почты): обычно достаточно
// одного нажатия «Отправить». Для кандидата 16–17 лет — полная форма (ограничения по формату и времени, youth.py).
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Field, errText, rub, useApi, NB } from "./ui";
import { BasisSeg, MarketNote, otherBasis, type Basis } from "./Salary";
import { HhMarketNote } from "../integrations/HhImport";
import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { INVITE_MIN, InviteForm, SALARY_MAX_RATIO, defaultRange, inviteMissing, type NeedSalary } from "../pages/employer/Contact";

type Market = { from: number; to: number; median?: number | null } | null | undefined;
type SlotFormat = "video" | "phone" | "office";
interface SlotDraft { on: boolean; at: string; duration: number }
interface OfferCheck {
  level: string; title: string; line: string; score: number; known_weight: number; decline_risk: boolean;
  hint: string; salary_status: string; checks_left: number | null;
}

const LS_CONTACT = "draft.invite.contact";
const LS_PLACE = "draft.invite.place";
const FORMAT_TITLE: Record<SlotFormat, string> = { video: "Видеозвонок", phone: "Телефон", office: "Офис" };
const LEVEL_STYLE: Record<string, string> = {
  high: "border-emerald-200 bg-emerald-50 text-emerald-900",
  medium: "border-amber-200 bg-amber-50 text-amber-950",
  low: "border-brand/30 bg-brand-blush/40 text-brand-plum",
  unknown: "border-brand-night/10 bg-[#F7F6FB] text-brand-night",
};

const pad = (n: number) => String(n).padStart(2, "0");
/** Значение для input[type=datetime-local] по московскому времени (сервер читает время без пояса как МСК). */
function mskLocal(d: Date) {
  const m = new Date(d.getTime() + (3 * 60 + d.getTimezoneOffset()) * 60000);
  return `${m.getFullYear()}-${pad(m.getMonth() + 1)}-${pad(m.getDate())}T${pad(m.getHours())}:${pad(m.getMinutes())}`;
}
/** Три слота по умолчанию: ближайшие рабочие дни, 11:00 и 16:00 по Москве. */
export function defaultSlots(now = new Date()): SlotDraft[] {
  const out: SlotDraft[] = [];
  const day = new Date(now.getTime());
  const hours = [11, 16, 11];
  while (out.length < 3) {
    day.setDate(day.getDate() + 1);
    const wd = new Date(day.getTime() + (3 * 60 + day.getTimezoneOffset()) * 60000).getDay();
    if (wd === 0 || wd === 6) continue;
    for (const h of out.length === 0 ? [hours[0], hours[1]] : [hours[2]]) {
      if (out.length >= 3) break;
      const [d] = mskLocal(day).split("T");
      out.push({ on: true, at: `${d}T${pad(h)}:00`, duration: 60 });
    }
  }
  return out;
}

const salaryError = (from: string, to: string) => {
  const f = Number(from), t = Number(to);
  if (!f || !t || f <= 0 || t <= 0) return "Укажите вилку «от» и «до» — это обязательно";
  if (f > t) return "Нижняя граница вилки больше верхней";
  if (t > f * 3.5) return "Слишком широкая вилка (разрыв более 3,5×): такие предложения выглядят размыто и снижают доверие кандидатов. Укажите диапазон с разрывом до 1,5×";
  if (t > f * SALARY_MAX_RATIO) return "Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от»";
  return null;
};

export function InviteDialog({ cref, needId, needTitle, market, needSalary, onDone }: {
  cref: string; needId?: string | null; needTitle?: string | null; market: Market; needSalary?: NeedSalary; onDone: (inv: any) => void;
}) {
  const { me } = useAuth();
  const navigate = useNavigate();
  const candidate = useApi<any>(`/employer/candidates/${cref}`);
  const safety = candidate.data?.employment_safety;
  const [full, setFull] = useState(false);
  const [title, setTitle] = useState(needTitle ?? "");
  const [desc, setDesc] = useState(() => needTitle
    ? `Приглашаем на позицию «${needTitle}». Ваш подтверждённый тестом и заданиями профиль совпал с требованиями вакансии — обсудим задачи и условия на коротком собеседовании.`
    : "");
  const [contact, setContact] = useState(() => localStorage.getItem(LS_CONTACT) ?? "");
  useEffect(() => { if (!contact && me?.email) setContact(me.email); }, [me?.email]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [range] = useState(() => defaultRange(market, needSalary));
  const [from, setFrom] = useState(range[0]);
  const [to, setTo] = useState(range[1]);
  const [basis, setBasis] = useState<Basis>(needSalary?.net ? "net" : "gross");
  const [slots, setSlots] = useState<SlotDraft[]>(() => defaultSlots());
  const [place, setPlace] = useState(() => localStorage.getItem(LS_PLACE) ?? "");
  const [fmt, setFmt] = useState<SlotFormat>(() => (localStorage.getItem(LS_PLACE) ? "video" : "phone"));
  const [err, setErr] = useState<string | null>(null);
  const [limitHit, setLimitHit] = useState(false);
  const [sending, setSending] = useState(false);
  const [cupBusy, setCupBusy] = useState(false);
  const inFlight = useRef(false);

  // --- Mutual Draft Score: вероятность согласия кандидата с этой вилкой (минимум кандидата не раскрывается)
  const [fit, setFit] = useState<OfferCheck | null>(null);
  const [fitErr, setFitErr] = useState<string | null>(null);
  const seq = useRef(0);
  const toN = Number(to) || 0, fromN = Number(from) || 0;
  const fitKey = useMemo(() => (toN >= 10000 && (!fromN || fromN <= toN) ? `${cref}|${needId ?? ""}|${Math.floor(toN / 10000)}|${basis}` : ""), [cref, needId, toN, fromN, basis]);
  useEffect(() => {
    if (!fitKey) { setFit(null); return; }
    const my = ++seq.current;
    const t = setTimeout(() => {
      api<OfferCheck>("/employer/mutual/offer-check", { body: { candidate_ref: cref, need_id: needId || null, salary_from: fromN || null, salary_to: toN, salary_basis: basis } })
        .then((r) => { if (my === seq.current) { setFit(r); setFitErr(null); } })
        .catch((e) => { if (my === seq.current) { setFit(null); setFitErr(errText(e)); } });
    }, 700);
    return () => clearTimeout(t);
  }, [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (full || (safety?.minor)) {
    return (
      <div className="space-y-3">
        {safety?.minor && <Alert kind="info">Кандидату 16–17 лет: для него — полная форма с ограничениями по формату и времени работы.</Alert>}
        <InviteForm cref={cref} needId={needId} market={market} needSalary={needSalary} onDone={onDone} />
      </div>
    );
  }

  const chosen = slots.filter((s) => s.on);
  const missing = inviteMissing({ title, desc, contact, format: "employment", reduced: false, ack: false });
  const slotProblems: string[] = [];
  if (chosen.length) {
    if (fmt === "video" && !/^https:\/\/\S+$/.test(place.trim())) slotProblems.push("ссылку на видеозвонок https://… (или выберите «Телефон»)");
    if (fmt === "office" && place.trim().length < 3) slotProblems.push("адрес офиса для собеседования");
    if (new Set(chosen.map((s) => s.at)).size !== chosen.length) slotProblems.push("разное время слотов — сейчас повторяются");
    if (chosen.some((s) => !s.at)) slotProblems.push("дату и время каждого отмеченного слота");
  }
  const salErr = salaryError(from, to);
  const blocked = missing.length > 0 || slotProblems.length > 0 || !!salErr || candidate.loading || !!candidate.error;

  async function send() {
    if (inFlight.current || blocked) return;
    inFlight.current = true; setSending(true); setErr(null); setLimitHit(false);
    try {
      const proposed_slots = chosen.map((s) => ({ starts_at: s.at, duration_min: s.duration, format: fmt, place: fmt === "phone" ? null : place.trim() || null }));
      const inv = await api<any>("/employer/invitations", { body: {
        candidate_ref: cref, need_id: needId ?? null, position_title: title.trim(), offer_description: desc.trim(), contact_method: contact.trim(),
        salary_from: Number(from), salary_to: Number(to), salary_basis: basis,
        employment_terms: { format: "employment", reduced_time: false, employer_acknowledged: false }, proposed_slots,
      } });
      try { localStorage.setItem(LS_CONTACT, contact.trim()); if (fmt !== "phone" && place.trim()) localStorage.setItem(LS_PLACE, place.trim()); } catch { /* приватный режим */ }
      onDone(inv);
    } catch (e) { setErr(errText(e)); setLimitHit(e instanceof ApiError && e.code === "tariff_limit"); } finally { inFlight.current = false; setSending(false); }
  }

  async function launchCup() {
    if (!needId) return;
    setCupBusy(true); setErr(null);
    try {
      const cup = await api<any>(`/employer/cups/from-need/${needId}`, { body: {} });
      navigate(`/employer/cups/${cup.id}`);
    } catch (e) { setErr(errText(e)); setCupBusy(false); }
  }

  const score = fit ? Math.round(Math.max(0, Math.min(1, fit.score)) * 100) : null;
  const wide = fromN > 0 && toN > fromN * SALARY_MAX_RATIO;
  return (
    <div className="space-y-5" data-testid="invite-dialog">
      <p className="text-sm text-brand-ink/75">Всё заполнено по потребности — проверьте и отправьте одним нажатием. Кандидат увидит компанию, вилку и слоты собеседования и сможет сразу забронировать удобное время.</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Позиция" htmlFor="kf3-title"><input id="kf3-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Как с вами связаться" htmlFor="kf3-contact"><input id="kf3-contact" className="input" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Telegram @hr_company или hr@company.ru" /></Field>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer font-semibold text-brand-plum">Суть предложения ({desc.trim().length} / {INVITE_MIN.desc}+ знаков)</summary>
        <textarea aria-label="Суть предложения" className="input mt-2 min-h-[90px]" value={desc} onChange={(e) => setDesc(e.target.value)} />
      </details>

      {/* ---- вилка + ориентир медианы */}
      <section aria-labelledby="kf3-salary" className="space-y-2 rounded-2xl border border-brand-night/10 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="kf3-salary" className="font-bold text-brand-night">Вилка зарплаты</h3>
          <BasisSeg value={basis} onChange={setBasis} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={fromN > 0 ? `От, ₽ в месяц (${rub(fromN)})` : "От, ₽ в месяц"} htmlFor="kf3-from"><input id="kf3-from" type="number" min={1} step={5000} className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label={toN > 0 ? `До, ₽ в месяц (${rub(toN)})` : "До, ₽ в месяц"} htmlFor="kf3-to"><input id="kf3-to" type="number" min={1} step={5000} className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
        <p className={`text-xs ${wide ? "font-semibold text-brand-plum" : "text-brand-ink/65"}`}>{wide ? "Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от»." : otherBasis(fromN, toN, basis) ?? "«До» — не больше чем в 1,5 раза выше «от»."}</p>
        {market?.median ? <p className="text-xs text-brand-ink/75" data-testid="kf3-median">Ориентир рынка: медиана категории {rub(market.median)} в месяц{toN && market.median ? ` · ваш верх вилки ${toN >= market.median ? "выше" : "ниже"} медианы на ${Math.abs(Math.round((toN / market.median - 1) * 100))}${NB}%` : ""}.</p> : <MarketNote m={market} short />}
        <HhMarketNote cref={cref} needId={needId} title="Медиана вакансий на hh.ru" />
      </section>

      {/* ---- Mutual Draft Score */}
      <section aria-labelledby="kf3-mds" aria-live="polite" className={`rounded-2xl border p-4 ${LEVEL_STYLE[fit?.level ?? "unknown"] ?? LEVEL_STYLE.unknown}`} data-testid="kf3-mutual">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="kf3-mds" className="font-bold">Mutual Draft Score — вероятность согласия</h3>
          {score != null && <p className="text-3xl font-extrabold tabular-nums">{score}<span className="text-base font-semibold">{NB}%</span></p>}
        </div>
        {fit ? <>
          <p className="mt-1 text-sm font-semibold">{fit.salary_status === "bad" ? "С такой вилкой кандидат, вероятно, откажет" : fit.hint || fit.title}</p>
          <p className="mt-1 text-sm opacity-85">{fit.hint && fit.line?.startsWith(`${fit.hint} · `) ? fit.line.slice(fit.hint.length + 3) : fit.line}</p>
          <p className="mt-1 text-xs opacity-70">Минимум кандидата не раскрывается: сравнивается только верх вилки.{fit.checks_left != null ? ` Проверок вилки на сегодня: ${fit.checks_left}.` : " Лимит проверок вилки на сегодня исчерпан."}</p>
        </> : <p className="mt-1 text-sm opacity-75">{fitErr ?? (fitKey ? "Считаем по интересам кандидата…" : "Укажите вилку — покажем, насколько предложение подходит кандидату.")}</p>}
      </section>

      {/* ---- слоты собеседования */}
      <section aria-labelledby="kf3-slots" className="space-y-3 rounded-2xl border border-brand-night/10 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="kf3-slots" className="font-bold text-brand-night">Слоты собеседования <span className="font-normal text-brand-ink/60">(до 3, московское время)</span></h3>
          <div role="radiogroup" aria-label="Формат собеседования" className="flex gap-1">
            {(Object.keys(FORMAT_TITLE) as SlotFormat[]).map((f) => (
              <button key={f} type="button" role="radio" aria-checked={fmt === f} onClick={() => setFmt(f)}
                className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${fmt === f ? "bg-brand-night text-white" : "bg-[#F3F2FB] text-brand-night hover:bg-brand-blush/50"}`}>{FORMAT_TITLE[f]}</button>
            ))}
          </div>
        </div>
        <ul className="space-y-2">
          {slots.map((s, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2">
              <input type="checkbox" id={`kf3-slot-on-${i}`} checked={s.on} onChange={(e) => setSlots(slots.map((x, j) => (j === i ? { ...x, on: e.target.checked } : x)))} className="h-4 w-4 accent-brand" />
              <label htmlFor={`kf3-slot-at-${i}`} className="w-14 text-sm font-semibold text-brand-night">Слот {i + 1}</label>
              <input id={`kf3-slot-at-${i}`} type="datetime-local" className="input !w-auto flex-1" value={s.at} disabled={!s.on} onChange={(e) => setSlots(slots.map((x, j) => (j === i ? { ...x, at: e.target.value } : x)))} />
              <select aria-label={`Длительность слота ${i + 1}`} className="input !w-auto" value={s.duration} disabled={!s.on} onChange={(e) => setSlots(slots.map((x, j) => (j === i ? { ...x, duration: Number(e.target.value) } : x)))}>
                {[30, 45, 60, 90].map((m) => <option key={m} value={m}>{m} мин</option>)}
              </select>
            </li>
          ))}
        </ul>
        {fmt !== "phone" && (
          <Field label={fmt === "video" ? "Ссылка на видеозвонок" : "Адрес офиса"} htmlFor="kf3-place">
            <input id="kf3-place" className="input" value={place} onChange={(e) => setPlace(e.target.value)} placeholder={fmt === "video" ? "https://telemost.yandex.ru/j/…" : "Москва, ул. …, офис …"} />
          </Field>
        )}
        <p className="text-xs text-brand-ink/65">{chosen.length ? `Кандидат выберет один из ${chosen.length} слотов при принятии — собеседование сразу будет назначено.` : "Без слотов: время собеседования согласуете после принятия приглашения."}</p>
      </section>

      <Alert>{err && <>{err}{limitHit && <> <Link to="/employer/tariffs" className="font-semibold underline">Открыть тарифы</Link></>}</>}</Alert>
      {(missing.length > 0 || slotProblems.length > 0 || salErr) && (
        <div className="rounded-xl bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-950 ring-1 ring-amber-200" data-testid="kf3-missing" aria-live="polite">
          <p className="font-semibold">Чтобы отправить, укажите:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {salErr && <li>{salErr}</li>}
            {missing.map((m) => <li key={m.field}>{m.text}</li>)}
            {slotProblems.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={blocked || sending} aria-busy={sending || undefined} onClick={() => void send()} data-testid="kf3-send">
          {sending ? "Отправляем…" : chosen.length ? `Отправить приглашение со слотами (${chosen.length})` : "Отправить приглашение"}
        </button>
        <button type="button" className="text-sm font-semibold text-brand-plum hover:text-brand" onClick={() => setFull(true)}>Полная форма</button>
      </div>
      {candidate.error && <Alert>{candidate.error}</Alert>}

      {needId && (
        <section className="relative overflow-hidden rounded-2xl bg-brand-night p-4 text-white" aria-labelledby="kf3-cup">
          <span className="pointer-events-none absolute inset-y-0 left-0 w-1.5 bg-brand" aria-hidden="true" />
          <div className="flex flex-wrap items-center justify-between gap-3 pl-2">
            <div className="min-w-0">
              <h3 id="kf3-cup" className="font-bold">Мало кандидатов?</h3>
              <p className="mt-0.5 text-sm text-white/80">Запустите отборочный кубок ФСП по этой вакансии: задания с автопроверкой под стек, приз — прямой оффер с вашей вилкой.</p>
            </div>
            <button type="button" className="rounded-xl bg-white px-4 py-2 text-sm font-bold text-brand-night hover:bg-white/90 disabled:opacity-60" disabled={cupBusy} onClick={() => void launchCup()} data-testid="kf3-cup">
              {cupBusy ? "Запускаем…" : "Запустить отборочный кубок ФСП по вакансии"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
