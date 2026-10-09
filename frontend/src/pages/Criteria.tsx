import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { Alert, errText, Loading, NB, num, pct, signed, useApi } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { juryLogin, type Persona } from "../lib/jury";
import { usePageTitle } from "../lib/meta";

/** «Проверьте нас по критериям ТЗ» (К1): раздел 6 ТЗ дословно по подпунктам → что сделать → что увидите → чем доказано
 *  → ограничение. Тексты и числа — из GET /api/validation/criteria (backend/app/modules/validation/criteria.py, тот же
 *  источник, что docs/CRITERIA.md); числа — из расчётов /validation с подписью мира, на странице их не пишем. */

type Go = { label: string; to: string; as: Persona | null; need: string | null };
type Sig = { world?: string; seed?: number | null; commit?: string | null; generated_at?: string | null; n?: number | null };
type Proof =
  | { kind: "metric"; label: string; fmt: string; value: number; ci?: number[] | null; vs?: { label: string; value: number; fmt?: string } | null;
      note?: string | null; anchor: string; signature?: Sig }
  | { kind: "link"; label: string; anchor: string; missing?: boolean }
  | { kind: "doc"; label: string; path: string };
type Item = { id: string; n: string; tz: string; do: Go[]; see: string; proof: Proof; limit: string };
type Crit = { id: string; n: number; title: string; short: string; weight: number; items: Item[] };
type Out = {
  criteria: Crit[]; unique: { title: string; text: string; note?: string; do: Go[] }[]; how_to_read: string;
  pitch: { n: number; title: string; weight: number; tz: string }; personas: Record<string, string>;
};

const fmt = (v: number | null | undefined, f: string) =>
  f === "pct1" ? pct(v, 1) : f === "pct" ? pct(v) : f === "signed3" ? signed(v, 3) : num(v, f === "num1" ? 1 : f === "num2" ? 2 : 3);

/** Адрес ссылки «что сделать»: с персоной — вход в один клик в свою песочницу (/jury/go), без — сам экран. */
export function goHref(g: Go): string {
  if (!g.as) return g.to;
  const q = new URLSearchParams({ as: g.as, to: g.to });
  if (g.need) q.set("need", g.need);
  return `/jury/go?${q}`;
}

function GoLink({ g, personas, dark = false }: { g: Go; personas: Record<string, string>; dark?: boolean }) {
  const who = g.as ? personas[g.as] : null;
  const cls = dark
    ? "bg-white/10 text-white ring-1 ring-white/20 hover:bg-white/20"
    : g.as ? "bg-brand-night text-white hover:bg-brand-plum" : "bg-white text-brand-night ring-1 ring-brand-night/15 hover:ring-brand/50";
  const inner = <>{g.label}{who && <span className={dark ? "font-medium text-white/65" : "font-medium text-white/70"}>{` · ${who}`}</span>}</>;
  const props = { className: `inline-block max-w-full rounded-lg px-2.5 py-1.5 text-left text-xs font-semibold leading-snug transition-colors [overflow-wrap:anywhere] ${cls}`,
    "data-criteria-link": g.to, title: who ? `Вход в один клик в вашу копию демо: ${who}` : undefined };
  // /api/… — не экран SPA: обычная ссылка (документация API, статус сервиса)
  return g.to.startsWith("/api/") ? <a href={g.to} {...props}>{inner}</a> : <Link to={goHref(g)} {...props}>{inner}</Link>;
}

function SigLine({ s }: { s?: Sig }) {
  if (!s) return null;
  const commit = s.commit && !["unknown", "не записан"].includes(s.commit) ? s.commit : null;
  const parts = [s.world, s.n != null && !s.seed ? `n${NB}=${NB}${s.n}` : null, s.seed != null ? `seed${NB}${s.seed}` : null,
    commit ? `коммит ${commit}` : "коммит не записан", s.generated_at ? `расчёт ${s.generated_at.slice(8, 10)}.${s.generated_at.slice(5, 7)}` : null];
  return <p className="mt-1 text-[11px] leading-snug text-brand-ink/65 [overflow-wrap:anywhere]" data-testid="criteria-signature">Мир: {parts.filter(Boolean).join(" · ")}</p>;
}

