import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { GradeBadge, type GradeStatusInfo } from "../../components/GradeStatus";
import { Alert, DemoProfileBadge, Empty, Level, LevelLegend, Loading, Modal, Status, dt, plainText as ruText, useApi } from "../../components/ui";
import { ProbeForm, inviteBlockedText, inviteSentText, probeSentText } from "./Contact";
import { ReasonLevel } from "../../components/CandidateCard";  // Ф6 (Н5)
import { ExecAdvisor } from "../../components/ExecAdvisor";  // Н1: ИИ-советник руководителя (живой диалог)
import { DecisionProofStrip } from "../../components/UnderTheHood";
import { InviteDialog } from "../../components/InviteDialog";  // KF3 «Оффер в один клик»: вилка, Mutual Draft Score, слоты
import { PassportCryptoChip } from "../../passport/Share";  // KF1 «Паспорт-щит»: значок «Паспорт Ed25519: действует»

interface Cell { level: string; status: string; text: string; value?: number; best?: boolean }
interface Row { key: string; group: string; title: string; requirement?: string | null; quote?: string | null; weight?: number | null; hint?: string }
interface Cand {
  ref: string; category: { id: string; title: string; provisional?: boolean } | null; grade: string | null; score: number; rank_in_selection: number | null;
  status?: GradeStatusInfo | null; claimed?: { title?: string; grade?: string } | null;
  cells: Record<string, Cell>; market_range: { from: number; to: number; median?: number } | null;
  can_invite: boolean; invite_available_at: string | null; last_invitation_status: string | null; probe_active: boolean;
}
interface WhyF { level: string; points: number; text: string }
interface Why { higher: string; lower: string; diff: number; summary: string; text: string; pro: WhyF[]; con: WhyF[]; core_note?: string | null }  // core_note — ядро роли (Я1), в балл не входит
interface CompareOut { need: { id: string; title: string; raw_text: string; version: number | null; requirements: any }; rows: Row[]; candidates: Cand[]; selection_total: number; why: Why[] }

const pts = (x: number) => Math.abs(x).toFixed(1).replace(".", ",");

/** Код кандидата «C-8D3YPW» не переносится по дефису. */
const nowrapRefs = (t: string) => t.split(/(C-[A-Z0-9]+)/).map((p, i) => (i % 2 ? <span key={i} className="whitespace-nowrap">{p}</span> : p));

/** «Почему A выше B»: вклад подтверждённых фактов в разницу скоров. */
function WhyBlock({ why }: { why: Why[] }) {
  if (!why?.length) return null;
  return (
    <section className="card space-y-3" aria-label="Почему один кандидат выше другого">
      <h2 className="text-sm font-bold text-brand-night">Почему выше</h2>
      {/* аудит №1: колонки по ширине блока, а не экрана — при узкой колонке (панель проводника) уровни не наезжают на текст */}
      {/* D3 п. 2: при открытой панели проводника (1440 px) пары не сжимаются уже 20rem — блок прокручивается по горизонтали */}
      <div className="-mx-1 overflow-x-auto px-1 pb-1" data-testid="why-scroll">
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {why.map((w) => (
          <li key={`${w.higher}-${w.lower}`} className="min-w-0 rounded-xl bg-[#F7F6FB] p-4 text-sm">
            <p className="font-semibold text-brand-night">{nowrapRefs(ruText(w.summary))}</p>
            {w.pro.length > 0 && (
              <ul className="mt-2.5 space-y-2">
                {w.pro.map((f, i) => (
                  <li key={i} className="rounded-lg bg-white/80 px-3 py-2 shadow-sm ring-1 ring-brand-night/5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="shrink-0"><Level level={f.level} /></span>
                      <span className="shrink-0 whitespace-nowrap font-semibold tabular-nums text-emerald-700">+{pts(f.points)}</span>
                    </div>
                    <p className="mt-1 min-w-0 text-brand-night/90 [overflow-wrap:anywhere]">{nowrapRefs(ruText(f.text).replace(/уровень\s+([+-]?\d+[.,]\d+\s*±\s*\d+[.,]\d+)\s+против\s+уровень\s+/gi, "оценка теста $1 против "))}</p>
                  </li>
                ))}
              </ul>
            )}
            {w.con.map((f, i) => (
              <div key={i} className="mt-2 rounded-lg bg-white/60 px-3 py-2 text-brand-ink/75 ring-1 ring-brand-night/5">
                <div className="flex items-center justify-between gap-2">
                  <span className="shrink-0"><Level level={f.level} /></span>
                  <span className="shrink-0 whitespace-nowrap font-semibold tabular-nums text-brand-plum">−{pts(f.points)}</span>
                </div>
                <p className="mt-1 min-w-0 [overflow-wrap:anywhere]">В пользу <span className="whitespace-nowrap font-medium">{w.lower}</span>: {nowrapRefs(ruText(f.text).replace(/уровень\s+([+-]?\d+[.,]\d+\s*±\s*\d+[.,]\d+)\s+против\s+уровень\s+/gi, "оценка теста $1 против "))}</p>
              </div>
            ))}
            {(() => {  // FIX7 п. 11: показаны топ-3 «за» и главный «против» — остаток разницы виден отдельной строкой
              const rest = w.diff - w.pro.reduce((t, f) => t + f.points, 0) - w.con.reduce((t, f) => t + f.points, 0);
              return Math.abs(rest) >= 0.1 ? <p className="mt-2 flex items-center justify-between gap-2 text-brand-ink/70" data-testid="why-rest">
                <span className="min-w-0 flex-1">Прочие сигналы — факторы меньшего веса и округление</span>
                <span className="shrink-0 whitespace-nowrap font-semibold tabular-nums">{rest > 0 ? "+" : "−"}{pts(rest)}</span></p> : null;
            })()}
            {w.core_note && <p className="mt-2 border-t border-brand-ink/10 pt-2 font-semibold text-amber-900" data-testid="why-core-note">{nowrapRefs(w.core_note.replace(/в скор не входит/gi, "в балл не входит"))}.</p>}
          </li>
        ))}
      </ul>
      </div>
      <p className="text-xs text-brand-ink/65">Баллы из 100 — вклад каждого факта в разницу. Учитывается только проверенное: тест, достижения из реестра ФСП, оценённые задания работодателя. Ядро роли (основной язык, фреймворк или специализация) в балл не входит — о нём отдельная строка.</p>
    </section>
  );
}

