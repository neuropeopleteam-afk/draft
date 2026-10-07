import { Link, useSearchParams } from "react-router-dom";
import { PageTitle } from "../components/CabinetLayout";
import { Thread, type ThreadKind } from "../components/Chat";
import { Alert, Empty, Loading, Status, dtt, useApi } from "../components/ui";

interface ThreadRow {
  kind: ThreadKind; id: string; title: string; counterpart: string; status: string; mode: "qa" | "chat";
  closed: string | null; revoked: boolean; messages: number; unread: number;
  last: { body: string; mine: boolean; at: string } | null; activity_at: string;
}

const APP_STATUS: Record<string, string> = { sent: "Отклик отправлен", viewed: "Отклик просмотрен", accepted: "Приглашение на интервью", rejected: "Отказ", withdrawn: "Отклик отозван" };

/** Сообщения: все переписки по приглашениям и откликам, слева список, справа тред (на телефоне — по очереди). */
export function Messages({ role }: { role: "candidate" | "employer" }) {
  const { data, loading, error, reload } = useApi<ThreadRow[]>("/messages/threads");
  const [sp, setSp] = useSearchParams();
  const sel = sp.get("t");
  const [kind, id] = (sel ?? "").split(":") as [ThreadKind, string];
  const cur = data?.find((t) => t.kind === kind && t.id === id);
  const open = (t: ThreadRow) => setSp({ t: `${t.kind}:${t.id}` }, { replace: !!sel });
  const back = () => setSp({}, { replace: true });
  const base = role === "candidate" ? "/candidate" : "/employer";
  const subtitle = role === "candidate"
    ? "Переписка с работодателями по приглашениям и откликам. До принятия приглашения — «вопрос — ответ», ваши контакты скрыты."
    : "Переписка с кандидатами по приглашениям и откликам на вакансии. До принятия приглашения кандидат обезличен, контакты в тексте скрываются.";

  return (
    <div className="max-w-6xl space-y-6">
      <PageTitle title="Сообщения" subtitle={subtitle} />
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Переписок пока нет" text={role === "candidate" ? "Когда работодатель пригласит вас или вы откликнетесь на вакансию, здесь можно будет задать вопрос." : "Отправьте приглашение кандидату или опубликуйте вакансию — переписка появится здесь."}
          action={<Link className="btn-primary" to={`${base}/${role === "candidate" ? "invitations" : "needs"}`}>{role === "candidate" ? "К приглашениям" : "К подборкам"}</Link>} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <ul className={`space-y-2 ${sel ? "hidden lg:block" : ""}`} aria-label="Переписки">
            {data.map((t) => {
              const active = cur?.kind === t.kind && cur?.id === t.id;
              return (
                <li key={`${t.kind}:${t.id}`}>
                  <button onClick={() => open(t)} aria-current={active ? "true" : undefined}
                    className={`card w-full !p-3 text-left transition-colors hover:border-brand/40 ${active ? "border-brand/50 bg-brand-blush/30" : ""}`}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="min-w-0 font-semibold text-brand-night">{t.counterpart}</p>
                      {t.unread > 0 && <span className="shrink-0 rounded-full bg-brand px-2 py-0.5 text-xs font-bold text-white" aria-label={`Непрочитанных: ${t.unread}`}>{t.unread}</span>}
                    </div>
                    <p className="truncate text-xs text-brand-ink/65">{t.kind === "invitation" ? "Приглашение" : "Отклик"} · {t.title}</p>
                    <p className="mt-1 line-clamp-2 text-sm text-brand-ink/75">{t.last ? `${t.last.mine ? "Вы: " : ""}${t.last.body}` : "Сообщений пока нет"}</p>
                    <p className="mt-1 text-[11px] text-brand-ink/50">{dtt(t.activity_at)}{t.revoked ? " · доступ к контактам отозван" : t.mode === "qa" && !t.closed ? " · вопрос — ответ" : ""}</p>
                  </button>
                </li>
              );
            })}
          </ul>
          <section className={`card min-w-0 ${sel ? "" : "hidden lg:block"}`} aria-label="Переписка">
            {cur ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <button className="mb-1 text-sm font-semibold text-brand-plum hover:underline lg:hidden" onClick={back}>Все переписки</button>
                    <p className="font-bold text-brand-night">{cur.counterpart}</p>
                    <p className="text-sm text-brand-ink/65">{cur.kind === "invitation" ? "Приглашение" : "Отклик на вакансию"} «{cur.title}»</p>
                  </div>
                  {cur.kind === "invitation" ? <Status s={cur.revoked ? "contacts_revoked" : cur.status} /> : <span className="rounded-full bg-[#ECEAF8] px-2.5 py-1 text-xs font-semibold text-brand-night">{APP_STATUS[cur.status] ?? cur.status}</span>}
                </div>
                <Thread key={`${cur.kind}:${cur.id}`} kind={cur.kind} id={cur.id} onUpdate={reload} />
                <Link className="inline-block text-sm font-semibold text-brand hover:underline" to={`${base}/${cur.kind === "invitation" ? "invitations" : "vacancies"}`}>
                  {cur.kind === "invitation" ? "Открыть приглашения" : "Открыть отклики"}
                </Link>
              </div>
            ) : sel ? <Alert kind="info">Переписка не найдена или недоступна.</Alert> : <p className="py-10 text-center text-sm text-brand-ink/65">Выберите переписку слева.</p>}
          </section>
        </div>
      )}
    </div>
  );
}
