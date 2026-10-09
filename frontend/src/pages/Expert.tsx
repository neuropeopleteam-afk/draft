import { useState } from "react";
import { PageTitle } from "../components/CabinetLayout";
import { Alert, catTitle, DIRECTIONS, dtt, Empty, errText, Loading, num, Seg, signed, useApi } from "../components/ui";
import { api } from "../lib/api";

type Mode = "pending" | "llm" | "reviewed";
const FORMAT: Record<string, string> = { open_answer: "Развёрнутый ответ", open_book_3step: "Open book, шаг 3 — объяснение" };
const MARKS = [{ v: 0, t: "0 — нет" }, { v: 0.5, t: "0,5 — частично" }, { v: 1, t: "1 — полностью" }];

/** Экран эксперта: развёрнутые ответы «на проверке» и выборочная проверка оценок LLM — по рубрике. */
export default function Expert() {
  const [mode, setMode] = useState<Mode>("pending");
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useApi<any>(`/expert/queue?mode=${mode}`, [mode, tick]);
  const agr = useApi<any>("/expert/agreement", [tick]);
  return (
    <div className="max-w-4xl">
      <PageTitle title="Проверка развёрнутых ответов"
        subtitle="Ответ оценивается по каждому критерию рубрики: 0, 0,5 или 1 — с весами критериев. Оценка эксперта сразу входит в результат теста; грейд принудительно не понижается." />
      <div className="mt-6 flex flex-wrap items-center gap-4">
        <Seg label="Очередь" value={mode} onChange={setMode} options={[
          { id: "pending", title: `На проверке${data?.counts ? ` · ${data.counts.pending}` : ""}` },
          { id: "llm", title: `Проверка LLM вслепую${data?.counts ? ` · ${data.counts.llm}` : ""}` },
          { id: "reviewed", title: `Проверено${data?.counts ? ` · ${data.counts.reviewed}` : ""}` },
        ]} />
        {agr.data?.n > 0 && <p className="text-sm text-brand-ink/70">Согласие LLM и экспертов: {agr.data.n} пар, средняя разница {agr.data.mae}, в пределах 0,25 — {Math.round(agr.data.within_025 * 100)} %</p>}
      </div>
      {mode === "llm" && <p className="mt-3 text-sm text-brand-ink/70">Ответы, которые уже оценил LLM. Балл модели скрыт, пока вы не поставите свой, — так считается честное согласие для выбора модели оценщика.</p>}
      <div className="mt-6 space-y-5">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.items?.length
          ? <Empty title={mode === "pending" ? "Очередь пуста" : "Пока ничего нет"} text={mode === "pending" ? "Все развёрнутые ответы оценены. Ответ попадает сюда, если LLM не смог его оценить." : undefined} />
          : data.items.map((it: any) => <ReviewItem key={`${it.session_id}-${it.token}-${it.part}`} it={it} mode={mode} onDone={() => setTick((x) => x + 1)} />)}
      </div>
    </div>
  );
}