function ProofView({ p }: { p: Proof }) {
  if (p.kind === "metric") {
    return (
      <div>
        <p className="text-xs leading-snug text-brand-ink/70">{p.label}</p>
        <p className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
          <span className="text-2xl font-extrabold tabular-nums text-brand-night" data-testid="criteria-value">{fmt(p.value, p.fmt)}</span>
          {p.ci && <span className="text-xs tabular-nums text-brand-ink/65">95{NB}% ДИ {fmt(p.ci[0], p.fmt)} … {fmt(p.ci[1], p.fmt)}</span>}
        </p>
        {(p.vs || p.note) && <p className="text-xs text-brand-ink/70">{p.vs && <>{p.vs.label}: <b className="tabular-nums">{fmt(p.vs.value, p.vs.fmt ?? p.fmt)}</b></>}{p.vs && p.note ? "; " : ""}{p.note}</p>}
        <SigLine s={p.signature} />
        <ProofLink to={p.anchor} text="Блок с расчётом" />
      </div>
    );
  }
  if (p.kind === "doc") {
    return <p className="text-sm text-brand-ink/80">{p.label}<span className="mt-0.5 block text-xs text-brand-ink/65">в репозитории: <code className="[overflow-wrap:anywhere]">{p.path}</code></span></p>;
  }
  return <ProofLink to={p.anchor} text={p.label} />;
}

function ProofLink({ to, text }: { to: string; text: string }) {
  return <Link to={to} data-criteria-link={to} className="mt-1 inline-block text-sm font-semibold text-brand-plum underline-offset-2 hover:underline">{text} →</Link>;
}

export default function Criteria() {
  usePageTitle("Проверка по критериям ТЗ");
  const { data, error, loading } = useApi<Out>("/validation/criteria", []);
  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content px-4 py-10 sm:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-plum">Для экспертов жюри</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-brand-night md:text-4xl">Проверьте нас по критериям ТЗ</h1>
        {loading ? <div className="mt-8"><Loading /></div> : error || !data ? <div className="mt-8"><Alert>{error ?? "Нет данных"}</Alert></div> : <Body d={data} />}
      </main>
      <SiteFooter />
    </div>
  );
}

function Body({ d }: { d: Out }) {
  return (
    <>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-brand-ink/75">{d.how_to_read}</p>
      <nav className="mt-5 flex flex-wrap gap-2 text-sm" aria-label="Критерии">
        <a href="#unique" className="rounded-full bg-brand-night px-3 py-1.5 font-semibold text-white hover:bg-brand-plum">Только здесь</a>
        {d.criteria.map((c) => (
          <a key={c.id} href={`#${c.id}`} className="rounded-full bg-white px-3 py-1.5 font-medium text-brand-night ring-1 ring-brand-night/10 hover:ring-brand/40">
            {c.n}. {c.short} <span className="tabular-nums text-brand-ink/65">{c.weight}{NB}%</span>
          </a>
        ))}
      </nav>

      <section id="unique" className="mt-8 scroll-mt-20 rounded-3xl bg-brand-night p-5 text-white md:p-7" aria-labelledby="unique-t">
        <h2 id="unique-t" className="text-xl font-extrabold tracking-tight md:text-2xl">Что можно проверить только здесь</h2>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {d.unique.map((u) => (
            <li key={u.title} className="flex min-w-0 flex-col rounded-2xl bg-white/[0.06] p-4 ring-1 ring-white/10">
              <p className="font-bold leading-snug">{u.title}</p>
              <p className="mt-1.5 text-sm leading-snug text-white/75">{u.text}</p>
              {u.note && <p className="mt-1.5 text-xs leading-snug text-brand-blush/90">{u.note}</p>}
              <div className="mt-auto flex flex-wrap gap-1.5 pt-3">{u.do.map((g) => <GoLink key={g.label} g={g} personas={d.personas} dark />)}</div>
            </li>
          ))}
        </ul>
      </section>

      {d.criteria.map((c) => (
        <section key={c.id} id={c.id} className="mt-10 scroll-mt-20" aria-labelledby={`${c.id}-t`}>
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 id={`${c.id}-t`} className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">{c.n}. {c.title}</h2>
            <span className="chip tabular-nums">вес {c.weight}{NB}%</span>
          </div>
          <div className="mt-3 rounded-2xl border border-brand-night/10 bg-white px-4 sm:px-6">
            {c.items.map((it) => <Row key={it.id} it={it} personas={d.personas} />)}
          </div>
        </section>
      ))}

      <p className="mt-10 rounded-2xl bg-white p-4 text-sm leading-relaxed text-brand-ink/75 ring-1 ring-brand-night/10">
        <b className="text-brand-night">{d.pitch.n}. {d.pitch.title} — {d.pitch.weight}{NB}%.</b> «{d.pitch.tz}» В продукте не проверяется.
      </p>
    </>
  );
}

