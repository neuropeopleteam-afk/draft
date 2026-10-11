import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CandidateCard } from "../../components/CandidateCard";
import { InterviewEmployerDetails } from "../../components/Interview";  // Я15: устная защита и ИИ-интервью
import { PageTitle } from "../../components/CabinetLayout";
import { StatusCounts } from "../../components/GradeStatus";
import { Alert, DIRECTIONS, Empty, Field, GRADES, LevelLegend, Loading, Modal, Seg, Status, Toggle, dt, useApi } from "../../components/ui";
import { apiDownload } from "../../lib/api";
import { InviteForm, ProbeForm, inviteBlockedText, inviteSentText, probeSentText } from "./Contact";
import { useTags } from "./Needs";
import { PassportEmployerBadge } from "../../passport/Share";
import { EmployerAttempts } from "../../components/AttemptsCompare";
import { EmployerEvidence } from "../../components/OpenEvidence";  // цитаты из ответа

const PAGE = 20;

export function Search() {
  const tags = useTags();
  const [direction, setDirection] = useState("");
  const [grade, setGrade] = useState("");
  const [stack, setStack] = useState<string[]>([]);
  const [level, setLevel] = useState<"any" | "t1">("any");
  const [fsp, setFsp] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [add, setAdd] = useState("");
  const [page, setPage] = useState(0);
  const qs = new URLSearchParams();
  if (direction) qs.set("direction", direction);
  if (grade) qs.set("grade", grade);
  stack.forEach((s) => qs.append("stack", s));
  qs.set("stack_level", level);
  if (fsp) qs.set("fsp", "true");
  if (confirmed) qs.set("confirmed", "true");
  qs.set("limit", String(PAGE));
  if (page) qs.set("offset", String(page * PAGE));
  const { data, loading, error } = useApi<any>(`/employer/candidates?${qs.toString()}`);
  const cats = useApi<any[]>("/employer/categories");
  const avail = Object.values(tags).filter((t: any) => !direction || !t.direction_id || t.direction_id === direction);

  return (
    <div className="max-w-6xl space-y-6">
      <PageTitle title="Поиск по базе" subtitle="Все кандидаты с согласием на публикацию: с подтверждённым грейдом, «предварительно» и без подтверждённого грейда — последние всегда ниже. Карточки обезличены." />
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <aside className="card h-fit space-y-4">
          <Field label="Специализация" htmlFor="sd">
            <select id="sd" className="input" value={direction} onChange={(e) => { setDirection(e.target.value); setStack([]); setPage(0); }}>
              <option value="">все</option>{Object.entries(DIRECTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="Грейд" htmlFor="sg">
            <select id="sg" className="input" value={grade} onChange={(e) => { setGrade(e.target.value); setPage(0); }}>
              <option value="">все</option>{Object.entries(GRADES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <div>
            <p className="label">Стек</p>
            <div className="flex flex-wrap gap-1.5">
              {stack.map((s) => <button key={s} className="rounded-full border border-brand bg-brand-blush/50 px-2.5 py-1 text-xs font-semibold" onClick={() => { setStack(stack.filter((x) => x !== s)); setPage(0); }} aria-label={`Убрать ${(tags as any)[s]?.title ?? s}`}>{(tags as any)[s]?.title ?? s} ✕</button>)}
            </div>
            <select aria-label="Добавить технологию" className="input mt-2" value={add} onChange={(e) => { if (e.target.value) { setStack([...stack, e.target.value]); setPage(0); } setAdd(""); }}>
              <option value="">добавить…</option>{avail.filter((t: any) => !stack.includes(t.id)).map((t: any) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
            {stack.length > 0 && <div className="mt-2"><Seg label="Уровень навыка" value={level} onChange={setLevel} options={[{ id: "any", title: "Заявлен или подтверждён" }, { id: "t1", title: "Подтверждён (T1)" }]} /></div>}
          </div>
          <Toggle checked={fsp} onChange={(v) => { setFsp(v); setPage(0); }} label="Есть паспорт ФСП" />
          <Toggle checked={confirmed} onChange={(v) => { setConfirmed(v); setPage(0); }} label="Только подтверждённый грейд"
            hint="Без «Junior (предварительно)» и без кандидатов, чей грейд не подтверждён тестом. По умолчанию они показаны со статусом ниже подтверждённых." />
          {cats.data && (
            <div className="hidden border-t border-brand-night/10 pt-3 text-xs text-brand-ink/65 lg:block">
              <p className="mb-1 font-semibold text-brand-night">Кандидатов по категориям</p>
              <ul className="grid grid-cols-1 gap-0.5">{cats.data.filter((c) => !direction || c.direction === direction).map((c) => (
                <li key={c.id} className="flex justify-between gap-2"><span>{c.title}</span>
                  <span title={`подтверждённых ${c.count - (c.provisional ?? 0)}${c.provisional ? `, предварительно ${c.provisional}` : ""}${c.unconfirmed ? `, грейд не подтверждён ${c.unconfirmed}` : ""}`}>
                    {c.count}{c.unconfirmed ? <span className="text-brand-ink/65"> +{c.unconfirmed}</span> : null}
                  </span>
                </li>
              ))}</ul>
              <p className="mt-1 text-brand-ink/65">+n — заявили категорию, грейд не подтверждён</p>
            </div>
          )}
        </aside>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-brand-ink/70" aria-live="polite">Найдено: <b>{data?.total ?? "…"}</b>{data?.total > PAGE && <> · показаны {page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)}</>}</p>
              {data && <StatusCounts confirmed={data.confirmed} provisional={data.provisional} unconfirmed={data.unconfirmed} hiddenNote={confirmed} />}
            </div>
            <LevelLegend />
          </div>
          {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.items.length ? <Empty title="Никого не нашлось" text="Ослабьте фильтры." /> :
            <>
              {data.items.map((c: any) => <CandidateCard key={c.ref} c={c} compact actions={<Link className="btn-ghost !py-2" to={`/employer/candidates/${c.ref}?direction=${c.direction}`}>Открыть</Link>} />)}
              {data.total > PAGE && (
                <nav className="flex flex-wrap items-center justify-between gap-3 pt-2" aria-label="Страницы результатов">
                  <button className="btn-ghost" disabled={page === 0 || loading} onClick={() => { setPage(page - 1); window.scrollTo({ top: 0 }); }}>← Предыдущие</button>
                  <span className="text-sm text-brand-ink/70">Страница {page + 1} из {Math.ceil(data.total / PAGE)}</span>
                  <button className="btn-ghost" disabled={(page + 1) * PAGE >= data.total || loading} onClick={() => { setPage(page + 1); window.scrollTo({ top: 0 }); }}>Следующие →</button>
                </nav>
              )}
            </>}
        </div>
      </div>
    </div>
  );
}

/** Карточка кандидата: факты, взаимодействия компании, зонд и приглашение. */
export function CandidateDetail() {
  const { ref } = useParams();
  const [params] = useSearchParams();
  const need = params.get("need");
  const direction = params.get("direction");
  const qs = new URLSearchParams();
  if (need) qs.set("need_id", need);
  if (direction) qs.set("direction", direction);
  const { data: c, loading, error, reload } = useApi<any>(`/employer/candidates/${ref}?${qs.toString()}`);
  const [modal, setModal] = useState<"" | "probe" | "invite">("");
  const [msg, setMsg] = useState<string | null>(null);
  // бюджет потребности — потолок вилки по умолчанию в зонде и приглашении
  const needReq = useApi<any>(need ? `/employer/needs/${need}` : null).data?.requirements;
  const needSalary = needReq ? { from: needReq.salary_from, to: needReq.salary_to, net: needReq.salary_net } : undefined;
  if (loading && !c) return <Loading />;
  if (error || !c) return <Alert>{error}</Alert>;
  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title={`Кандидат ${c.ref}`} subtitle={c.contacts ? "Кандидат принял ваше приглашение — контакты открыты." : c.contacts_revoked ? `Обезличенная карточка. ${c.contacts_note}.` : "Обезличенная карточка. Контакты откроются после принятия приглашения."} />
        <button className="btn-ghost" onClick={() => apiDownload(`/employer/candidates/${c.ref}/profile.pdf`, `profile-${c.ref}.pdf`)}>PDF-профиль</button>
      </div>
      {c.contacts_revoked && !c.contacts && (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-900">
          <p className="flex flex-wrap items-center gap-2 font-bold">Контакты скрыты <Status s="contacts_revoked" /></p>
          <p className="mt-1 text-sm">{c.contacts_note}: имя, почта, телефон и PDF с контактами снова недоступны, передача в ATS закрыта. Переписка по приглашению — в формате «вопрос — ответ». Вернуть доступ может только кандидат.</p>
        </section>
      )}
      {c.contacts && (
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-emerald-900">
          <p className="font-bold">Контакты</p>
          <p className="mt-1 text-sm">{[c.contacts.full_name, c.contacts.email, c.contacts.phone, c.contacts.telegram].filter(Boolean).join(" · ")}</p>
        </section>
      )}
      <CandidateCard c={c} score={c.match?.score} reasons={c.match?.reasons} must={c.match?.must} core={c.match?.core}
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-ghost" onClick={() => setModal("probe")}>Отправить зонд</button>
            <button className="btn-primary" disabled={!c.can_invite} title={c.can_invite ? undefined : inviteBlockedText(c)} aria-describedby={c.can_invite ? undefined : "invite-why"} onClick={() => setModal("invite")}>Пригласить</button>
            {/* Я11 (С3-6): почему «Пригласить» неактивна — рядом с кнопкой, а не только ниже по странице */}
            {!c.can_invite && <p id="invite-why" className="basis-full text-xs text-brand-ink/65">{inviteBlockedText(c)}</p>}
          </div>
        } />
      {/* Ф6: итог зонда/приглашения — сразу под кнопками, где был клик */}
      {msg && <Alert kind="ok">{msg}</Alert>}
      <PassportEmployerBadge refId={c.ref} />
      <EmployerAttempts refId={c.ref} direction={c.direction ?? direction} />
      <EmployerEvidence refId={c.ref} direction={c.direction ?? direction} />
      <InterviewEmployerDetails refId={c.ref} direction={c.direction ?? direction} />
      {(c.my_invitations.length > 0 || c.my_probes.length > 0) && (
        <section className="card text-sm">
          <h2 className="font-bold text-brand-night">Ваши взаимодействия</h2>
          <ul className="mt-3 space-y-2">
            {c.my_invitations.map((i: any) => <li key={i.id} className="flex items-center justify-between gap-3"><span>Приглашение «{i.position_title}» · {dt(i.created_at)}</span><Status s={i.contacts_revoked ? "contacts_revoked" : i.status} /></li>)}
            {c.my_probes.map((p: any) => <li key={p.id} className="flex items-center justify-between gap-3"><span>Зонд «{p.title}» · {dt(p.created_at)}</span><Status s={p.status} /></li>)}
          </ul>
        </section>
      )}
      <Modal open={modal === "probe"} onClose={() => setModal("")} title="Зонд кандидату">
        <ProbeForm refs={[c.ref]} needId={need ?? undefined} market={c.market_range} needSalary={needSalary} onDone={(r) => { setModal(""); setMsg(probeSentText(r)); void reload(); }} />
      </Modal>
      <Modal open={modal === "invite"} onClose={() => setModal("")} title="Приглашение-оффер">
        <InviteForm cref={c.ref} needId={need} market={c.market_range} needSalary={needSalary} onDone={(inv) => { setModal(""); setMsg(inviteSentText(inv, c.ref)); void reload(); }} />
      </Modal>
    </div>
  );
}
