// Трёхсторонняя связь: работодатель ↔ кандидат ↔ представитель ФСП по одному приглашению (API /api/trio).
// Канал от работодателя ждёт согласия кандидата; до принятия приглашения кандидат обезличен, контакты скрыты.
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Loading, cleanCompanyName, dtt, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";

type Side = "candidate" | "employer" | "fsp" | "system";
interface Msg { id: string; side: Side; side_title: string; mine: boolean; body: string; masked: number; at: string }
interface Participant { side: Side; title: string; joined: boolean }
interface TrioThread {
  id: string; invitation_id: string; status: "pending" | "active" | "closed"; status_title: string; topic: string; topic_title: string;
  side: Side; position: string; company: string; candidate: string; contacts_open: boolean; participants: Participant[];
  created_by_side: string; needs_my_consent: boolean; can_write: boolean; messages_count: number; last: Msg | null; activity_at: string;
  messages?: Msg[];
}
interface Eligible { invitation_id: string; position: string; counterpart: string; status: string }
interface Meta { topics: { id: string; title: string }[]; rules: string[]; max_len: number }

const MASK = "[контакт скрыт до принятия приглашения]";
const SIDE_STYLE: Record<Side, string> = {
  employer: "bg-[#ECEAF8] text-brand-night", candidate: "bg-white text-brand-ink ring-1 ring-brand-night/10",
  fsp: "bg-emerald-50 text-emerald-900 ring-1 ring-emerald-200", system: "bg-transparent text-brand-ink/65",
};
const DOT: Record<Side, string> = { employer: "bg-brand-lavender", candidate: "bg-brand", fsp: "bg-emerald-600", system: "bg-brand-ink/30" };
const STATUS_STYLE = { pending: "bg-amber-50 text-amber-900 ring-amber-200", active: "bg-emerald-50 text-emerald-800 ring-emerald-200", closed: "bg-[#F3F2FB] text-brand-ink/70 ring-brand-night/10" };

function TriangleScheme({ t }: { t?: TrioThread | null }) {
  const p = t?.participants ?? [
    { side: "employer", title: "Работодатель", joined: true }, { side: "candidate", title: "Кандидат", joined: true },
    { side: "fsp", title: "Представитель ФСП", joined: true }] as Participant[];
  return (
    <div className="grid grid-cols-3 gap-2 text-center text-xs" aria-label="Участники канала">
      {p.map((x) => (
        <div key={x.side} className={`rounded-xl px-2 py-2 ${x.joined ? SIDE_STYLE[x.side] : "border border-dashed border-brand-night/20 text-brand-ink/60"}`}>
          <span className={`mx-auto mb-1 block h-2 w-2 rounded-full ${DOT[x.side]}`} aria-hidden="true" />
          <span className="block font-semibold">{x.side === "employer" ? "Работодатель" : x.side === "candidate" ? "Кандидат" : "ФСП"}</span>
          <span className="block truncate opacity-80" title={cleanCompanyName(x.title)}>{x.joined ? cleanCompanyName(x.title) : "ждёт согласия"}</span>
        </div>
      ))}
    </div>
  );
}

function Body({ text, mine = false }: { text: string; mine?: boolean }) {
  const parts = text.split(MASK);
  const badgeCls = mine ? "bg-white/20 text-white" : "bg-brand-night/10 text-brand-plum";
  return <p className="whitespace-pre-line break-words">{parts.map((p, i) => <span key={i}>{p}{i < parts.length - 1 && <span className={`rounded px-1 text-[0.85em] font-semibold ${badgeCls}`}>контакт скрыт</span>}</span>)}</p>;
}