function ReviewItem({ it, mode, onDone }: { it: any; mode: Mode; onDone: () => void }) {
  const crit: any[] = it.rubric?.criteria ?? [];
  const [marks, setMarks] = useState<Record<string, number>>(() => Object.fromEntries(crit.map((c) => [c.id, it.expert?.criteria?.[c.id]]).filter(([, v]) => v != null)));
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<any>(null);
  const total = crit.reduce((a, c) => a + c.weight, 0) || 1;
  const score = crit.every((c) => marks[c.id] != null) ? crit.reduce((a, c) => a + c.weight * marks[c.id], 0) / total : null;
  const done = mode === "reviewed" || res;

  async function submit() {
    setBusy(true); setErr(null);
    try {
      setRes(await api<any>("/expert/review", { body: { session_id: it.session_id, token: it.token, part: it.part, criteria: marks, comment: comment || null } }));
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <article className="card">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="chip">{FORMAT[it.format] ?? it.format}</span>
        <span className="text-brand-ink/65">Кандидат {it.candidate_ref ?? "—"} · {DIRECTIONS[it.direction] ?? it.direction} · заявлен {catTitle(`${it.direction}.${it.claimed_grade}`)} · задание {it.position} · {dtt(it.at)}</span>
        {it.session_status === "finished" && it.status === "pending" && <span className="chip bg-brand-blush text-brand-plum">результат предварительный</span>}
        {it.llm?.second && <span className="chip bg-[#ECEAF8] text-brand-night" title={`Причины второй оценки: ${(it.llm.checks ?? []).join(", ")}`}>Две оценки: {it.llm.model_label ?? "LLM"} {num(it.llm.scores?.[0])} · {it.llm.second.model_label ?? "вторая"} {it.llm.second.score == null ? "—" : num(it.llm.second.score)}{it.llm.error === "graders_disagree" || it.llm.second.verdict === "disagree" ? " — разошлись" : ""}{it.llm.second.status === "pending" ? " — вторая оценка выполняется" : it.llm.second.after_finish ? " (вторая — в фоне, после итога теста)" : ""}</span>}
        {it.llm?.error === "prompt_injection_suspected" && <span className="chip bg-brand-night text-white" title={it.llm.injection_note ?? undefined}>Похоже на инструкции оценщику — LLM не вызывался</span>}
      </div>
      <p className="mt-3 whitespace-pre-line font-semibold leading-relaxed text-brand-night">{it.stem}</p>
      {it.code && <pre tabIndex={0} aria-label="Код задания" className="mt-3 max-h-72 overflow-auto rounded-xl bg-brand-ink p-3 text-xs leading-relaxed text-[#FFD6E4]"><code>{it.code}</code></pre>}
      {it.step_prompt && <p className="mt-3 rounded-xl bg-brand-blush/30 px-4 py-3 text-sm font-semibold text-brand-night">{it.step_prompt}</p>}
      {it.llm?.injection_note && <div className="mt-3"><Alert kind="info">{it.llm.injection_note} Оцените ответ по рубрике как обычно: попытка повлиять на оценщика уже учтена в «достоверности результата».</Alert></div>}
      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Ответ кандидата</p>
        <p className="mt-1 whitespace-pre-line rounded-xl border border-brand-night/10 bg-white p-3 text-sm leading-relaxed text-brand-ink">{it.answer || "— пустой ответ —"}</p>
      </div>
      {it.rubric && (
        <details className="mt-3 rounded-xl bg-[#F3F2FB] p-3 text-sm">
          <summary className="cursor-pointer font-semibold text-brand-night">Эталоны: сильный, средний, слабый ответ</summary>
          {(["strong", "medium", "weak"] as const).map((k) => it.rubric[k] && (
            <p key={k} className="mt-2 text-brand-ink/80"><b>{{ strong: "Сильный", medium: "Средний", weak: "Слабый" }[k]}:</b> {it.rubric[k]}</p>))}
          {it.rubric.scoring_notes && <p className="mt-2 text-xs text-brand-ink/65">{it.rubric.scoring_notes}</p>}
        </details>
      )}
      <fieldset className="mt-4 min-w-0 space-y-3" disabled={!!done}>
        <legend className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Критерии рубрики</legend>
        {crit.map((c) => (
          <div key={c.id} className="rounded-xl border border-brand-night/10 p-3">
            <p className="text-sm text-brand-ink"><b className="font-semibold">Вес {Math.round(c.weight * 100)} %.</b> {c.description}</p>
            <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label={`Оценка: ${c.description}`}>
              {MARKS.map((m) => (
                <button key={m.v} type="button" role="radio" aria-checked={marks[c.id] === m.v}
                  className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${marks[c.id] === m.v ? "border-brand-strong bg-brand-strong text-white" : "border-brand-night/15 text-brand-ink hover:border-brand/50"}`}
                  onClick={() => setMarks({ ...marks, [c.id]: m.v })}>{m.t}</button>))}
            </div>
          </div>
        ))}
        {!done && <textarea className="input" rows={2} aria-label="Комментарий эксперта" placeholder="Комментарий (необязательно): что упущено, что верно" value={comment} onChange={(e) => setComment(e.target.value)} />}
      </fieldset>
      {err && <div className="mt-3"><Alert>{err}</Alert></div>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-brand-ink/75">{score != null ? <>Итог по рубрике: <b className="text-brand-night">{num(score)}</b></> : "Оцените все критерии"}</p>
        {!done && <button className="btn-primary" disabled={score == null || busy} onClick={submit}>{busy ? "Сохраняем…" : "Сохранить оценку"}</button>}
      </div>
      {(res || mode === "reviewed") && (
        <div className="mt-3"><Alert kind="ok">
          {res?.review?.applied || it.method === "expert" ? "Оценка эксперта вошла в результат теста." : "Оценка сохранена рядом с оценкой LLM."}
          {(res?.review?.llm_score ?? it.llm?.score) != null && ` Балл ${it.llm?.model_label ?? "LLM"}: ${num(Number(res?.review?.llm_score ?? it.llm?.score))}.`}
          {res?.recomputed && ` Результат пересчитан: θ = ${signed(res.theta)}, грейд ${res.confirmed ? "подтверждён" : "не подтверждён"}.`}
          {res && <button className="ml-2 font-semibold underline" onClick={onDone}>Обновить очередь</button>}
        </Alert></div>
      )}
    </article>
  );
}
