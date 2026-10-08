import { useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, History, Level, Loading, Modal, Seg, Status, dt, errText, range, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { SusPrompt } from "../../integrations/Sus";
import { InvitationTrust, TrustBadge, useInvitationsTrust } from "../../integrations/Trust";
import { EmploymentTermsText } from "../../integrations/Youth";

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
  const trust = useInvitationsTrust();

  async function complain() {
    setErr(null);
    try {
      setOpen(await api<any>(`/candidate/invitations/${open.id}/complaint`, { body: { reason: cReason, comment: cComment || null } }));
      setComplaining(false); void reload();
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
      setOpen(r); void reload();
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
                  <p className="text-sm text-brand-ink/65">{i.company?.name} · {range(i.salary_from, i.salary_to)} · {dt(i.created_at)}</p>
                  {i.below_my_minimum && <p className="mt-1 text-xs font-semibold text-brand-plum">Верх вилки ниже вашего минимума</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2"><TrustBadge t={trust[i.id]} compact /><Status s={i.status} /></div>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!open} onClose={() => setOpen(null)} title={open?.position_title ?? ""}>
        {open && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-3"><Status s={open.status} /><span className="text-brand-ink/65">{open.company?.name}{open.company?.industry ? ` · ${open.company.industry}` : ""}</span></div>
            <p className="text-2xl font-extrabold text-brand-night">{range(open.salary_from, open.salary_to)}</p>
            {open.below_my_minimum && <Alert kind="info">Верх вилки ниже вашего скрытого минимума. Работодатель этот минимум не видит.</Alert>}
            <p className="whitespace-pre-line text-brand-ink/80">{open.offer_description}</p>
            <EmploymentTermsText terms={open.employment_terms} />
            <p><b>Способ связи:</b> {open.contact_method}</p>
            <InvitationTrust invitationId={open.id} />
            {open.evidence?.length > 0 && (
              <div>
                <p className="font-semibold text-brand-night">На чём основано приглашение</p>
                <ul className="mt-2 space-y-1.5">{open.evidence.map((e: any, k: number) => <li key={k} className="flex items-start gap-2"><Level level={e.level} /><span>{e.text}</span></li>)}</ul>
              </div>
            )}
            <div><p className="mb-2 font-semibold text-brand-night">История</p><History items={open.history} /></div>
            <Alert>{err}</Alert>
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
            {open.status === "accepted" && <Alert kind="ok">Вы приняли приглашение. Работодатель видит ваши контакты и свяжется с вами.</Alert>}
            {open.status === "accepted" && <SusPrompt context="e2e" />}
          </div>
        )}
      </Modal>
    </div>
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
                  <p className="text-sm text-brand-ink/65">{p.company?.name} · {range(p.salary_from, p.salary_to)} · до {dt(p.deadline_at)}</p>
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
            <div className="flex flex-wrap items-center gap-3"><Status s={open.status} /><span className="text-brand-ink/65">{open.company?.name} · вилка {range(open.salary_from, open.salary_to)} · ~{open.time_limit_min} мин</span></div>
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