const STATUS_TEXT: Record<string, string> = {
  confirmed: "text-brand-ink", partial: "text-brand-ink/80", declared: "text-brand-ink/65", missing: "text-brand-ink/65",
  mismatch: "text-brand-plum", neutral: "text-brand-ink/65", info: "text-brand-ink/80", provisional: "text-amber-900",
  unconfirmed: "text-brand-ink/65",
};

/** Сравнение 2–3 кандидатов рядом по требованиям потребности; отсюда — сразу задание с вилкой или приглашение. */
export function Compare() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const refs = (sp.get("refs") ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  const v = sp.get("v");
  const qs = new URLSearchParams();
  refs.forEach((r) => qs.append("refs", r));
  if (v) qs.set("version", v);
  const { data, loading, error, reload } = useApi<CompareOut>(`/employer/needs/${id}/compare?${qs.toString()}`, [sp.toString()]);
  const navigate = useNavigate();
  const allNeeds = useApi<any[]>("/employer/needs");
  const ver = v ? Number(v) : data?.need?.version ?? 1;
  const selData = useApi<any>(id && ver ? `/employer/needs/${id}/selections/${ver}` : null, [id, ver]);
  const synByRef = new Map<string, any>((selData.data?.results ?? []).map((r: any) => [r.ref, r.card ?? r]));
  const [probe, setProbe] = useState<string[] | null>(null);
  const [invite, setInvite] = useState<Cand | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (loading && !data) {
    return (
      <div className="min-w-0 max-w-6xl space-y-5">
        <PageTitle title="Сравнение кандидатов" subtitle="Сопоставьте 2–3 кандидатов рядом по подтверждённым навыкам, результатам теста и достижениям ФСП, чтобы выбрать, кого пригласить." />
        <Loading />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="max-w-3xl space-y-4">
        <PageTitle title="Сравнение кандидатов" subtitle="Сопоставьте 2–3 кандидатов рядом по подтверждённым навыкам, результатам теста и достижениям ФСП, чтобы выбрать, кого пригласить." />
        <Alert>{error}</Alert>
        <Link to={`/employer/needs/${id}`} className="btn-ghost">К подборке</Link>
      </div>
    );
  }
  const cs = data.candidates;
  const market = cs.find((c) => c.market_range)?.market_range ?? null;
  const needSalary = { from: data.need.requirements?.salary_from, to: data.need.requirements?.salary_to, net: data.need.requirements?.salary_net };
  const groups: { group: string; rows: Row[] }[] = [];
  for (const r of data.rows) {
    const g = groups.at(-1);
    if (g && g.group === r.group) g.rows.push(r); else groups.push({ group: r.group, rows: [r] });
  }
  const back = `/employer/needs/${id}${data.need.version ? `/v/${data.need.version}` : ""}`;
  // D3 п. 2: колонка кандидата не уже 15rem — при открытой панели проводника «12 минут» (1440 px) числа и бейджи
  // не обрезаются и не наезжают: таблица прокручивается по горизонтали внутри своего контейнера
  const cols = `minmax(12rem,16rem) repeat(${cs.length}, minmax(15rem,1fr))`;

  return (
    <div className="w-full min-w-0 max-w-6xl space-y-5 overflow-x-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title="Сравнение кандидатов" subtitle={`«${data.need.title}»${data.need.version ? `, подборка, версия ${data.need.version}` : ""}. Рядом — только факты по требованиям потребности; сказанное кандидатом о себе в балл не входит. Кандидаты обезличены.`} />
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
          {(allNeeds.data?.length ?? 0) > 1 && (
            <select
              aria-label="Потребность для сравнения"
              className="w-full max-w-full truncate rounded-xl border border-brand-night/15 bg-white px-3 py-2 text-xs font-semibold text-brand-night sm:w-auto sm:max-w-xs"
              value={id}
              onChange={(e) => navigate(`/employer/needs/${e.target.value}/compare`)}
            >
              {allNeeds.data!.map((n: any) => (
                <option key={n.id} value={n.id}>{n.title}</option>
              ))}
            </select>
          )}
          <Link to={back} className="btn-ghost">К подборке</Link>
          <button className="btn-ghost" disabled={!cs.some((c) => !c.probe_active)} onClick={() => setProbe(cs.filter((c) => !c.probe_active).map((c) => c.ref))}>Задание всем ({cs.filter((c) => !c.probe_active).length})</button>
        </div>
      </div>
      <ExecAdvisor needId={id!} refs={cs.map((c) => c.ref)} version={data.need.version} />
      <DecisionProofStrip totalCandidates={data.selection_total} version={data.need.version} />
      {done && <Alert kind="ok">{done}</Alert>}
      <WhyBlock why={data.why} />
      <LevelLegend />
      <div className="max-w-full overflow-x-auto rounded-2xl border border-brand-night/10" data-testid="compare-scroll">
        <div role="table" aria-label="Сравнение кандидатов" style={{ display: "grid", gridTemplateColumns: cols, minWidth: `${12 + cs.length * 15}rem` }}>
          <div role="row" className="contents">
            <div role="columnheader" className="sticky left-0 z-10 border-b border-brand-night/10 bg-white p-4 text-xs text-brand-ink/65">
              Требование потребности и цитата из текста
            </div>
            {cs.map((c) => (
              <div key={c.ref} role="columnheader" className="space-y-2 border-b border-l border-brand-night/10 bg-[#F7F6FB] p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-mono text-sm font-bold text-brand-night">{c.ref}</p>
                  {c.rank_in_selection && <span className="text-xs text-brand-ink/65">место {c.rank_in_selection} из {data.selection_total}</span>}
                </div>
                <p className="text-sm text-brand-ink/75">{c.category?.title ?? (c.claimed?.title ? `заявлено: ${c.claimed.title}` : "без категории")}</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  <GradeBadge s={c.status} claimed={c.claimed} />
                  <DemoProfileBadge c={synByRef.get(c.ref) ?? c} />
                </div>
                <div><PassportCryptoChip refId={c.ref} /></div>
                <p className="text-2xl font-bold text-brand">{Math.round(c.score * 100)}<span className="text-sm font-semibold text-brand-ink/65"> из 100</span></p>
                <div className="flex flex-wrap gap-1.5">
                  <button className="btn-ghost !px-3 !py-1.5 text-xs" disabled={c.probe_active} title={c.probe_active ? "Задание уже отправлено и ждёт ответа" : "Короткое проверочное задание от вас"} onClick={() => setProbe([c.ref])}>
                    {c.probe_active ? "Задание отправлено" : "Задание"}
                  </button>
                  <button className="btn-primary !px-3 !py-1.5 text-xs" disabled={!c.can_invite} title={c.can_invite ? undefined : inviteBlockedText(c)} onClick={() => setInvite(c)}>Пригласить</button>
                  <Link className="btn-ghost !px-3 !py-1.5 text-xs" to={`/employer/candidates/${c.ref}?need=${id}${data.need.version ? `&v=${data.need.version}` : ""}`}>Карточка</Link>
                </div>
                {!c.can_invite && <p className="text-xs text-brand-ink/65">Повторное приглашение — с {c.invite_available_at ? dt(c.invite_available_at) : "позже"}</p>}
                {c.last_invitation_status && <div className="text-xs"><Status s={c.last_invitation_status} /></div>}
              </div>
            ))}
          </div>
          {groups.map((g) => (
            <div key={g.group} role="rowgroup" className="contents">
              <div role="row" className="contents">
                <div role="rowheader" className="sticky left-0 z-10 border-b border-brand-night/10 bg-white px-4 pb-1 pt-4 text-xs font-bold uppercase tracking-[0.12em] text-brand-lavender">{g.group}</div>
                {cs.map((c) => <div key={c.ref} role="cell" className="border-b border-l border-brand-night/10 bg-white" />)}
              </div>
              {g.rows.map((r) => (
                <div key={r.key} role="row" className="contents">
                  <div role="rowheader" className="sticky left-0 z-10 border-b border-brand-night/10 bg-white p-4 text-sm">
                    <p className="font-semibold text-brand-night">{ruText(r.title)}{r.weight != null && <span className="font-normal text-brand-ink/65"> · вес {r.weight.toLocaleString("ru-RU")}</span>}</p>
                    {r.requirement && <p className="text-xs text-brand-ink/70">нужно: {r.requirement}</p>}
                    {r.quote && <p className="mt-1 text-xs"><span className="rounded bg-brand-blush/60 px-1 text-brand-night">«{r.quote}»</span></p>}
                    {r.hint && <p className="mt-1 text-xs leading-snug text-brand-ink/65">{ruText(r.hint)}</p>}
                  </div>
                  {cs.map((c) => {
                    const cell = c.cells[r.key];
                    return (
                      <div key={c.ref} role="cell" className={`border-b border-l border-brand-night/10 p-4 text-sm ${cell?.best ? "bg-emerald-50/70" : ""}`}>
                        {!cell ? <span className="text-brand-ink/65">—</span> : (
                          <div className="flex flex-col items-start gap-1.5">
                            {cell.level !== "market" && <ReasonLevel r={{ ...cell, weight: r.weight }} />}
                            <p className={`min-w-0 flex-1 break-words ${STATUS_TEXT[cell.status] ?? ""}`}>{ruText(cell.text)}{cell.best && <span className="ml-1 whitespace-nowrap text-xs font-semibold text-emerald-700">лучше в строке</span>}</p>
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
      <p className="text-xs text-brand-ink/65">Пол, возраст, имя и фото в сравнении и в ранжировании не участвуют. Контакты откроются только после того, как кандидат примет приглашение.</p>
      <Modal open={!!probe} onClose={() => setProbe(null)} title={`Проверочное задание: ${probe?.length ?? 0} канд.`}>
        {probe && <ProbeForm refs={probe} needId={id} market={market} needSalary={needSalary} onDone={(r) => { setProbe(null); setDone(probeSentText(r) ?? "Задание никому не отправлено."); reload(); }} />}
      </Modal>
      <Modal open={!!invite} onClose={() => setInvite(null)} title={`Оффер в один клик: ${invite?.ref ?? ""}`}>
        {invite && <InviteDialog cref={invite.ref} needId={id} needTitle={data.need.title} market={invite.market_range ?? market} needSalary={needSalary}
          onDone={(inv) => { setInvite(null); const n = inv?.proposed_slots?.length ?? 0; setDone(inviteSentText(inv, invite.ref) + (n ? ` Предложено слотов собеседования: ${n} — кандидат забронирует один при принятии.` : "")); reload(); }} />}
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
  if (loading && !data) {
    return (
      <div className="max-w-3xl space-y-5">
        <PageTitle title="Сравнение кандидатов" subtitle="Сопоставьте 2–3 кандидатов рядом по требованиям вашей потребности и получите рекомендацию ИИ-советника." />
        <Loading />
      </div>
    );
  }
  if (error) {
    return (
      <div className="max-w-3xl space-y-5">
        <PageTitle title="Сравнение кандидатов" subtitle="Сопоставьте 2–3 кандидатов рядом по требованиям вашей потребности и получите рекомендацию ИИ-советника." />
        <Alert>{error}</Alert>
      </div>
    );
  }
  if (!pick) {
    return (
      <div className="max-w-3xl space-y-5">
        <PageTitle title="Сравнение кандидатов" subtitle="Сопоставьте 2–3 кандидатов рядом по требованиям вашей потребности и получите рекомендацию ИИ-советника." />
        <Empty
          title="Сравнивать пока некого"
          text="Создайте первую потребность (описание вакансии) — платформа подберёт кандидатов по подтверждённым навыкам и откроет таблицу сравнения топ-3 рядом."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link to="/employer/needs" className="btn-primary">Создать потребность</Link>
              <Link to="/employer/search" className="btn-ghost">Поиск по базе кандидатов</Link>
            </div>
          }
        />
      </div>
    );
  }
  return (
    <div className="max-w-3xl space-y-5">
      <PageTitle title="Сравнение кандидатов" subtitle="Сопоставьте 2–3 кандидатов рядом по требованиям вашей потребности и получите рекомендацию ИИ-советника." />
      <Loading />
    </div>
  );
}
