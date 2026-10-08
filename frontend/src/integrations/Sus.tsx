// Опрос SUS: 10 стандартных утверждений, шкала 1–5, балл 0–100. Встраивается после сквозного сценария,
// отдельная страница /sus (?context=jury для режима жюри) и админка /admin/sus.
import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Alert, Loading, errText, useApi } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

interface Q { n: number; text: string; positive: boolean }
const SCALE = ["Полностью не согласен", "Скорее не согласен", "Нейтрально", "Скорее согласен", "Полностью согласен"];

export function SusSurvey({ context = "e2e", onDone, intro }: { context?: string; onDone?: (score: number) => void; intro?: string }) {
  const { data } = useApi<{ questions: Q[] }>("/sus/questions");
  const [ans, setAns] = useState<(number | null)[]>(Array(10).fill(null));
  const [comment, setComment] = useState("");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return <Loading />;
  const done = ans.every((a) => a !== null);
  async function submit() {
    setBusy(true); setErr(null);
    try { const r = await api<any>("/sus", { body: { answers: ans, context, comment: comment || null } }); setRes(r); onDone?.(r.score); }
    catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  }
  if (res) return (
    <div className="rounded-2xl bg-[#F3F2FB] p-5 text-center">
      <p className="text-sm text-brand-ink/65">Спасибо! Ваша оценка удобства</p>
      <p className="mt-1 text-4xl font-extrabold tabular-nums text-brand-night">{res.score}</p>
      <p className="text-sm text-brand-ink/70">из 100 · «{res.adjective}» · оценка {res.grade} (среднее по отрасли — 68)</p>
    </div>
  );
  return (
    <div className="space-y-4">
      {intro && <p className="text-sm text-brand-ink/70">{intro}</p>}
      <ol className="space-y-3">
        {data.questions.map((q, i) => (
          <li key={q.n} className="rounded-xl border border-brand-night/10 p-3">
            <p className="text-sm font-medium text-brand-night">{q.n}. {q.text}</p>
            <div className="mt-2 grid grid-cols-5 gap-1" role="radiogroup" aria-label={`Утверждение ${q.n}`}>
              {SCALE.map((s, k) => (
                <button key={k} type="button" role="radio" aria-checked={ans[i] === k + 1} title={s}
                  onClick={() => setAns((prev) => prev.map((a, j) => (j === i ? k + 1 : a)))}
                  className={`rounded-lg py-2 text-sm font-bold transition-colors ${ans[i] === k + 1 ? "bg-brand-strong text-white" : "bg-brand-blush/40 text-brand-plum hover:bg-brand-blush"}`}>
                  {k + 1}
                </button>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-xs text-brand-ink/65"><span>не согласен</span><span>согласен</span></div>
          </li>
        ))}
      </ol>
      <textarea className="input min-h-[70px]" placeholder="Что мешало или понравилось (необязательно)" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
      <Alert>{err}</Alert>
      <button className="btn-primary w-full" disabled={!done || busy} onClick={submit}>{busy ? "Сохраняем…" : done ? "Отправить оценку" : `Ответьте на все утверждения (${ans.filter((a) => a !== null).length}/10)`}</button>
    </div>
  );
}

/** Карточка-приглашение пройти SUS после сквозного сценария; не показывается, если пользователь уже отвечал. */
export function SusPrompt({ context = "e2e" }: { context?: string }) {
  const { data } = useApi<{ answered: boolean }>("/sus/mine");
  const [open, setOpen] = useState(false);
  if (!data || data.answered) return null;
  return (
    <section className="card border-brand-lavender/30 bg-[#FBFAFF]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-bold text-brand-night">Оцените удобство платформы — 1 минута</p>
          <p className="text-sm text-brand-ink/65">10 стандартных утверждений SUS. Результаты — на странице проверки гипотез.</p>
        </div>
        {!open && <button className="btn-ghost" onClick={() => setOpen(true)}>Пройти опрос</button>}
      </div>
      {open && <div className="mt-4"><SusSurvey context={context} /></div>}
    </section>
  );
}

/** /sus — отдельная страница (для жюри: /sus?context=jury). */
export function SusPage() {
  const [sp] = useSearchParams();
  const context = ["e2e", "jury", "pilot", "other"].includes(sp.get("context") ?? "") ? sp.get("context")! : "other";
  return (
    <div className="min-h-screen bg-[#FBF8FC] px-6 py-10">
      <div className="mx-auto max-w-2xl space-y-6">
        <Link to="/"><Logo /></Link>
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">Оценка удобства (SUS)</h1>
          <p className="mt-2 text-brand-ink/70">System Usability Scale — стандартная анкета из 10 утверждений. Оцените каждое от 1 до 5. Анонимно, если вы не вошли.</p>
        </div>
        <div className="card"><SusSurvey context={context} /></div>
        <SusSummaryCard />
      </div>
    </div>
  );
}

export function SusSummaryCard() {
  const { data } = useApi<any>("/sus/summary");
  if (!data || !data.n) return null;
  return (
    <section className="card">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Итог по ответам после входа</p>
      <p className="mt-2 text-3xl font-extrabold tabular-nums text-brand-night">{String(data.mean).replace(".", ",")}<span className="ml-2 text-base font-medium text-brand-ink/65">из 100 · n = {data.n}</span></p>
      <p className="text-sm text-brand-ink/65">Медиана {String(data.median).replace(".", ",")}{data.ci95 ? `, 95 % ДИ ${data.ci95[0]}–${data.ci95[1]}` : ""} · «{data.adjective}» · оценка {data.grade} · порог отрасли 68</p>
      {data.anonymous?.n ? <p className="mt-2 text-xs text-brand-ink/65">Анонимные анкеты считаются отдельно и в итог не входят: n = {data.anonymous.n}, среднее {String(data.anonymous.mean).replace(".", ",")}.</p> : null}
    </section>
  );
}

/** /admin/sus — все анкеты (для роли admin). */
export function AdminSus() {
  const { me, loading } = useAuth();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (me?.role === ("admin" as any)) api<any>("/admin/sus").then(setD).catch((e) => setErr(errText(e))); }, [me]);
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  return (
    <div className="min-h-screen bg-[#FBF8FC] px-6 py-10">
      <div className="mx-auto max-w-5xl space-y-6">
        <Link to="/"><Logo /></Link>
        <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">Админка · SUS</h1>
        {me.role !== ("admin" as any) ? <Alert>Раздел доступен только администратору.</Alert> : err ? <Alert>{err}</Alert> : !d ? <Loading /> : (
          <>
            <div className="grid gap-3 sm:grid-cols-4">
              {[["Анкет", d.total], ["Среднее", d.summary.mean ?? "—"], ["Медиана", d.summary.median ?? "—"], ["95 % ДИ", d.summary.ci95 ? d.summary.ci95.join("–") : "—"]].map(([k, v]) => (
                <div key={k as string} className="card"><p className="text-xs uppercase tracking-[0.12em] text-brand-lavender">{k}</p><p className="mt-1 text-xl font-bold text-brand-night">{v}</p></div>
              ))}
            </div>
            <div className="card overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wider text-brand-ink/65"><tr><th className="py-2">Когда</th><th>Роль</th><th>Контекст</th><th>Ответы</th><th>Балл</th><th>Комментарий</th></tr></thead>
                <tbody className="divide-y divide-brand-night/5">
                  {d.items.map((r: any) => (
                    <tr key={r.id}><td className="py-2 pr-3 whitespace-nowrap">{new Date(r.created_at).toLocaleString("ru-RU")}</td><td className="pr-3">{r.role}{r.is_demo ? " (демо)" : ""}</td><td className="pr-3">{r.context}</td><td className="pr-3 font-mono text-xs">{r.answers.join(" ")}</td><td className="pr-3 font-bold tabular-nums">{r.score}</td><td className="text-brand-ink/70">{r.comment}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
