import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Level, LevelLegend, Loading, Modal, Status, dt, useApi } from "../../components/ui";
import { InviteForm, ProbeForm } from "./Contact";

interface Cell { level: string; status: string; text: string; value?: number; best?: boolean }
interface Row { key: string; group: string; title: string; requirement?: string | null; quote?: string | null; weight?: number | null; hint?: string }
interface Cand {
  ref: string; category: { id: string; title: string } | null; grade: string | null; score: number; rank_in_selection: number | null;
  cells: Record<string, Cell>; market_range: { from: number; to: number; median?: number } | null;
  can_invite: boolean; invite_available_at: string | null; last_invitation_status: string | null; probe_active: boolean;
}
interface CompareOut { need: { id: string; title: string; raw_text: string; version: number | null }; rows: Row[]; candidates: Cand[]; selection_total: number }

const STATUS_TEXT: Record<string, string> = {
  confirmed: "text-brand-ink", partial: "text-brand-ink/80", declared: "text-brand-ink/60", missing: "text-brand-ink/45",
  mismatch: "text-brand-plum", neutral: "text-brand-ink/60", info: "text-brand-ink/80",
};

/** Сравнение 2–3 кандидатов рядом по требованиям потребности; отсюда — сразу зонд или приглашение. */
export function Compare() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const refs = (sp.get("refs") ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  const v = sp.get("v");
  const qs = new URLSearchParams();
  refs.forEach((r) => qs.append("refs", r));
  if (v) qs.set("version", v);
  const { data, loading, error, reload } = useApi<CompareOut>(`/employer/needs/${id}/compare?${qs.toString()}`, [sp.toString()]);
  const [probe, setProbe] = useState<string[] | null>(null);
  const [invite, setInvite] = useState<Cand | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error || !data) return <div className="max-w-3xl space-y-4"><Alert>{error}</Alert><Link to={`/employer/needs/${id}`} className="btn-ghost">К подборке</Link></div>;
  const cs = data.candidates;
  const market = cs.find((c) => c.market_range)?.market_range ?? null;
  const groups: { group: string; rows: Row[] }[] = [];
  for (const r of data.rows) {
    const g = groups.at(-1);
    if (g && g.group === r.group) g.rows.push(r); else groups.push({ group: r.group, rows: [r] });
  }
  const back = `/employer/needs/${id}${data.need.version ? `/v/${data.need.version}` : ""}`;
  const cols = `minmax(14rem,18rem) repeat(${cs.length}, minmax(15rem,1fr))`;

  return (
    <div className="max-w-6xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title="Сравнение кандидатов" subtitle={`«${data.need.title}»${data.need.version ? `, подборка v${data.need.version}` : ""}. Рядом — только факты по требованиям потребности; заявленное кандидатом (T0) в скор не входит. Кандидаты обезличены.`} />
        <div className="flex flex-wrap gap-2">
          <Link to={back} className="btn-ghost">К подборке</Link>
          <button className="btn-primary" disabled={!cs.some((c) => !c.probe_active)} onClick={() => setProbe(cs.filter((c) => !c.probe_active).map((c) => c.ref))}>Зонд всем ({cs.filter((c) => !c.probe_active).length})</button>
        </div>
      </div>
      {done && <Alert kind="ok">{done}</Alert>}
      <LevelLegend />
      <div className="overflow-x-auto rounded-2xl border border-brand-night/10">
        <div role="table" aria-label="Сравнение кандидатов" className="min-w-max" style={{ display: "grid", gridTemplateColumns: cols }}>
          <div role="row" className="contents">
            <div role="columnheader" className="sticky left-0 z-10 border-b border-brand-night/10 bg-white p-4 text-xs text-brand-ink/60">
              Требование потребности и цитата из текста
            </div>
            {cs.map((c) => (
              <div key={c.ref} role="columnheader" className="space-y-2 border-b border-l border-brand-night/10 bg-[#F7F6FB] p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-mono text-sm font-bold text-brand-night">{c.ref}</p>
                  {c.rank_in_selection && <span className="text-xs text-brand-ink/55">место {c.rank_in_selection} из {data.selection_total}</span>}
                </div>
                <p className="text-sm text-brand-ink/75">{c.category?.title ?? "без категории"}</p>
                <p className="text-2xl font-bold text-brand">{Math.round(c.score * 100)}<span className="text-sm font-semibold text-brand-ink/50"> из 100</span></p>
                <div className="flex flex-wrap gap-1.5">
                  <button className="btn-ghost !px-3 !py-1.5 text-xs" disabled={c.probe_active} title={c.probe_active ? "Зонд уже отправлен и ждёт ответа" : undefined} onClick={() => setProbe([c.ref])}>
                    {c.probe_active ? "Зонд отправлен" : "Зонд"}
                  </button>
                  <button className="btn-primary !px-3 !py-1.5 text-xs" disabled={!c.can_invite} onClick={() => setInvite(c)}>Пригласить</button>
                  <Link className="btn-ghost !px-3 !py-1.5 text-xs" to={`/employer/candidates/${c.ref}?need=${id}`}>Карточка</Link>
                </div>
                {!c.can_invite && <p className="text-xs text-brand-ink/55">Повторное приглашение — с {c.invite_available_at ? dt(c.invite_available_at) : "позже"}</p>}
                {c.last_invitation_status && <div className="text-xs"><Status s={c.last_invitation_status} /></div>}
              </div>
            ))}
          </div>
          {groups.map((g) => (
            <div key={g.group} role="rowgroup" className="contents">
              <div role="row" className="contents">
                <div className="sticky left-0 z-10 border-b border-brand-night/10 bg-white px-4 pb-1 pt-4 text-[11px] font-bold uppercase tracking-[0.12em] text-brand-lavender">{g.group}</div>
                {cs.map((c) => <div key={c.ref} className="border-b border-l border-brand-night/10 bg-white" />)}
              </div>
              {g.rows.map((r) => (
                <div key={r.key} role="row" className="contents">
                  <div role="rowheader" className="sticky left-0 z-10 border-b border-brand-night/10 bg-white p-4 text-sm" title={r.hint}>
                    <p className="font-semibold text-brand-night">{r.title}{r.weight != null && <span className="font-normal text-brand-ink/50"> · вес {r.weight.toLocaleString("ru-RU")}</span>}</p>
                    {r.requirement && <p className="text-xs text-brand-ink/70">нужно: {r.requirement}</p>}
                    {r.quote && <p className="mt-1 text-xs"><span className="rounded bg-brand-blush/60 px-1 text-brand-night">«{r.quote}»</span></p>}
                    {r.hint && <p className="mt-1 text-[11px] leading-snug text-brand-ink/45">{r.hint}</p>}
                  </div>
                  {cs.map((c) => {
                    const cell = c.cells[r.key];
                    return (
                      <div key={c.ref} role="cell" className={`border-b border-l border-brand-night/10 p-4 text-sm ${cell?.best ? "bg-emerald-50/70" : ""}`}>
                        {!cell ? <span className="text-brand-ink/40">—</span> : (
                          <div className="flex items-start gap-2">
                            {cell.level !== "market" && <Level level={cell.level} />}
                            <p className={STATUS_TEXT[cell.status] ?? ""}>{cell.text}{cell.best && <span className="ml-1 whitespace-nowrap text-xs font-semibold text-emerald-700">лучше в строке</span>}</p>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
      <p className="text-xs text-brand-ink/55">Пол, возраст, имя и фото в сравнении и в ранжировании не участвуют. Контакты откроются только после того, как кандидат примет приглашение.</p>
      <Modal open={!!probe} onClose={() => setProbe(null)} title={`Зонд для ${probe?.length ?? 0} канд.`}>
        {probe && <ProbeForm refs={probe} needId={id} market={market} onDone={() => { setProbe(null); setDone("Зонд отправлен. Ответы появятся в разделе «Зонды»."); reload(); }} />}
      </Modal>
      <Modal open={!!invite} onClose={() => setInvite(null)} title={`Приглашение ${invite?.ref ?? ""}`}>
        {invite && <InviteForm cref={invite.ref} needId={id} market={invite.market_range ?? market} onDone={() => { setInvite(null); setDone(`Приглашение ${invite.ref} отправлено. Контакты откроются после согласия кандидата.`); reload(); }} />}
      </Modal>
    </div>
  );
}

/** Вход в сравнение из проводника жюри: самая ранняя потребность, где в подборке не меньше двух кандидатов. */
export function CompareLanding() {
  const { data, loading, error } = useApi<any[]>("/employer/needs");
  const navigate = useNavigate();
  const pick = (data ?? []).slice().reverse().find((n) => (n.versions?.at(-1)?.total ?? 0) >= 2);
  useEffect(() => {
    if (pick) navigate(`/employer/needs/${pick.id}/compare?v=${pick.versions.at(-1).version}`, { replace: true });
  }, [pick?.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  if (!pick) return <Empty title="Сравнивать пока некого" text="Создайте потребность — в подборке отметьте 2–3 кандидатов и нажмите «Сравнить выбранных»." action={<Link to="/employer/needs" className="btn-primary">К потребностям</Link>} />;
  return <Loading />;
}
