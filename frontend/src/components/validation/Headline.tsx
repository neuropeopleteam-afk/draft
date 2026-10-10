import { Alert, Loading, NB, num, pct, signed, useApi } from "../ui";
import { ProvenanceLine, RetestVsTruth } from "./Provenance";

/** Первый экран /validation: «5 чисел, которые доказывают механику» (backend: app/modules/validation/headline.py).
 *  Каждое число — из расчёта с подписью мира; нет расчёта — нет числа. */

export type Signature = { world?: string; seed?: number; config_hash?: string; commit?: string; command?: string; generated_at?: string; n?: number };

export function SignatureLine({ s, className = "" }: { s?: Signature | null; className?: string }) {
  if (!s) return null;
  return (
    <p className={`text-[11px] leading-snug text-brand-ink/65 [overflow-wrap:anywhere] ${className}`} data-testid="world-signature">
      Мир: {s.world ?? "—"} · seed{NB}{s.seed ?? "—"} · конфигурация <code>{s.config_hash ?? "—"}</code> · коммит <code>{s.commit ?? "—"}</code>{s.command ? <> · <code>{s.command}</code></> : null}
    </p>
  );
}

const fmt = (v: number | null | undefined, f: string) => (f === "pct" ? pct(v) : f === "signed3" ? signed(v, 3) : num(v, 3));

export default function Headline() {
  const { data, error, loading } = useApi<any>("/validation/headline", []);
  if (loading) return <div className="mt-8"><Loading /></div>;
  if (error) return <div className="mt-8"><Alert>{error}</Alert></div>;
  if (!data || data.missing) return <div className="mt-8"><Alert kind="info">Ключевые числа ещё не посчитаны: make path-retest и make bench.</Alert></div>;
  return (
    <section id="headline" className="mt-8 scroll-mt-20" aria-labelledby="headline-t" data-testid="validation-headline">
      <h2 id="headline-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">5 чисел, которые доказывают механику</h2>
      <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">{data.how_to_read}</p>
      <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {data.items.map((it: any, i: number) => (
          <li key={it.id} className="card flex min-w-0 flex-col" data-testid={`headline-${it.id}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{i + 1}. {it.title}</p>
            <p className="mt-2 text-3xl font-extrabold tabular-nums text-brand-night">{fmt(it.value, it.format)}</p>
            {it.ci && <p className="text-xs tabular-nums text-brand-ink/70">95{NB}% ДИ: {fmt(it.ci[0], it.format)} … {fmt(it.ci[1], it.format)}</p>}
            {it.pair && <p className="text-xs tabular-nums text-brand-ink/70">nDCG@10: {num(it.pair[0], 3)} против {num(it.pair[1], 3)}</p>}
            <p className="mt-2 text-sm leading-snug text-brand-ink/80">{it.text}</p>
            {it.note && <p className="mt-1 text-xs text-brand-ink/65">{it.note}</p>}
            <div className="mt-auto pt-3">
              <a href={`#${it.anchor}`} className="text-sm font-semibold text-brand-plum underline">Подробнее в разделе</a>
              <ProvenanceLine p={it.provenance} className="mt-1.5" />
              <SignatureLine s={it.signature} className="mt-1" />
            </div>
          </li>
        ))}
      </ol>
      <RetestVsTruth v={data.retest_vs_truth} className="mt-3" />
    </section>
  );
}