function Row({ it, personas }: { it: Item; personas: Record<string, string> }) {
  return (
    <article id={it.id} className="grid scroll-mt-20 gap-3 border-t border-brand-night/10 py-4 first:border-t-0 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] lg:gap-6" data-testid="criteria-item">
      <div className="min-w-0">
        <p className="text-sm font-semibold leading-snug text-brand-night"><span className="mr-1.5 tabular-nums text-brand-lavender">{it.n}</span>«{it.tz}»</p>
        <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-brand-ink/65">Что сделать</p>
        <div className="mt-1 flex flex-wrap gap-1.5">{it.do.map((g) => <GoLink key={g.label} g={g} personas={personas} />)}</div>
      </div>
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-brand-ink/65">Что увидите</p>
        <p className="mt-1 text-sm leading-snug text-brand-ink/85">{it.see}</p>
        <p className="mt-2 text-xs leading-snug text-brand-ink/65"><b className="font-semibold text-brand-ink/80">Ограничение:</b> {it.limit}</p>
      </div>
      <div className="min-w-0" data-testid={`proof-${it.id}`}>
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-brand-ink/65">Чем доказано</p>
        <div className="mt-1"><ProofView p={it.proof} /></div>
      </div>
    </article>
  );
}

const PERSONAS = new Set<Persona>(["candidate", "candidate_nofsp", "candidate_junior", "candidate_new", "employer", "expert", "fsp"]);
const safePath = (to: string | null) => (to && to.startsWith("/") && !to.startsWith("//") ? to : null);

/** /jury/go?as=<персона>&to=<экран#якорь>[&need=<фрагмент названия потребности>]: глубокая ссылка в свою песочницу
 *  жюри — вход в один клик под персоной (как на главной) и переход на экран. need — открыть подборку демо-потребности:
 *  у каждой песочницы свои id, поэтому потребность ищется по названию. */
export function JuryGo() {
  const [sp] = useSearchParams();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const as = sp.get("as") as Persona, to = safePath(sp.get("to")), need = sp.get("need");
    if (!PERSONAS.has(as) || !to) { setErr("Ссылка неполная: нет роли или экрана."); return; }
    let off = false;
    const enter = async () => {
      let dest = await juryLogin(as, signIn, to);
      if (need && dest === to) {
        const needs = await api<{ id: string; title: string; raw_text: string }[]>("/employer/needs");
        const q = need.toLowerCase();
        const n = needs.find((x) => `${x.title} ${x.raw_text}`.toLowerCase().includes(q));
        const hash = to.includes("#") ? to.slice(to.indexOf("#")) : "";
        if (n) dest = `/employer/needs/${n.id}${hash}`;
      }
      if (!off) navigate(dest, { replace: true });
    };
    (async () => {
      try { await enter(); }
      catch (e) {
        // сбой сервера на входе (5xx) — одна повторная попытка, дальше честное сообщение
        if (!(e instanceof ApiError && e.status >= 500)) { if (!off) setErr(errText(e)); return; }
        await new Promise((r) => setTimeout(r, 1500));
        try { if (!off) await enter(); } catch (e2) { if (!off) setErr(errText(e2)); }
      }
    })();
    return () => { off = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <main id="main" className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
      <h1 className="sr-only">Вход в копию демо для жюри</h1>
      <div className="flex flex-col items-center gap-4" role="status">
      {err ? (
        <>
          <p className="max-w-sm text-sm text-brand-ink/80">{err}</p>
          <div className="flex flex-wrap justify-center gap-3">
            <button type="button" className="btn-primary" onClick={() => location.reload()}>Повторить</button>
            <Link to="/#jury" className="btn-ghost">Демо-учётки на главной</Link>
            <Link to="/criteria" className="btn-ghost">К критериям ТЗ</Link>
          </div>
        </>
      ) : <p className="text-sm text-brand-ink/70" aria-busy="true">Входим в вашу копию демо…</p>}
      </div>
    </main>
  );
}
