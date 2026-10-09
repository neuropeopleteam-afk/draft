import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { AttemptsCompare, type Comparison } from "../../components/AttemptsCompare";
import { Alert, DIRECTIONS, Empty, GRADES, Loading, dtt, num, signed, useApi } from "../../components/ui";

/** Две попытки теста рядом (И26): θ ± погрешность, точность, грейд и статус, время, повторы заданий, что изменилось. */

type Item = { id: string; mode_title: string; claimed_grade: string; finished_at: string | null; theta: number | null; se: number | null;
  status_title: string; grade_after: string | null; is_sandbox: boolean; n_items: number };
type Data = { direction: string | null; attempts: Item[]; comparison: Comparison | null; sandbox: boolean; retake_grade: string | null;
  can_retake_now: boolean; retake_reason: string | null; note: string | null };

const label = (x: Item, i: number) =>
  `${i + 1}. ${dtt(x.finished_at)} · ${GRADES[x.claimed_grade] ?? x.claimed_grade} · θ ${x.theta == null ? "—" : `${signed(x.theta)} ± ${num(x.se)}`}`;

export default function Attempts() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const direction = params.get("direction");
  const a = params.get("a");
  const b = params.get("b");
  const qs = new URLSearchParams();
  if (direction) qs.set("direction", direction);
  if (a && b) { qs.set("a", a); qs.set("b", b); }
  const { data, error, loading } = useApi<Data>(`/assessment/attempts?${qs.toString()}`, [qs.toString()]);
  if (loading && !data) return <Loading />;
  if (error || !data) return <Alert>{error}</Alert>;
  const items = data.attempts;
  const cmp = data.comparison;
  const pick = (k: "a" | "b", id: string) => {
    const next = new URLSearchParams(params);
    const cur = { a: cmp?.first.id ?? "", b: cmp?.second.id ?? "", [k]: id };
    if (cur.a === cur.b) return;  // одну и ту же попытку с собой не сравниваем
    next.set("a", cur.a); next.set("b", cur.b);
    if (data.direction) next.set("direction", data.direction);
    setParams(next, { replace: true });
  };
  const retake = () => navigate(`/candidate/assessment?grade=${data.retake_grade}&direction=${data.direction}`);
  const retakeBox = data.retake_grade && (
    <div className="flex flex-wrap items-center gap-3">
      <button className="btn-primary" disabled={!data.can_retake_now} onClick={retake}>
        {data.sandbox ? "Пройти ещё раз (демо)" : `Пройти тест на ${GRADES[data.retake_grade]} ещё раз`}
      </button>
      <span className="min-w-0 text-xs text-brand-ink/65">
        {data.sandbox ? data.note : data.can_retake_now ? "Повтор доступен по правилам 30/90 дней." : data.retake_reason}
      </span>
    </div>
  );

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Две попытки рядом" subtitle={`${DIRECTIONS[data.direction ?? ""] ?? "Тест"}: что изменилось между попытками и почему. Повтор выдаётся из другого набора заданий банка.`} />
      {items.length < 2 ? (
        <Empty title={items.length ? "Пока одна попытка" : "Попыток ещё нет"}
          text={items.length ? "Сравнение появится после второй завершённой попытки в этом направлении." : "Пройдите тест — затем повторите его, чтобы увидеть две попытки рядом."}
          action={retakeBox || <Link className="btn-primary" to="/candidate/assessment">Пройти тест</Link>} />
      ) : (
        <>
          {items.length > 2 && cmp && (
            <section className="card grid gap-3 sm:grid-cols-2" aria-label="Выбор попыток">
              {(["a", "b"] as const).map((k, n) => (
                <label key={k} className="min-w-0 text-sm">
                  <span className="font-semibold text-brand-night">Попытка {n + 1}</span>
                  <select className="input mt-1 w-full" value={k === "a" ? cmp.first.id : cmp.second.id} onChange={(e) => pick(k, e.target.value)}>
                    {items.map((x, i) => <option key={x.id} value={x.id}>{label(x, i)}</option>)}
                  </select>
                </label>
              ))}
              <p className="text-xs text-brand-ink/65 sm:col-span-2">По умолчанию — две последние попытки; порядок — по времени завершения.</p>
            </section>
          )}
          {cmp && <section className="card"><AttemptsCompare cmp={cmp} level={2} /></section>}
          {retakeBox}
        </>
      )}
      <p className="text-xs text-brand-ink/65">
        Стабильность при повторе на синтетической популяции и доля повторов заданий между попытками — на <Link className="font-semibold text-brand" to="/validation#retest">/validation</Link> (модель, не люди).
      </p>
    </div>
  );
}
