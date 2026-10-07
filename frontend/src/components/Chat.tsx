import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { Alert, Loading, dtt, errText } from "./ui";

export type ThreadKind = "invitation" | "application";
interface Msg { id: string; side: "candidate" | "employer"; mine: boolean; body: string; mode: "qa" | "chat"; masked: number; at: string; read_at: string | null }
interface ThreadOut {
  kind: ThreadKind; id: string; title: string; side: string; counterpart: string; status: string; messages: Msg[];
  mode: "qa" | "chat"; max_len: number; can_write: boolean; reason: string | null; revoked: boolean; left?: number; in_row?: number;
}

/** Событие для значка непрочитанных в меню кабинета (CabinetLayout). */
export const MESSAGES_CHANGED = "messages:changed";
export const messagesChanged = () => window.dispatchEvent(new Event(MESSAGES_CHANGED));

const MASK = "[контакт скрыт до принятия приглашения]";

function Body({ text, mine }: { text: string; mine: boolean }) {
  const parts = text.split(MASK);
  // пометка читается и на тёмном пузыре своих сообщений, и на белом — чужих
  const mask = mine ? "bg-white/20 text-white" : "bg-brand-night/10 text-brand-plum";
  return (
    <p className="whitespace-pre-line break-words">
      {parts.map((p, i) => (
        <span key={i}>{p}{i < parts.length - 1 && <span className={`rounded px-1 text-[0.85em] font-semibold ${mask}`} title="Телефон, почта или ссылка на мессенджер скрыты до принятия приглашения">контакт скрыт</span>}</span>
      ))}
    </p>
  );
}

/** Переписка по приглашению или отклику: до принятия — «вопрос — ответ» с маскированием контактов, после — чат. */
export function Thread({ kind, id, compact, onUpdate }: { kind: ThreadKind; id: string; compact?: boolean; onUpdate?: () => void }) {
  const [t, setT] = useState<ThreadOut | null>(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const seen = useRef(0);
  const count = useRef(0);
  const upd = useRef(onUpdate);
  upd.current = onUpdate;

  const load = useCallback(async (quiet = false) => {
    try {
      const r = await api<ThreadOut>(`/messages/${kind}/${id}`);
      setT(r);
      // открытие треда отмечает сообщения прочитанными — значок в меню обновляется
      if (!quiet || r.messages.length !== count.current) { messagesChanged(); upd.current?.(); }
      count.current = r.messages.length;
    } catch (e) { if (!quiet) setErr(errText(e)); }
  }, [kind, id]);

  useEffect(() => {
    setT(null); setErr(null); setText(""); seen.current = 0; count.current = 0;
    void load();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(true); }, 20000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {  // новые сообщения — прокрутка вниз внутри ленты, страница не двигается
    const n = t?.messages.length ?? 0;
    if (n !== seen.current && list.current) list.current.scrollTop = list.current.scrollHeight;
    seen.current = n;
  }, [t]);

  async function send() {
    if (!text.trim()) return;
    setBusy(true); setErr(null);
    try {
      const r = await api<ThreadOut>(`/messages/${kind}/${id}`, { body: { body: text } });
      setT(r); setText(""); upd.current?.(); messagesChanged();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  if (!t) return err ? <Alert>{err}</Alert> : <Loading text="Загрузка переписки…" />;
  const other = t.counterpart;
  const qa = t.mode === "qa";
  return (
    <div className="space-y-3">
      {qa && (
        <p className="rounded-xl bg-[#F3F2FB] px-3 py-2 text-xs leading-relaxed text-brand-night">
          {t.kind === "invitation" && t.revoked ? "Кандидат отозвал доступ к контактам. " : "До принятия приглашения — "}
          формат «вопрос — ответ»: не больше двух сообщений подряд, телефоны, почты и ссылки на мессенджеры скрываются автоматически у обеих сторон.
          {t.can_write && t.left != null && ` Осталось сообщений: ${t.left}.`}
        </p>
      )}
      <div ref={list} className={`space-y-2 overflow-y-auto overscroll-contain rounded-xl border border-brand-night/10 bg-[#FBF8FC] p-3 ${compact ? "max-h-72" : "max-h-[55vh] min-h-[12rem]"}`} aria-live="polite">
        {!t.messages.length ? (
          <p className="py-6 text-center text-sm text-brand-ink/65">{t.side === "candidate" ? "Сообщений пока нет. Задайте вопрос работодателю — о команде, задачах, формате." : "Сообщений пока нет. Можно уточнить детали у кандидата — контакты останутся скрытыми до принятия."}</p>
        ) : t.messages.map((m) => (
          <div key={m.id} className={`flex ${m.mine ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-sm ${m.mine ? "rounded-br-md bg-brand-night text-white" : "rounded-bl-md bg-white text-brand-ink"}`}>
              <p className={`mb-0.5 text-[11px] font-semibold ${m.mine ? "text-white/70" : "text-brand-plum"}`}>{m.mine ? "Вы" : other}</p>
              <Body text={m.body} mine={m.mine} />
              <p className={`mt-1 text-right text-[11px] ${m.mine ? "text-white/60" : "text-brand-ink/50"}`}>
                {dtt(m.at)}{m.mine ? (m.read_at ? " · прочитано" : " · не прочитано") : ""}
              </p>
            </div>
          </div>
        ))}
      </div>
      {t.can_write ? (
        <div className="space-y-2">
          <label htmlFor={`msg-${id}`} className="sr-only">Сообщение</label>
          <textarea id={`msg-${id}`} className="input min-h-[72px]" maxLength={t.max_len} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={t.side === "candidate" ? (qa ? "Вопрос работодателю" : "Сообщение работодателю") : (qa ? "Вопрос или ответ кандидату" : "Сообщение кандидату")}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send(); }} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-brand-ink/55">{text.length} / {t.max_len.toLocaleString("ru-RU")}</span>
            <button className="btn-primary !py-2" disabled={busy || !text.trim()} onClick={send}>Отправить</button>
          </div>
        </div>
      ) : t.reason && <Alert kind="info">{t.reason}</Alert>}
      <Alert>{err}</Alert>
    </div>
  );
}

/** Переписка в карточке приглашения или отклика: свёрнута, число непрочитанных рядом, ссылка на раздел «Сообщения». */
export function InlineThread({ kind, id, thread, onUpdate, who = "с кандидатом", base = "/employer" }: {
  kind: ThreadKind; id: string; thread?: { total: number; unread: number } | null; onUpdate?: () => void; who?: string; base?: string;
}) {
  const [open, setOpen] = useState(false);
  const t = thread ?? { total: 0, unread: 0 };
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="text-sm font-semibold text-brand-plum hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Скрыть переписку" : `Переписка ${who}`}{!open && t.total ? ` (${t.total})` : ""}
        </button>
        {t.unread > 0 && <span className="rounded-full bg-brand px-2 py-0.5 text-xs font-bold text-white">Новых: {t.unread}</span>}
        <Link className="text-xs font-semibold text-brand hover:underline" to={`${base}/messages?t=${kind}:${id}`}>Открыть в «Сообщениях»</Link>
      </div>
      {open && <div className="mt-3"><Thread compact kind={kind} id={id} onUpdate={onUpdate} /></div>}
    </div>
  );
}
