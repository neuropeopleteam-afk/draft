// Раздел «Уведомления» (И25, Н6): лента того, что отправлено в push и письмах, и настройки каналов. Общий для ролей.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../components/CabinetLayout";
import { Alert, Empty, Loading, Toggle, dtt, errText, useApi } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

interface Item {
  id: string; kind: string; title: string; body: string; url: string; created_at: string; read: boolean;
  push_state: string | null; email_state: string | null; digest: string | null; channels: string[]; waiting: boolean;
}
interface Feed { items: Item[]; unread: number; prefs: { push_enabled: boolean; email_enabled: boolean; reminders_enabled: boolean }; quiet: { from: number; to: number } }

const KIND: Record<string, string> = {
  new_match: "Новые подходящие", digest: "Дайджест", inv_unanswered: "Приглашение без ответа", inv_expiring: "Срок ответа",
  inv_expired: "Приглашение истекло", app_stale: "Отклик без ответа",
  hiring: "Найм", hiring_reminder: "Скоро собеседование",  // найм по приглашению (Н8)
};
const PUSH: Record<string, string> = {
  sent: "push отправлен", no_devices: "push: устройств нет", off: "push выключен вами", off_platform: "push на сервере не настроен", failed: "push не доставлен",
};
const MAIL: Record<string, string> = {
  sent: "письмо отправлено", demo: "письмо демо-учётке не уходит", off: "письма выключены вами", failed: "письмо не отправлено",
};
const hh = (n: number) => `${String(n).padStart(2, "0")}:00`;

function Delivery({ n }: { n: Item }) {
  const parts: string[] = [];
  if (n.waiting) parts.push("ждёт утра: сейчас тихие часы");
  else {
    if (n.channels.includes("push") && n.push_state) parts.push(PUSH[n.push_state] ?? n.push_state);
    if (n.channels.includes("email") && n.email_state) parts.push(MAIL[n.email_state] ?? n.email_state);
    if (n.digest === "queued") parts.push("попадёт в письмо-дайджест");
    if (n.digest === "sent") parts.push("вошло в письмо-дайджест");
  }
  return parts.length ? <p className="mt-2 text-xs text-brand-ink/65">{parts.join(" · ")}</p> : null;
}

export default function Notifications() {
  const { me } = useAuth();
  const role = me?.role === "employer" ? "employer" : "candidate";
  const feed = useApi<Feed>("/notifications");
  const [err, setErr] = useState<string | null>(null);
  const reload = feed.reload;
  useEffect(() => {
    const f = () => { void reload(); };
    window.addEventListener("subs:changed", f);
    return () => window.removeEventListener("subs:changed", f);
  }, [reload]);

  async function setPref(k: string, v: boolean) {
    setErr(null);
    try { const p = await api<Feed["prefs"]>("/notifications/prefs", { method: "PUT", body: { [k]: v } }); feed.setData(feed.data ? { ...feed.data, prefs: p } : feed.data); }
    catch (e) { setErr(errText(e)); }
  }
  async function readAll() {
    setErr(null);
    try { await api("/notifications/read", { method: "POST", body: {} }); await feed.reload(); } catch (e) { setErr(errText(e)); }
  }
  const d = feed.data;
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Уведомления" subtitle={role === "employer"
        ? "Новые подходящие кандидаты по потребностям, за которыми вы следите, и напоминания по приглашениям и откликам."
        : "Напоминания о приглашениях: без ответа и срок ответа."} />
      <section className="card space-y-1">
        <h2 className="font-bold text-brand-night">Каналы</h2>
        {!d ? <Loading /> : (
          <>
            <Toggle checked={d.prefs.push_enabled} onChange={(v) => setPref("push_enabled", v)} label="Push на устройство"
              hint="Включить на самом устройстве можно в разделе «Приложение и уведомления»." />
            <Toggle checked={d.prefs.email_enabled} onChange={(v) => setPref("email_enabled", v)} label="Письма"
              hint={role === "employer" ? "Дайджест раз в день (или раз в неделю — как выбрано в подписке): новые подходящие, истёкшие приглашения, отклики без ответа." : "Напоминания по приглашениям."} />
            <Toggle checked={d.prefs.reminders_enabled} onChange={(v) => setPref("reminders_enabled", v)} label="Напоминания"
              hint={role === "employer" ? "Приглашение без ответа истекло; отклик без ответа 5 дней." : "Приглашение без ответа 3 дня; за сутки до окончания срока ответа."} />
            <p className="pt-2 text-xs text-brand-ink/65">С {hh(d.quiet.from)} до {hh(d.quiet.to)} по Москве push и письма не отправляются: они придут утром. В кабинете уведомления видны всегда.</p>
            <p className="text-xs text-brand-ink/65"><Link className="font-semibold text-brand hover:underline" to={`/${role}/app`}>Приложение и уведомления на устройстве</Link></p>
          </>
        )}
        <Alert>{err}</Alert>
      </section>
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold text-brand-night">Лента{d && d.unread ? ` · непрочитанных: ${d.unread}` : ""}</h2>
          {d && d.unread > 0 && <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={readAll}>Отметить все прочитанными</button>}
        </div>
        {feed.loading && !d ? <Loading /> : feed.error ? <Alert>{feed.error}</Alert> : !d?.items.length
          ? <Empty title="Пока ничего нет" text={role === "employer" ? "Включите «Следить за новыми подходящими» в подборке по потребности." : "Здесь появятся напоминания по приглашениям."} />
          : (
            <ul className="space-y-3">
              {d.items.map((n) => (
                <li key={n.id} className={`card ${n.read ? "" : "border-brand/40"}`}>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    {!n.read && <span className="h-2 w-2 rounded-full bg-brand" aria-label="не прочитано" />}
                    <span className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{KIND[n.kind] ?? n.kind}</span>
                    <span className="text-xs text-brand-ink/65">{dtt(n.created_at)}</span>
                  </div>
                  <p className="mt-1 font-bold text-brand-night">{n.title}</p>
                  <p className="mt-1 whitespace-pre-line break-words text-sm text-brand-ink/80">{n.body}</p>
                  <Delivery n={n} />
                  {n.url && n.kind !== "digest" && <Link to={n.url} className="mt-2 inline-block text-sm font-semibold text-brand hover:underline">Открыть</Link>}
                </li>
              ))}
            </ul>
          )}
      </section>
    </div>
  );
}
