import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api";
import { study } from "../../lib/study";
import { Alert, errText, Loading, Modal } from "../ui";

interface Shown { ref: string; rank: number; category: string | null; status: string | null; reasons: string[] }
interface Form {
  role: "candidate" | "employer"; exposed: boolean;
  sus: { items: string[]; scale: string[] };
  rel: { scale: string[]; threshold: number; selection: { need_id: string; version: number; shown: Shown[] } | null };
  belief: { q: string } | null; grade_fit: { q: string; options: Record<string, string> } | null;
  tags: Record<string, string>; text_max: number;
}

const NUM = [1, 2, 3, 4, 5];

function Scale({ value, onChange, label, titles }: { value: number | null; onChange: (v: number) => void; label: string; titles?: string[] }) {
  return (
    <div role="radiogroup" aria-label={label} className="grid grid-cols-5 gap-1.5">
      {NUM.map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} title={titles?.[n - 1]} onClick={() => onChange(n)}
          className={`min-h-[44px] rounded-xl border text-sm font-semibold transition-colors ${value === n ? "border-brand-strong bg-brand-strong text-white" : "border-brand-night/15 bg-white text-brand-night hover:bg-brand-blush/50"}`}>
          {n}
        </button>
      ))}
    </div>
  );
}

/** Необязательная анкета: SUS, оценка топ-5 подборки (работодатель), доверие к грейду и «что мешало». Любую часть можно пропустить. */
export function SurveyModal({ open, onClose, role }: { open: boolean; onClose: () => void; role: "candidate" | "employer" }) {
  const [form, setForm] = useState<Form | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [sus, setSus] = useState<(number | null)[]>(Array(10).fill(null));
  const [rate, setRate] = useState<Record<string, number>>({});
  const [belief, setBelief] = useState<number | null>(null);
  const [fit, setFit] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ sus_score: number | null } | null>(null);
  const need = study.need();
  const top = useRef<HTMLDivElement>(null);
  // новый шаг — окно прокручивается к началу (иначе после длинной шкалы человек попадает в середину следующего шага)
  useEffect(() => { top.current?.closest('[role="dialog"]')?.scrollTo({ top: 0 }); }, [step, done]);

  useEffect(() => {
    if (!open) return;
    setForm(null); setErr(null); setStep(0); setDone(null);
    const q = need ? `?need_id=${need.id}${need.version ? `&version=${need.version}` : ""}` : "";
    api<Form>(`/study/survey${q}`).then(setForm).catch((e) => setErr(errText(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const shown = form?.rel.selection?.shown ?? [];
  const steps = useMemo(() => ["sus", ...(role === "employer" && shown.length ? ["rel"] : []), "final"], [role, shown.length]);
  const kind = steps[step];
  const susAnswered = sus.filter((v) => v !== null).length;
  const relAnswered = shown.filter((x) => rate[x.ref]).length;
  const susBad = susAnswered > 0 && susAnswered < 10;
  const relBad = relAnswered > 0 && relAnswered < shown.length;
  const anything = susAnswered === 10 || relAnswered === shown.length && shown.length > 0 || belief !== null || !!fit || tags.length > 0 || comment.trim().length > 0;

  async function submit() {
    if (susBad || relBad) { setErr(susBad ? "Ответьте на все 10 пунктов шкалы или пропустите её." : "Оцените всех пятерых кандидатов или пропустите шаг."); return; }
    setBusy(true); setErr(null);
    try {
      const sel = form?.rel.selection;
      const r = await api<{ sus_score: number | null }>("/study/survey", { body: {
        sus: susAnswered === 10 ? sus : undefined,
        ratings: sel && relAnswered === shown.length && shown.length ? shown.map((x) => ({ ref: x.ref, rating: rate[x.ref] })) : undefined,
        need_id: sel?.need_id, version: sel?.version,
        belief: belief ?? undefined, grade_fit: fit ?? undefined, tags: tags.length ? tags : undefined, comment: comment.trim() || undefined,
      } });
      setDone(r);
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  }

  return (
    <Modal open={open} onClose={onClose} title="Короткая анкета (необязательно)">
      {done ? (
        <div className="space-y-4">
          <p className="text-sm text-brand-ink/80">Спасибо, ответы сохранены без имени и почты.{done.sus_score != null ? ` Ваша оценка удобства по шкале SUS: ${Math.round(done.sus_score)} из 100.` : ""}</p>
          <button type="button" onClick={onClose} className="btn-primary">Закрыть</button>
        </div>
      ) : !form ? (err ? <Alert>{err}</Alert> : <Loading />) : (
        <div className="space-y-5">
          <div ref={top} />
          <p className="text-xs text-brand-ink/65">Шаг {step + 1} из {steps.length}. Можно ответить на любую часть или закрыть окно: результат это не меняет. Анкета без имени и почты.</p>

          {kind === "sus" && (
            <section aria-label="Шкала удобства SUS">
              <h3 className="text-base font-bold text-brand-night">Удобство платформы</h3>
              <p className="mt-1 text-xs text-brand-ink/65">1 — {form.sus.scale[0].toLowerCase()}, 5 — {form.sus.scale[4].toLowerCase()}.</p>
              <ol className="mt-3 space-y-4">
                {form.sus.items.map((t, i) => (
                  <li key={i}>
                    <p className="mb-1.5 text-sm text-brand-ink">{i + 1}. {t}</p>
                    <Scale value={sus[i]} label={`Пункт ${i + 1}`} titles={form.sus.scale} onChange={(v) => setSus((a) => a.map((x, j) => (j === i ? v : x)))} />
                  </li>
                ))}
              </ol>
              {susAnswered > 0 && <button type="button" onClick={() => setSus(Array(10).fill(null))} className="mt-3 text-xs font-medium text-brand-plum underline">Пропустить шкалу ({susAnswered} из 10 заполнено)</button>}
            </section>
          )}

          {kind === "rel" && (
            <section aria-label="Оценка подборки">
              <h3 className="text-base font-bold text-brand-night">Первые пять кандидатов подборки</h3>
              <p className="mt-1 text-xs text-brand-ink/65">Насколько каждый подходит вашей потребности: 1 — совсем не подходит, 5 — подходит полностью. Кандидаты демонстрационные: профили смоделированы.</p>
              <ul className="mt-3 space-y-3">
                {shown.map((x) => (
                  <li key={x.ref} className="rounded-xl bg-[#F3F2FB] p-3">
                    <p className="text-sm font-semibold text-brand-night">{x.rank}. {x.category ?? "Кандидат"} <span className="font-normal text-brand-ink/65">· {x.ref}</span></p>
                    {x.reasons.length > 0 && <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-brand-ink/75">{x.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
                    <div className="mt-2"><Scale value={rate[x.ref] ?? null} label={`Оценка кандидата ${x.rank}`} titles={form.rel.scale} onChange={(v) => setRate((a) => ({ ...a, [x.ref]: v }))} /></div>
                  </li>
                ))}
              </ul>
              {relAnswered > 0 && <button type="button" onClick={() => setRate({})} className="mt-3 text-xs font-medium text-brand-plum underline">Пропустить оценку ({relAnswered} из {shown.length})</button>}
            </section>
          )}

          {kind === "final" && (
            <section aria-label="Грейд и замечания" className="space-y-5">
              {form.belief && (
                <div>
                  <p className="text-sm font-semibold text-brand-night">{form.belief.q}</p>
                  <p className="mb-1.5 text-xs text-brand-ink/65">1 — совсем не верю, 5 — полностью верю.</p>
                  <Scale value={belief} label="Доверие к грейду" onChange={setBelief} />
                </div>
              )}
              {form.grade_fit && (
                <div>
                  <p className="mb-1.5 text-sm font-semibold text-brand-night">{form.grade_fit.q}</p>
                  <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="Соответствие грейда">
                    {Object.entries(form.grade_fit.options).map(([k, t]) => (
                      <button key={k} type="button" role="radio" aria-checked={fit === k} onClick={() => setFit(fit === k ? null : k)}
                        className={`min-h-[44px] rounded-xl border px-1 text-sm font-semibold ${fit === k ? "border-brand-strong bg-brand-strong text-white" : "border-brand-night/15 bg-white text-brand-night hover:bg-brand-blush/50"}`}>{t}</button>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <p className="mb-1.5 text-sm font-semibold text-brand-night">Что мешало?</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(form.tags).map(([k, t]) => (
                    <button key={k} type="button" aria-pressed={tags.includes(k)} onClick={() => setTags((a) => (a.includes(k) ? a.filter((x) => x !== k) : [...a, k]))}
                      className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${tags.includes(k) ? "border-brand-strong bg-brand-strong text-white" : "border-brand-night/15 bg-white text-brand-night hover:bg-brand-blush/50"}`}>{t}</button>
                  ))}
                </div>
                <label htmlFor="study-comment" className="label mt-3">Своими словами</label>
                <textarea id="study-comment" className="input" rows={3} maxLength={form.text_max} value={comment} onChange={(e) => setComment(e.target.value)}
                  placeholder="Одно-два предложения. Почту, телефон и ссылки не указывайте: они удаляются." />
              </div>
            </section>
          )}

          {err && <Alert>{err}</Alert>}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-brand-night/10 pt-4">
            <button type="button" onClick={onClose} className="text-sm font-medium text-brand-ink/70 underline">Закрыть без ответа</button>
            <div className="flex gap-2">
              {step > 0 && <button type="button" onClick={() => { setErr(null); setStep(step - 1); }} className="btn-ghost !px-4 !py-2">Назад</button>}
              {step < steps.length - 1
                ? <button type="button" onClick={() => { setErr(null); setStep(step + 1); }} className="btn-primary !px-4 !py-2">Далее</button>
                : <button type="button" disabled={busy || !anything} onClick={() => void submit()} className="btn-primary !px-4 !py-2">{busy ? "Отправляем…" : "Отправить"}</button>}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
