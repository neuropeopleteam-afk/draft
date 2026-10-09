// Подборка для нанимающего руководителя по ссылке (Н3): только чтение, без ПДн, отметки «интересно / нет».
import { useState } from "react";
import { useParams } from "react-router-dom";
import { CandidateCard } from "../../components/CandidateCard";
import { Logo } from "../../components/Logo";
import { Alert, Empty, Loading, dt, errText, range, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { FitBadge, type Fit } from "./shared";

const WF: Record<string, string> = { office: "офис", hybrid: "гибрид", remote: "удалённо" };

export function SharePage() {
  const { token = "" } = useParams();
  const d = useApi<any>(`/share/${token}`, [token]);
  const [author, setAuthor] = useState(() => localStorage.getItem("share-author") ?? "");
  return (
    <div className="min-h-screen bg-[#F7F6FB]">
      <header className="border-b border-brand-night/10 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <Logo />
          <span className="text-xs text-brand-ink/65">подборка для руководителя · только чтение</span>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6">
        {d.loading && !d.data ? <Loading /> : !d.data ? (
          <Empty title="Ссылка недоступна" text={d.error ?? "Попросите рекрутера прислать новую ссылку."} />
        ) : (
          <>
            <section className="card space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{d.data.company}{d.data.label ? ` · ${d.data.label}` : ""}</p>
              <h1 className="text-xl font-extrabold text-brand-night sm:text-2xl">{d.data.need_title}</h1>
              <Reqs r={d.data.requirements} />
              <p className="text-xs text-brand-ink/65">Версия подборки v{d.data.version} · ссылка действует до {dt(d.data.expires_at)}. {d.data.note}</p>
              {d.data.hidden > 0 && <p className="text-xs text-brand-ink/65">Скрыли профиль после создания подборки: {d.data.hidden}.</p>}
              <div className="max-w-sm pt-1">
                <label className="label" htmlFor="share-author">Как подписать ваши отметки (необязательно)</label>
                <input id="share-author" className="input" maxLength={80} value={author} placeholder="Например, руководитель команды"
                  onChange={(e) => { setAuthor(e.target.value); localStorage.setItem("share-author", e.target.value); }} />
              </div>
            </section>
            {!d.data.candidates.length ? <Empty title="В подборке нет кандидатов" /> : d.data.candidates.map((c: any) => (
              <CandidateCard key={c.ref} c={c.card} score={c.score} reasons={c.reasons} compact
                mutual={c.fit?.level ? <div className="mt-3 flex flex-wrap items-start gap-x-3 gap-y-1"><FitBadge fit={c.fit as Fit} /><p className="min-w-0 flex-1 basis-56 text-sm text-brand-ink/80">{c.fit.line}</p></div> : null}
                actions={<Reaction token={token} cref={c.ref} mine={d.data.reactions[c.ref]} author={author} onSaved={d.reload} />} />
            ))}
          </>
        )}
      </main>
    </div>
  );
}

function Reqs({ r }: { r: any }) {
  const parts = [r.category, r.stack_required?.length ? `обязательно: ${r.stack_required.join(", ")}` : null,
    r.stack_desired?.length ? `желательно: ${r.stack_desired.join(", ")}` : null,
    (r.work_formats?.length ? r.work_formats : r.work_format ? [r.work_format] : []).map((x: string) => WF[x] ?? x).join(" или ") || null,
    r.city, r.salary_from || r.salary_to ? range(r.salary_from, r.salary_to) : null].filter(Boolean);
  return <p className="text-sm text-brand-ink/80">{parts.join(" · ")}</p>;
}

function Reaction({ token, cref, mine, author, onSaved }: { token: string; cref: string; mine?: any; author: string; onSaved: () => void }) {
  const [comment, setComment] = useState(mine?.comment ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function send(verdict: "interesting" | "no") {
    setErr(null); setBusy(true);
    try { await api(`/share/${token}/reactions`, { body: { ref: cref, verdict, comment: comment || null, author: author || null }, auth: false }); onSaved(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <div className="w-full space-y-2 sm:w-auto sm:min-w-[22rem]">
      <input className="input" maxLength={500} placeholder="Комментарий для рекрутера" value={comment} onChange={(e) => setComment(e.target.value)} aria-label={`Комментарий о кандидате ${cref}`} />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={mine?.verdict === "interesting" ? "btn-primary !py-2" : "btn-ghost !py-2"} disabled={busy} aria-pressed={mine?.verdict === "interesting"} onClick={() => send("interesting")}>Интересно</button>
        <button type="button" className={mine?.verdict === "no" ? "btn-primary !py-2" : "btn-ghost !py-2"} disabled={busy} aria-pressed={mine?.verdict === "no"} onClick={() => send("no")}>Нет</button>
        {mine && <span className="text-xs text-brand-ink/65">отмечено: {mine.verdict_title}</span>}
      </div>
      <Alert>{err}</Alert>
    </div>
  );
}