function ThreadView({ id, onChange }: { id: string; onChange: () => void }) {
  const [t, setT] = useState<TrioThread | null>(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const load = async (quiet = false) => { try { setT(await api<TrioThread>(`/trio/threads/${id}`)); } catch (e) { if (!quiet) setErr(errText(e)); } };
  useEffect(() => {
    setT(null); setErr(null); void load();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(true); }, 15000);
    return () => window.clearInterval(timer);
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [t?.messages?.length]);
  async function act(path: string, body?: unknown) {
    setBusy(true); setErr(null);
    try { setT(await api<TrioThread>(`/trio/threads/${id}${path}`, { method: "POST", ...(body ? { body } : {}) })); onChange(); if (body) setText(""); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  if (!t) return err ? <Alert>{err}</Alert> : <Loading text="Загрузка канала…" />;
  return (
    <div className="space-y-3" data-testid="trio-thread">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-bold text-brand-night">«{t.position}» · {cleanCompanyName(t.company)}</p>
          <p className="text-sm text-brand-ink/65">{t.candidate} · тема: {t.topic_title}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${STATUS_STYLE[t.status]}`}>{t.status_title}</span>
      </div>
      <TriangleScheme t={t} />
      {t.needs_my_consent && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          <p className="font-semibold">Работодатель предлагает подключить представителя ФСП.</p>
          <p className="mt-1">ФСП увидит эту переписку (вы останетесь обезличены до принятия приглашения) и сможет подтвердить ваши результаты соревнований, помочь с условиями оффера или спором.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn-primary !py-2" disabled={busy} onClick={() => act("/consent")}>Согласен, подключить ФСП</button>
            <button className="btn-ghost !py-2" disabled={busy} onClick={() => act("/close")}>Не подключать</button>
          </div>
        </div>
      )}
      {!t.contacts_open && <p className="rounded-xl bg-[#F3F2FB] px-3 py-2 text-xs text-brand-night">До принятия приглашения телефоны, почты и мессенджеры в тексте скрываются у всех трёх сторон автоматически.</p>}
      <div ref={box} className="max-h-[50vh] min-h-[12rem] space-y-2 overflow-y-auto overscroll-contain rounded-xl border border-brand-night/10 bg-[#FBF8FC] p-3" aria-live="polite">
        {(t.messages ?? []).map((m) => m.side === "system" ? (
          <p key={m.id} className="py-1 text-center text-xs text-brand-ink/65">{m.body} · {dtt(m.at)}</p>
        ) : (
          <div key={m.id} className={`flex ${m.mine ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-sm ${m.mine ? "rounded-br-md bg-brand-night text-white" : `rounded-bl-md ${SIDE_STYLE[m.side]}`}`}>
              <p className={`mb-0.5 flex items-center gap-1.5 text-[11px] font-semibold ${m.mine ? "text-white/70" : ""}`}>
                {!m.mine && <span className={`h-1.5 w-1.5 rounded-full ${DOT[m.side]}`} aria-hidden="true" />}
                {m.mine ? "Вы" : m.side === "employer" ? cleanCompanyName(t.company) : m.side === "candidate" ? t.candidate : m.side_title}
              </p>
              <Body text={m.body} mine={m.mine} />
              <p className={`mt-1 text-right text-[11px] ${m.mine ? "text-white/60" : "opacity-60"}`}>{dtt(m.at)}</p>
            </div>
          </div>
        ))}
      </div>
      {t.can_write ? (
        <div className="space-y-2">
          <label htmlFor={`trio-${id}`} className="sr-only">Сообщение</label>
          <textarea id={`trio-${id}`} className="input min-h-[72px]" maxLength={2000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={t.side === "fsp" ? "Сообщение работодателю и кандидату от ФСП" : "Сообщение сразу двум участникам"}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim()) void act("/messages", { body: text }); }} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button className="text-xs font-semibold text-brand-plum hover:underline" disabled={busy} onClick={() => act("/close")}>Закрыть канал</button>
            <button className="btn-primary !py-2" disabled={busy || !text.trim()} onClick={() => act("/messages", { body: text })}>Отправить</button>
          </div>
        </div>
      ) : t.status === "closed" ? <Alert kind="info">Канал закрыт — переписка доступна только для чтения.</Alert> : null}
      <Alert>{err}</Alert>
    </div>
  );
}

function NewThread({ role, initialInv, initialTopic, initialBody, onCreated }: { role: "candidate" | "employer"; initialInv?: string | null; initialTopic?: string | null; initialBody?: string | null; onCreated: (id: string) => void }) {
  const { data: el } = useApi<Eligible[]>("/trio/eligible");
  const { data: meta } = useApi<Meta>("/trio/meta");
  const [inv, setInv] = useState(initialInv ?? "");
  const [topic, setTopic] = useState(initialTopic ?? "fsp_check");
  const [body, setBody] = useState(initialBody ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (initialInv && el?.some((x) => x.invitation_id === initialInv)) {
      setInv(initialInv);
    } else if (el?.length && !inv) {
      setInv(el[0].invitation_id);
    }
  }, [el, inv, initialInv]);
  useEffect(() => { if (initialTopic) setTopic(initialTopic); }, [initialTopic]);
  useEffect(() => { if (initialBody && !body) setBody(initialBody); }, [initialBody]); // eslint-disable-line react-hooks/exhaustive-deps
  async function create() {
    setBusy(true); setErr(null);
    try { const t = await api<TrioThread>("/trio/threads", { body: { invitation_id: inv, topic, body: body.trim() || null } }); onCreated(t.id); setBody(""); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <section className="card space-y-3" data-testid="trio-new">
      <h2 className="font-bold text-brand-night">Подключить представителя ФСП</h2>
      <p className="text-sm text-brand-ink/70">{role === "employer" ? "Канал откроется для ФСП после согласия кандидата." : "Канал откроется сразу: работодатель и ФСП увидят его в своих кабинетах."}</p>
      {!el ? <Loading /> : !el.length ? <Alert kind="info">Нет открытых или принятых приглашений без канала. {role === "employer" ? "Отправьте приглашение кандидату — затем подключите ФСП." : "Когда работодатель пригласит вас, здесь можно будет подключить ФСП."}</Alert> : (
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">Приглашение
            <select className="input mt-1" value={inv} onChange={(e) => setInv(e.target.value)}>
              {el.map((x) => <option key={x.invitation_id} value={x.invitation_id}>«{x.position}» · {cleanCompanyName(x.counterpart)}</option>)}
            </select>
          </label>
          <label className="text-sm">Тема
            <select className="input mt-1" value={topic} onChange={(e) => setTopic(e.target.value)}>
              {(meta?.topics ?? []).map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
            </select>
          </label>
          <label className="text-sm md:col-span-2">Первое сообщение (необязательно)
            <textarea className="input mt-1 min-h-[64px]" maxLength={2000} value={body} onChange={(e) => setBody(e.target.value)}
              placeholder={role === "employer" ? "Например: просим подтвердить призовое место кандидата на чемпионате ФСП" : "Например: прошу ФСП подтвердить мои результаты для работодателя"} />
          </label>
          <div className="md:col-span-2"><button className="btn-primary" disabled={busy || !inv} onClick={create}>Открыть трёхсторонний канал</button></div>
        </div>
      )}
      <Alert>{err}</Alert>
    </section>
  );
}

/** Очередь заявок кандидатов на подтверждение достижений по официальным протоколам ФСП (для роли fsp). */
function ProtocolClaimsQueue() {
  const { data, loading, error, reload } = useApi<any>("/fsp-cabinet/protocol-claims");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);

  async function decide(id: string, action: "approve" | "reject") {
    setBusyId(id);
    setMsg(null);
    try {
      await api(`/fsp-cabinet/protocol-claims/${id}/decide`, {
        method: "POST",
        body: {
          action,
          note: action === "approve" ? "Сверено представителем ФСП с официальным PDF-протоколом" : "Не подтверждено при сверке",
        },
      });
      await reload();
      setMsg({
        k: "ok",
        t: action === "approve"
          ? "Достижение подтверждено по официальному протоколу ФСП. Статус в паспорте и карточке работодателя обновлён."
          : "Заявка отклонена.",
      });
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusyId(null);
    }
  }

  const items: any[] = data?.items ?? [];
  const counts = data?.counts ?? { pending_fsp: 0, verified: 0, total: 0 };

  return (
    <section className="card space-y-4" data-testid="fsp-protocol-claims-queue">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-bold text-brand-night">Очередь заявок на подтверждение по официальным протоколам ФСП</h2>
          <p className="mt-1 text-sm text-brand-ink/70">
            Защита от присвоения однофамильцем чужого результата: совпадение ФИО с протоколом создаёт заявку «ожидает подтверждения ФСП». После сверки с PDF протокола (или входа через ФСП ID) достижение получает статус «Подтверждено протоколом ФСП» и полный вес в подборе.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-semibold">
          <span className="rounded-full bg-amber-100 px-3 py-1 text-amber-900">
            Ожидают подтверждения: {counts.pending_fsp ?? 0}
          </span>
          <span className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-900">
            Подтверждено: {counts.verified ?? 0}
          </span>
        </div>
      </div>
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      {loading && !data ? (
        <Loading text="Загрузка очереди заявок по протоколам…" />
      ) : error ? (
        <Alert>{error}</Alert>
      ) : items.length === 0 ? (
        <div className="rounded-xl bg-[#F7F6FB] p-4 text-sm text-brand-ink/75">
          Новых заявок на ручную сверку по протоколам ФСП сейчас нет. Когда кандидат отметит свою запись в индексе официальных протоколов ФСП без входа через ФСП ID, заявка появится здесь со ссылкой на страницу PDF.
        </div>
      ) : (
        <ul className="space-y-3">
          {items.map((it) => {
            const isPending = it.protocol_status === "pending_fsp";
            return (
              <li key={it.id} className="rounded-xl border border-brand-night/10 bg-[#FBF8FC] p-3.5 text-sm" data-testid="fsp-protocol-claim-item">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {it.candidate_ref && (
                        <span className="text-xs font-bold uppercase tracking-wider text-brand-lavender">
                          Кандидат {it.candidate_ref}
                        </span>
                      )}
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                          isPending ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"
                        }`}
                        data-testid="fsp-claim-status-badge"
                      >
                        {it.status_title}
                      </span>
                      {it.evsk_rank && <span className="chip">Разряд по ЕВСК: {it.evsk_rank}</span>}
                      {(it.evsk_status === "place_unverified" || it.place_status === "not_recognized" || it.place_status === "place_unverified") ? (
                        <span className="chip bg-amber-50 text-amber-900">место не подтверждено</span>
                      ) : Array.isArray(it.place_range) && it.place_range.length === 2 && it.place == null ? (
                        <span className="chip">{it.place_range[0]}–{it.place_range[1]} место</span>
                      ) : it.place != null ? (
                        <span className="chip">{it.place} место</span>
                      ) : null}
                    </div>
                    <p className="font-semibold text-brand-night">{it.formatted_text}</p>
                    <p className="text-xs text-brand-ink/70">
                      {[
                        it.ekp_no ? `ЕКП № ${it.ekp_no}` : null,
                        it.evsk_basis ? `Норма ЕВСК: ${it.evsk_basis}` : null,
                        it.team_name ? `Команда: ${it.team_name}` : null,
                        it.region ? `Регион: ${it.region}` : null,
                      ].filter(Boolean).join(" · ")}
                    </p>
                    {it.pdf_url && (
                      <p className="text-xs">
                        <a href={it.pdf_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-brand hover:underline">
                          Открыть официальный протокол PDF (fsp-russia.ru){it.page ? `, стр. ${it.page}` : ""} ↗
                        </a>
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {isPending ? (
                      <>
                        <button
                          type="button"
                          className="btn-primary !py-1.5 !text-xs"
                          disabled={busyId === it.id}
                          onClick={() => decide(it.id, "approve")}
                          data-testid="fsp-claim-approve-btn"
                        >
                          Подтвердить результат
                        </button>
                        <button
                          type="button"
                          className="btn-ghost !py-1.5 !text-xs"
                          disabled={busyId === it.id}
                          onClick={() => decide(it.id, "reject")}
                          data-testid="fsp-claim-reject-btn"
                        >
                          Отклонить
                        </button>
                      </>
                    ) : (
                      <span className="text-xs font-semibold text-emerald-800">Проверено ФСП</span>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** Раздел «Связь с ФСП» — в кабинетах кандидата, работодателя и ФСП. */
export function TrioPage({ role }: { role: "candidate" | "employer" | "fsp" }) {
  const { data, loading, error, reload } = useApi<TrioThread[]>("/trio/threads");
  const { data: meta } = useApi<Meta>("/trio/meta");
  const [sp, setSp] = useSearchParams();
  const sel = sp.get("t");
  const invParam = sp.get("invitation");
  const topicParam = sp.get("topic");
  const bodyParam = sp.get("body");
  const open = (id: string) => setSp({ t: id }, { replace: !!sel });
  useEffect(() => {
    if (!sel && invParam && data?.length) {
      const existing = data.find((x) => x.invitation_id === invParam);
      if (existing) setSp({ t: existing.id }, { replace: true });
    } else if (!sel && !invParam && data?.length) {
      setSp({ t: data[0].id }, { replace: true });
    }
  }, [sel, invParam, data]); // eslint-disable-line react-hooks/exhaustive-deps
  const subtitle = role === "fsp"
    ? "Каналы, куда работодатель или кандидат пригласили ФСП: подтверждение результатов соревнований, условия оффера, апелляции и споры."
    : "Один канал на троих: работодатель, кандидат и представитель ФСП. ФСП подтверждает результаты соревнований и помогает договориться.";
  const pageTitle = role === "fsp" ? "Подтверждение результатов (трёхсторонняя связь)" : "Трёхсторонняя связь";
  return (
    <div className="max-w-6xl space-y-6">
      <PageTitle title={pageTitle} subtitle={subtitle} />
      <section className="card space-y-3">
        <TriangleScheme />
        <ul className="grid gap-1.5 text-sm text-brand-ink/75 md:grid-cols-2">
          {(meta?.rules ?? []).map((r) => <li key={r} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" aria-hidden="true" />{r}</li>)}
        </ul>
      </section>
      {role === "fsp" && <ProtocolClaimsQueue />}
      {role !== "fsp" && <NewThread role={role} initialInv={invParam} initialTopic={topicParam} initialBody={bodyParam} onCreated={(id) => { reload(); open(id); }} />}
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Каналов пока нет" text={role === "fsp" ? "Когда работодатель или кандидат подключит ФСП к приглашению, канал появится здесь." : "Откройте канал по приглашению — форма выше."} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <ul className={`min-w-0 space-y-2 ${sel ? "hidden lg:block" : ""}`} aria-label="Каналы">
            {data.map((t) => (
              <li key={t.id}>
                <button onClick={() => open(t.id)} aria-current={sel === t.id ? "true" : undefined}
                  className={`card w-full !p-3 text-left transition-colors hover:border-brand/40 ${sel === t.id ? "border-brand/50 bg-brand-blush/30" : ""}`}>
                  <div className="flex items-start justify-between gap-2">
                    <p className="min-w-0 font-semibold text-brand-night">{role === "candidate" ? cleanCompanyName(t.company) : role === "employer" ? t.candidate : `${cleanCompanyName(t.company)} ↔ ${t.candidate}`}</p>
                    <div className="flex shrink-0 items-center gap-1">
                      {(t.needs_my_consent || (t.status === "active" && t.last && !t.last.mine && t.last.side !== "system")) && (
                        <span className="h-2 w-2 rounded-full bg-brand-strong" title="Новое событие в канале" />
                      )}
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${STATUS_STYLE[t.status]}`}>{t.status === "pending" ? "ждёт согласия" : t.status === "active" ? "активен" : "закрыт"}</span>
                    </div>
                  </div>
                  <p className="truncate text-xs text-brand-ink/65">«{t.position}» · {t.topic_title}</p>
                  <p className="mt-1 line-clamp-2 text-sm text-brand-ink/75">{t.last ? `${t.last.mine ? "Вы: " : t.last.side === "system" ? "" : `${t.last.side_title}: `}${t.last.body}` : "Сообщений пока нет"}</p>
                  <p className="mt-1 text-[11px] text-brand-ink/65">{dtt(t.activity_at)}</p>
                </button>
              </li>
            ))}
          </ul>
          <section className={`card min-w-0 ${sel ? "" : "hidden lg:block"}`} aria-label="Канал">
            {sel ? <>
              <button className="mb-2 text-sm font-semibold text-brand-plum hover:underline lg:hidden" onClick={() => setSp({}, { replace: true })}>Все каналы</button>
              <ThreadView id={sel} onChange={reload} />
            </> : <p className="py-10 text-center text-sm text-brand-ink/65">Выберите канал слева.</p>}
          </section>
        </div>
      )}
    </div>
  );
}
