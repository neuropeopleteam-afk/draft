import { useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, History, Level, Loading, Modal, Seg, Status, dt, errText, rub, ruText, useApi } from "../../components/ui";
import { Thread } from "../../components/Chat";
import { BasisSeg, SalaryLine, otherBasis, salaryText, type Basis } from "../../components/Salary";
import { api } from "../../lib/api";
import { SusPrompt } from "../../integrations/Sus";
import { InvitationTrust, TrustBadge, useInvitationsTrust } from "../../integrations/Trust";
import { EmploymentTermsText } from "../../integrations/Youth";
import { AtsStageBadge } from "../../integrations/Ats";

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
    setErr(null); setDeclining(false); setComplaining(false); setReason(""); setCComment(""); setCReason("salary");
    try { setOpen(await api<any>(`/candidate/invitations/${i.id}`)); void reload(); } catch (e) { setErr(errText(e)); }
  }
  async function act(kind: "accept" | "decline") {
    setErr(null);
    try {
      const r = await api<any>(`/candidate/invitations/${open.id}/${kind}`, { body: kind === "decline" ? { reason: reason || null } : {} });
      setOpen(r); setTrustV((v) => v + 1); void reload();
    } catch (e) { setErr(errText(e)); }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Приглашения" subtitle="Работодатель видит ваши контакты только после того, как вы примете приглашение." />
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Приглашений пока нет" text="Когда работодатель пригласит вас с вилкой зарплаты, приглашение появится здесь и придёт письмом." />
      ) : (
        <ul className="space-y-3">
          {data.map((i) => (
            <li key={i.id}>
              <button onClick={() => view(i)} className="card flex w-full flex-wrap items-center justify-between gap-3 text-left transition-colors hover:border-brand/40">
                <div>
                  <p className="font-bold text-brand-night">{i.position_title}</p>
                  <p className="text-sm text-brand-ink/65">{i.company?.name} · {salaryText(i.salary_from, i.salary_to, i.salary_basis)} · {dt(i.created_at)}</p>
                  {i.below_my_minimum && <p className="mt-1 text-xs font-semibold text-brand-plum">Верх вилки ниже вашего минимума</p>}
                  {i.counter && <p className="mt-1 text-xs font-semibold text-amber-800">Встречное предложение ждёт ответа работодателя</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {i.thread?.unread > 0 && <span className="rounded-full bg-brand-strong px-2 py-0.5 text-xs font-bold text-white">Новых сообщений: {i.thread.unread}</span>}
                  <TrustBadge t={trust[i.id]} compact /><AtsStageBadge s={i.ats_stage} /><Status s={i.contacts_revoked ? "contacts_revoked" : i.status} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!open} onClose={() => setOpen(null)} title={open?.position_title ?? ""}>
        {open && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-3"><Status s={open.status} /><AtsStageBadge s={open.ats_stage} /><span className="text-brand-ink/65">{open.company?.name}{open.company?.industry ? ` · ${open.company.industry}` : ""}</span></div>
            <SalaryLine big from={open.salary_from} to={open.salary_to} basis={open.salary_basis} />
            {open.below_my_minimum && <Alert kind="info">Верх вилки ниже вашего скрытого минимума. Работодатель этот минимум не видит.</Alert>}
            <p className="whitespace-pre-line text-brand-ink/80">{open.offer_description}</p>
            <EmploymentTermsText terms={open.employment_terms} />
            <p><b>Способ связи:</b> {open.contact_method}</p>
            <InvitationTrust invitationId={open.id} version={`${trustV}:${open.status}:${open.complaint?.at ?? ""}`} />
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
                !complaining && <div className="flex flex-wrap gap-3">
                  <button className="btn-primary" onClick={() => act("accept")}>Принять и открыть контакты</button>
                  <button className="btn-ghost" onClick={() => setDeclining(true)}>Отклонить</button>
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
function CounterBlock({ inv, onDone }: { inv: any; onDone: (r: any) => void }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(() => String(inv.salary_to));
  const [to, setTo] = useState(() => String(Math.min(Math.floor(inv.salary_to * MAX_RATIO / 1000) * 1000, r5k(inv.salary_to * 1.15))));
  const [basis, setBasis] = useState<Basis>(inv.salary_basis ?? "gross");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const c = inv.counter;
  if (c) return (
    <Alert kind="info">
      Встречное предложение отправлено: <b>{salaryText(c.salary_from, c.salary_to, c.salary_basis)}</b>. Ждём ответа работодателя.
      Если он согласится, приглашение будет принято и откроются ваши контакты. Пока можно принять исходную вилку или отклонить приглашение.
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
    try { onDone(await api<any>(`/candidate/invitations/${inv.id}/counter`, { body: { salary_from: f, salary_to: t, salary_basis: basis, comment: comment || null } })); setOpen(false); }
    catch (e) { setErr(errText(e)); }
  }
  if (!open) return (
    <div className="space-y-2">
      {declinedNote}
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-ghost" onClick={() => setOpen(true)}>Предложить свою вилку</button>
        <span className="text-xs text-brand-ink/65">Встречное предложение: работодатель примет или отклонит. Осталось попыток: {inv.counters_left}.</span>
      </div>
    </div>
  );
  return (
    <div className="space-y-3 rounded-xl border border-brand-night/10 p-4">
      <p className="font-semibold text-brand-night">Встречное предложение</p>
      <p className="text-xs text-brand-ink/65">Предложено: {salaryText(inv.salary_from, inv.salary_to, inv.salary_basis)}. Ваша вилка должна быть выше хотя бы одной границей, «до» — не больше чем в 1,5 раза выше «от».</p>
      <div><p className="label">Сумма указана</p><BasisSeg value={basis} onChange={setBasis} /></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Моя вилка от, ₽ в месяц" htmlFor="cf"><input id="cf" type="number" min={1} step={5000} className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="Моя вилка до, ₽ в месяц" htmlFor="ct"><input id="ct" type="number" min={1} step={5000} className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <p className={`text-xs ${wide ? "font-semibold text-brand-plum" : "text-brand-ink/65"}`}>{wide ? `Слишком широкая вилка: при «от» ${rub(f)} «до» — не выше ${rub(Math.floor(f * MAX_RATIO / 1000) * 1000)}.` : f && t ? otherBasis(f, t, basis) : ""}</p>
      <Field label="Комментарий (необязательно)" htmlFor="cc">
        <textarea id="cc" className="input min-h-[70px]" maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Например, опыт с Kafka и выход через две недели" />
      </Field>
      <p className="text-xs text-brand-ink/65">Если работодатель примет встречное предложение, приглашение будет принято на ваших условиях и работодатель увидит ваши контакты.</p>
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
      <Alert kind="info">Вы отозвали доступ к контактам {dt(inv.contacts_revoked_at)}. Работодатель снова видит обезличенную карточку, переписка — в формате «вопрос — ответ».</Alert>
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
      <PageTitle title="Задания от работодателей" subtitle="Зонд — короткая задача с вилкой зарплаты. Ответ решением или подходом; оценка работодателя становится подтверждённым фактом (T1)." />
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
                  <p className="text-sm text-brand-ink/65">{p.company?.name} · {salaryText(p.salary_from, p.salary_to, p.salary_basis)} · до {dt(p.deadline_at)}</p>
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
            <div className="flex flex-wrap items-center gap-3"><Status s={open.status} /><span className="text-brand-ink/65">{open.company?.name} · вилка {salaryText(open.salary_from, open.salary_to, open.salary_basis)} · ~{open.time_limit_min} мин</span></div>
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
