import { useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, History, Level, Loading, Modal, Seg, Status, cleanCompanyName, dt, dtEnd, errText, rub, ruText, useApi } from "../../components/ui";
import { Thread } from "../../components/Chat";
import { BasisSeg, SalaryLine, otherBasis, salaryText, type Basis } from "../../components/Salary";
import { api } from "../../lib/api";
import { SusPrompt } from "../../integrations/Sus";
import { InvitationTrust, TrustBadge, useInvitationsTrust } from "../../integrations/Trust";
import { VacancyGuardBadge } from "../../components/MatchExplain";
import { EmploymentTermsText } from "../../integrations/Youth";
import { AtsStageBadge } from "../../integrations/Ats";
import { CandidateHiring, HiringChip, HiringReminders } from "../../components/Hiring";
import { AiInterviewCandidate } from "../../components/Interview";  // Я15: приглашение на ИИ-интервью
import { WhyChosen } from "../mutual/Candidate";  // почему меня выбрали (Н9)
import { PartnerBadge } from "../employer/Tariffs";  // Я29: метка «Партнёр ФСП» (только при TARIFFS_ENABLED)

/** Входящие приглашения: принять (контакты откроются работодателю) или отклонить (причина — по желанию). */
export function Invitations() {
  const { data, loading, error, reload } = useApi<any[]>("/candidate/invitations");
  const [open, setOpen] = useState<any>(null);
  const [reason, setReason] = useState("");
  const [declining, setDeclining] = useState(false);
  const [complaining, setComplaining] = useState(false);
  const [cReason, setCReason] = useState<"salary" | "role" | "spam" | "other">("salary");
  const [cComment, setCComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [slot, setSlot] = useState<number | null>(null);  // KF3: выбранный слот собеседования из приглашения
  const ALL_CONTACTS = ["full_name", "email", "phone", "telegram", "github"] as const;
  const [sharedContacts, setSharedContacts] = useState<string[]>([...ALL_CONTACTS]);
  const [trustV, setTrustV] = useState(0);  // ответ и жалоба меняют индекс доверия — перечитать в открытом окне
  const trust = useInvitationsTrust(trustV);

  async function complain() {
    setErr(null);
    try {
      setOpen(await api<any>(`/candidate/invitations/${open.id}/complaint`, { body: { reason: cReason, comment: cComment || null } }));
      setComplaining(false); setTrustV((v) => v + 1); void reload();
    } catch (e) { setErr(errText(e)); }
  }
  async function view(i: any) {
    setErr(null); setDeclining(false); setComplaining(false); setReason(""); setCComment(""); setCReason("salary"); setSlot(null);
    setSharedContacts(i.shared_contacts ?? [...ALL_CONTACTS]);
    try { setOpen(await api<any>(`/candidate/invitations/${i.id}`)); void reload(); } catch (e) { setErr(errText(e)); }
  }
  async function act(kind: "accept" | "decline", slotIndex: number | null = null) {
    setErr(null);
    try {
      const body = kind === "decline"
        ? { reason: reason || null }
        : {
            ...(slotIndex != null ? { slot_index: slotIndex } : {}),
            ...(sharedContacts.length < ALL_CONTACTS.length ? { shared_contacts: sharedContacts } : {}),
          };
      const r = await api<any>(`/candidate/invitations/${open.id}/${kind}`, { body });
      setOpen(r); setTrustV((v) => v + 1); void reload();
    } catch (e) { setErr(errText(e)); }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Приглашения" subtitle="Работодатель видит ваши контакты только после того, как вы примете приглашение." />
      <HiringReminders />
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Приглашений пока нет" text="Когда работодатель пригласит вас с вилкой зарплаты, приглашение появится здесь и придёт письмом." />
      ) : (
        <ul className="space-y-3">
          {data.map((i) => (
            <li key={i.id}>
              <button onClick={() => view(i)} className="card flex w-full flex-wrap items-center justify-between gap-3 text-left transition-colors hover:border-brand/40">
                <div>
                  <p className="font-bold text-brand-night">{i.position_title}</p>
                  <p className="text-sm text-brand-ink/65">{cleanCompanyName(i.company?.name)} · {salaryText(i.salary_from, i.salary_to, i.salary_basis)} · {dt(i.created_at)}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    {i.company?.fsp_partner && <PartnerBadge on />}
                    <VacancyGuardBadge vacancy={i} trust={i.trust ?? trust[i.id]} compact />
                  </div>
                  {i.below_my_minimum && <p className="mt-1 text-xs font-semibold text-brand-plum">Верх вилки ниже вашего минимума</p>}
                  {i.counter && <p className="mt-1 text-xs font-semibold text-amber-800">Встречное условие («Да, если…») ждёт ответа работодателя</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {i.thread?.unread > 0 && <span className="rounded-full bg-brand-strong px-2 py-0.5 text-xs font-bold text-white">Новых сообщений: {i.thread.unread}</span>}
                  <TrustBadge t={trust[i.id]} compact /><HiringChip h={i.hiring} /><AtsStageBadge s={i.ats_stage} /><Status s={i.contacts_revoked ? "contacts_revoked" : i.status} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!open} onClose={() => setOpen(null)} title={open?.position_title ?? ""}>
        {open && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3"><Status s={open.status} /><AtsStageBadge s={open.ats_stage} /><span className="text-brand-ink/65">{cleanCompanyName(open.company?.name)}{open.company?.industry ? ` · ${open.company.industry}` : ""}</span><PartnerBadge on={open.company?.fsp_partner} /></div>
              <Link to={`/candidate/trio?invitation=${open.id}`} className="btn-ghost !px-3 !py-1.5 text-xs" data-testid="trio-from-invitation">
                Подключить ФСП к диалогу
              </Link>
            </div>
            <VacancyGuardBadge vacancy={open} trust={open.trust ?? trust[open.id]} />
            <SalaryLine big from={open.salary_from} to={open.salary_to} basis={open.salary_basis} />
            {open.below_my_minimum && <Alert kind="info">Верх вилки ниже вашего скрытого минимума. Работодатель этот минимум не видит.</Alert>}
            <p className="whitespace-pre-line text-brand-ink/80">{open.offer_description}</p>
            <EmploymentTermsText terms={open.employment_terms} />
            <p><b>Способ связи:</b> {open.contact_method}</p>
            <InvitationTrust invitationId={open.id} version={`${trustV}:${open.status}:${open.complaint?.at ?? ""}`} />
            <WhyChosen invitationId={open.id} />
            {open.evidence?.length > 0 && (
              <div>
                <p className="font-semibold text-brand-night">На чём основано приглашение</p>
                <ul className="mt-2 space-y-1.5">{open.evidence.map((e: any, k: number) => <li key={k} className="flex items-start gap-2"><Level level={e.level} /><span>{ruText(e.text)}</span></li>)}</ul>
              </div>
            )}
            <div>
              <p className="mb-2 font-semibold text-brand-night">Переписка с работодателем</p>
              <Thread compact kind="invitation" id={open.id} onUpdate={reload} />
            </div>
            <div><p className="mb-2 font-semibold text-brand-night">История</p><History items={open.history} /></div>
            <Alert>{err}</Alert>
            {["sent", "viewed"].includes(open.status) && !declining && !complaining && <CounterBlock inv={open} onDone={(r) => { setOpen(r); void reload(); }} />}
            {["sent", "viewed"].includes(open.status) && (
              declining ? (
                <div className="space-y-3">
                  <Field label="Причина отказа (необязательно)" htmlFor="reason">
                    <textarea id="reason" className="input min-h-[80px]" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Например, вилка ниже ожиданий" />
                  </Field>
                  <div className="flex gap-3"><button className="btn-primary" onClick={() => act("decline")}>Отклонить</button><button className="btn-ghost" onClick={() => setDeclining(false)}>Назад</button></div>
                </div>
              ) : (
                !complaining && <div className="space-y-3">
                  <SlotPicker slots={open.proposed_slots ?? []} value={slot} onChange={setSlot} />
                  <fieldset className="rounded-xl border border-brand-night/10 bg-[#F7F6FB] p-3.5" data-testid="selective-contacts">
                    <legend className="px-1 text-xs font-bold uppercase tracking-[0.08em] text-brand-night">Выборочное согласие на открытие контактов</legend>
                    <p className="text-xs text-brand-ink/65">Отметьте, какие каналы связи открыть этому работодателю при принятии приглашения (в любой момент можно отозвать в «Моих данных»):</p>
                    <div className="mt-2 flex flex-wrap gap-3 text-xs font-semibold text-brand-night">
                      {[
                        ["full_name", "Имя и фамилия"],
                        ["email", "Почта (Email)"],
                        ["phone", "Телефон"],
                        ["telegram", "Telegram"],
                        ["github", "GitHub / портфолио"],
                      ].map(([key, label]) => {
                        const checked = sharedContacts.includes(key);
                        return (
                          <label key={key} className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-white px-2.5 py-1.5 ring-1 ring-brand-night/10">
                            <input
                              type="checkbox"
                              className="accent-brand"
                              checked={checked}
                              onChange={(e) => {
                                const next = e.target.checked
                                  ? [...sharedContacts, key]
                                  : sharedContacts.filter((x) => x !== key);
                                if (next.length > 0) setSharedContacts(next);
                              }}
                            />
                            <span>{label}</span>
                          </label>
                        );
                      })}
                    </div>
                  </fieldset>
                  <div className="flex flex-wrap gap-3">
                    {(open.proposed_slots ?? []).some((x: any) => !x.past) && (
                      <button className="btn-primary" disabled={slot == null} onClick={() => act("accept", slot)} data-testid="accept-with-slot">Принять и забронировать слот</button>
                    )}
                    <button className={(open.proposed_slots ?? []).some((x: any) => !x.past) ? "btn-ghost" : "btn-primary"} onClick={() => act("accept")}>Принять и открыть контакты</button>
                    <button className="btn-ghost" onClick={() => setDeclining(true)}>Отклонить</button>
                  </div>
                </div>
              )
            )}
            {open.complaint ? (
              <Alert kind="info">Жалоба отправлена: {open.complaint.reason_title.toLowerCase()}. Она учтена в индексе доверия компании, который видят другие кандидаты.</Alert>
            ) : complaining ? (
              <div className="space-y-3 rounded-xl border border-brand-night/10 p-4">
                <p className="font-semibold text-brand-night">Пожаловаться на приглашение</p>
                <Seg label="Причина жалобы" value={cReason} onChange={setCReason} options={[
                  { id: "salary", title: "Нереальная вилка" }, { id: "role", title: "Не та роль" },
                  { id: "spam", title: "Спам" }, { id: "other", title: "Другое" }]} />
                <Field label="Комментарий (необязательно, работодатель его не увидит)" htmlFor="ccomment">
                  <textarea id="ccomment" className="input min-h-[70px]" value={cComment} onChange={(e) => setCComment(e.target.value)} placeholder="Например, на собеседовании назвали сумму вдвое ниже" />
                </Field>
                <p className="text-xs text-brand-ink/65">Жалоба снижает индекс доверия работодателя{["sent", "viewed"].includes(open.status) ? "; приглашение будет отклонено" : ""}. Одна жалоба на приглашение.</p>
                <div className="flex gap-3"><button className="btn-primary" onClick={complain}>Отправить жалобу</button><button className="btn-ghost" onClick={() => setComplaining(false)}>Назад</button></div>
              </div>
            ) : !declining && (
              <button type="button" className="text-sm font-semibold text-brand-plum hover:underline" onClick={() => setComplaining(true)}>Пожаловаться: нереальная вилка, не та роль, спам</button>
            )}
            {open.status === "accepted" && !open.contacts_revoked && <Alert kind="ok">Вы приняли приглашение. Работодатель видит ваши контакты и свяжется с вами.</Alert>}
            {open.status === "accepted" && <AiInterviewCandidate inv={open} />}
            {open.status === "accepted" && <CandidateHiring inv={open} onChange={() => { void api<any>(`/candidate/invitations/${open.id}`).then(setOpen).catch(() => undefined); void reload(); }} />}
            {open.status === "accepted" && <ContactsAccess inv={open} onDone={(r) => { setOpen(r); void reload(); }} />}
            {open.status === "accepted" && <SusPrompt context="e2e" />}
          </div>
        )}
      </Modal>
    </div>
  );
}

const MAX_RATIO = 1.5;
const r5k = (v: number) => Math.round(v / 5000) * 5000;

/** Встречное предложение: своя вилка в ответ на приглашение. Правила — как на сервере (contact/service.py). */
interface ProposedSlot { index: number; starts_at: string; duration_min: number; format: string; place?: string | null; past: boolean; text: string }
const SLOT_FORMAT: Record<string, string> = { video: "видеозвонок", phone: "телефон", office: "офис" };

/** KF3 «Оффер в один клик»: слоты собеседования из приглашения — выбрать один и принять с бронированием. */
function SlotPicker({ slots, value, onChange }: { slots: ProposedSlot[]; value: number | null; onChange: (v: number | null) => void }) {
  if (!slots.length) return null;
  const fmt = (iso: string) => new Date(iso).toLocaleString("ru-RU", { timeZone: "Europe/Moscow", weekday: "short", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
  return (
    <fieldset className="rounded-xl border border-brand-lavender/40 bg-[#F7F6FB] p-4" data-testid="invite-slots">
      <legend className="px-1 font-semibold text-brand-night">Работодатель предложил время собеседования</legend>
      <p className="text-xs text-brand-ink/65">Выберите удобный слот — собеседование назначится сразу при принятии. Время московское.</p>
      <div className="mt-2 space-y-2">
        {slots.map((s) => (
          <label key={s.index} className={`flex cursor-pointer items-start gap-3 rounded-lg bg-white px-3 py-2 ring-1 ${value === s.index ? "ring-brand" : "ring-brand-night/10"} ${s.past ? "cursor-not-allowed opacity-50" : ""}`}>
            <input type="radio" name="invite-slot" className="mt-1 accent-brand" disabled={s.past} checked={value === s.index} onChange={() => onChange(s.index)} />
            <span className="min-w-0">
              <span className="block font-semibold text-brand-night">{fmt(s.starts_at)} · {s.duration_min} мин</span>
              <span className="block text-xs text-brand-ink/70">{SLOT_FORMAT[s.format] ?? s.format}{s.place ? ` · ${s.place}` : ""}{s.past ? " · время прошло" : ""}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function CounterBlock({ inv, onDone }: { inv: any; onDone: (r: any) => void }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(() => String(inv.salary_to));
  const [to, setTo] = useState(() => String(Math.min(Math.floor(inv.salary_to * MAX_RATIO / 1000) * 1000, r5k(inv.salary_to * 1.15))));
  const [basis, setBasis] = useState<Basis>(inv.salary_basis ?? "gross");
  const [workFormat, setWorkFormat] = useState<string>("");
  const [startDate, setStartDate] = useState<string>("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const c = inv.counter;
  if (c) return (
    <Alert kind="info">
      Встречное условие («Да, если…») отправлено: <b>{salaryText(c.salary_from, c.salary_to, c.salary_basis)}</b>{c.comment ? ` · ${c.comment}` : ""}. Ждём ответа работодателя.
      Если он согласится, приглашение будет принято и откроются ваши контакты. До этого контакты скрыты.
    </Alert>
  );
  const last = inv.counters?.[inv.counters.length - 1];
  const declinedNote = last?.status === "declined" && (
    <Alert kind="info">Работодатель не принял вилку {salaryText(last.salary_from, last.salary_to, last.salary_basis)}{last.employer_note ? `: «${last.employer_note}»` : ""}. В силе исходное предложение.</Alert>
  );
  if (!inv.counters_left) return declinedNote || null;
  const f = Number(from), t = Number(to);
  const wide = f > 0 && t > f * MAX_RATIO;
  async function send() {
    setErr(null);
    if (!f || !t || f > t) { setErr("Укажите вилку «от» и «до»: нижняя граница не больше верхней"); return; }
    if (wide) { setErr(`Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от» (не выше ${rub(Math.floor(f * MAX_RATIO / 1000) * 1000)})`); return; }
    try {
      onDone(await api<any>(`/candidate/invitations/${inv.id}/counter`, {
        body: {
          salary_from: f,
          salary_to: t,
          salary_basis: basis,
          work_format: workFormat || null,
          start_date: startDate.trim() || null,
          comment: comment || null,
        },
      }));
      setOpen(false);
    } catch (e) { setErr(errText(e)); }
  }
  if (!open) return (
    <div className="space-y-2">
      {declinedNote}
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-ghost" onClick={() => setOpen(true)} data-testid="counter-open-btn">Да, если… (предложить свою вилку или условия)</button>
        <span className="text-xs text-brand-ink/65">Приглашение не отклоняется, контакты скрыты до согласия работодателя. Осталось попыток: {inv.counters_left}.</span>
      </div>
    </div>
  );
  return (
    <div className="space-y-3 rounded-xl border border-brand-night/10 p-4" data-testid="counter-form">
      <p className="font-semibold text-brand-night">«Да, если…» — встречное условие работодателю</p>
      <p className="text-xs text-brand-ink/65">Предложено: {salaryText(inv.salary_from, inv.salary_to, inv.salary_basis)}. Укажите желаемую вилку («до» — не больше чем в 1,5 раза выше «от») и при необходимости формат работы или срок выхода.</p>
      <div><p className="label">Сумма указана</p><BasisSeg value={basis} onChange={setBasis} /></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Моя вилка от, ₽ в месяц" htmlFor="cf"><input id="cf" type="number" min={1} step={5000} className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="Моя вилка до, ₽ в месяц" htmlFor="ct"><input id="ct" type="number" min={1} step={5000} className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <p className={`text-xs ${wide ? "font-semibold text-brand-plum" : "text-brand-ink/65"}`}>{wide ? `Слишком широкая вилка: при «от» ${rub(f)} «до» — не выше ${rub(Math.floor(f * MAX_RATIO / 1000) * 1000)}.` : f && t ? otherBasis(f, t, basis) : ""}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Условие по формату (необязательно)" htmlFor="cwf">
          <select id="cwf" className="input" value={workFormat} onChange={(e) => setWorkFormat(e.target.value)}>
            <option value="">как в приглашении</option>
            <option value="remote">Удалённо</option>
            <option value="hybrid">Гибрид</option>
            <option value="office">Офис</option>
          </select>
        </Field>
        <Field label="Срок выхода / график (необязательно)" htmlFor="csd">
          <input id="csd" className="input" maxLength={120} value={startDate} onChange={(e) => setStartDate(e.target.value)} placeholder="Например: выход через 2 недели" />
        </Field>
      </div>
      <Field label="Комментарий (необязательно)" htmlFor="cc">
        <textarea id="cc" className="input min-h-[70px]" maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Например, опыт с Kafka и готовность вести архитектуру" />
      </Field>
      <p className="text-xs text-brand-ink/65">Если работодатель примет встречное условие, приглашение будет принято на ваших условиях и тогда откроются выбранные контакты.</p>
      <Alert>{err}</Alert>
      <div className="flex flex-wrap gap-3"><button className="btn-primary" onClick={send}>Отправить встречное</button><button className="btn-ghost" onClick={() => setOpen(false)}>Назад</button></div>
    </div>
  );
}

/** После принятия: отозвать доступ к контактам (работодатель снова видит обезличенную карточку) или вернуть его. */
function ContactsAccess({ inv, onDone }: { inv: any; onDone: (r: any) => void }) {
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go(kind: "revoke" | "restore") {
    setErr(null);
    try { onDone(await api<any>(`/candidate/invitations/${inv.id}/contacts/${kind}`, { method: "POST" })); setConfirm(false); }
    catch (e) { setErr(errText(e)); }
  }
  if (inv.contacts_revoked) return (
    <div className="space-y-2">
      <Alert kind="info">Вы отозвали доступ к контактам {dtEnd(inv.contacts_revoked_at)}. Работодатель снова видит обезличенную карточку, переписка — в формате «вопрос — ответ».</Alert>
      <button className="btn-ghost" onClick={() => go("restore")}>Вернуть доступ к контактам</button>
      <Alert>{err}</Alert>
    </div>
  );
  return confirm ? (
    <div className="space-y-3 rounded-xl border border-brand-night/10 p-4">
      <p className="font-semibold text-brand-night">Отозвать доступ к контактам?</p>
      <p className="text-brand-ink/75">Работодатель перестанет видеть ваше имя, почту, телефон и PDF-профиль с контактами, передать вас в ATS будет нельзя. Уже сохранённое у него вне платформы отозвать нельзя.</p>
      <div className="flex flex-wrap gap-3"><button className="btn-primary" onClick={() => go("revoke")}>Отозвать доступ</button><button className="btn-ghost" onClick={() => setConfirm(false)}>Назад</button></div>
      <Alert>{err}</Alert>
    </div>
  ) : (
    <button type="button" className="text-sm font-semibold text-brand-plum hover:underline" onClick={() => setConfirm(true)}>Отозвать доступ к контактам</button>
  );
}

/** Зонды: короткие задачи от работодателей с вилкой зарплаты до раскрытия контактов. */
export function Probes() {
  const { data, loading, error, reload } = useApi<any[]>("/candidate/probes");
  const [open, setOpen] = useState<any>(null);
  const [mode, setMode] = useState<"solution" | "approach">("approach");
  const [text, setText] = useState("");
  const [link, setLink] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function view(p: any) {
    setErr(null); setText(""); setLink("");
    try {
      const r = await api<any>(`/candidate/probes/${p.id}`);
      setOpen(r); setMode(r.answer_mode === "solution" ? "solution" : "approach"); void reload();
    } catch (e) { setErr(errText(e)); }
  }
  async function submit() {
    setErr(null);
    try { setOpen(await api<any>(`/candidate/probes/${open.id}/answer`, { body: { mode, text, link: link || null } })); void reload(); }
    catch (e) { setErr(errText(e)); }
  }
  async function decline() {
    try { setOpen(await api<any>(`/candidate/probes/${open.id}/decline`, { body: {} })); void reload(); } catch (e) { setErr(errText(e)); }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Задания с вилкой от работодателей" subtitle="Короткая задача с вилкой зарплаты. Ответ решением или подходом; оценка работодателя становится подтверждённым фактом платформы." />
      <p className="text-sm text-brand-ink/70">Задания с автопроверкой — лично, к откликам и по вашему стеку — в разделе <Link className="font-semibold text-brand hover:underline" to="/candidate/assignments">«Задания для вас»</Link>.</p>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Заданий пока нет" text="Работодатели могут прислать короткую задачу до приглашения. Контакты при этом не раскрываются." />
      ) : (
        <ul className="space-y-3">
          {data.map((p) => (
            <li key={p.id}>
              <button onClick={() => view(p)} className="card flex w-full flex-wrap items-center justify-between gap-3 text-left hover:border-brand/40">
                <div>
                  <p className="font-bold text-brand-night">{p.title}</p>
                  <p className="text-sm text-brand-ink/65">{cleanCompanyName(p.company?.name)} · {salaryText(p.salary_from, p.salary_to, p.salary_basis)} · до {dt(p.deadline_at)}</p>
                </div>
                <Status s={p.status} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!open} onClose={() => setOpen(null)} title={open?.title ?? ""}>
        {open && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-3"><Status s={open.status} /><span className="text-brand-ink/65">{cleanCompanyName(open.company?.name)} · вилка {salaryText(open.salary_from, open.salary_to, open.salary_basis)} · ~{open.time_limit_min} мин</span></div>
            <p className="whitespace-pre-line rounded-xl bg-[#F3F2FB] p-4 text-brand-ink/85">{open.task_text}</p>
            {["sent", "viewed"].includes(open.status) ? (
              <div className="space-y-3">
                {open.answer_mode === "any"
                  ? <Seg label="Формат ответа" value={mode} onChange={setMode} options={[{ id: "approach", title: "Опишу подход" }, { id: "solution", title: "Пришлю решение" }]} />
                  : <p className="text-brand-ink/70">Работодатель просит {open.answer_mode === "solution" ? "решение" : "описание подхода"}.</p>}
                <Field label={mode === "solution" ? "Решение" : "Подход"} htmlFor="ans">
                  <textarea id="ans" className="input min-h-[140px] font-mono text-[13px]" value={text} onChange={(e) => setText(e.target.value)} />
                </Field>
                <Field label="Ссылка (необязательно)" htmlFor="lnk" hint="Например, на gist или репозиторий. Код на нашем сервере не запускается.">
                  <input id="lnk" className="input" value={link} onChange={(e) => setLink(e.target.value)} />
                </Field>
                <Alert>{err}</Alert>
                <div className="flex flex-wrap gap-3"><button className="btn-primary" disabled={text.trim().length < 10} onClick={submit}>Отправить ответ</button><button className="btn-ghost" onClick={decline}>Отказаться</button></div>
              </div>
            ) : open.answer ? (
              <div><p className="font-semibold text-brand-night">Ваш ответ</p><p className="mt-1 whitespace-pre-line text-brand-ink/75">{open.answer.text}</p></div>
            ) : null}
            {open.review && <Alert kind="ok">Оценка работодателя: {open.review.verdict_title}{open.review.comment ? ` — «${open.review.comment}»` : ""}</Alert>}
            <div><p className="mb-2 font-semibold text-brand-night">История</p><History items={open.events} /></div>
          </div>
        )}
      </Modal>
    </div>
  );
}
