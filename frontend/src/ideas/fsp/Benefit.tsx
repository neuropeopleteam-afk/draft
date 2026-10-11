// Я29: Кабинет ФСП — «Польза для ФСП» (приглашения и наймы участников ФСП по регионам и направлениям, вклад партнёров,
// доля приглашений с ФСП-бонусом; только агрегаты, группы меньше 5 скрыты) и «Партнёры ФСП» (метка из спонсорского
// пакета). Данные — backend/app/fsp_cabinet/benefit.py и backend/app/modules/tariffs; за флагом TARIFFS_ENABLED.
import { useState } from "react";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Field, Loading, Seg, Stat, dateOnly, errText, useApi } from "../../components/ui";
import { api, apiDownload } from "../../lib/api";
import { usePageTitle } from "../../lib/meta";
import { BarList, fk, fpct } from "../charts";
import { PartnerBadge, useTariffsOn } from "../../pages/employer/Tariffs";

const PERIODS = [{ id: "all", title: "Всё время" }, { id: "180", title: "180 дней" }, { id: "90", title: "90 дней" }, { id: "30", title: "30 дней" }];
const KEY = "fsp_cabinet_days";  // тот же период, что и у остальных разделов кабинета
const q = (days: string) => (days === "all" ? "" : `?days=${days}`);

function Off({ title }: { title: string }) {
  return <div className="max-w-3xl space-y-4"><PageTitle title={title} /><Alert kind="info">Раздел включается вместе с тарифами (TARIFFS_ENABLED) — на этом сервере выключен.</Alert></div>;
}

function GroupTable({ caption, rows }: { caption: string; rows: any[] }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-brand-night/10 bg-white">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.08em] text-brand-night">
          <tr>
            <th scope="col" className="px-3 py-2.5">Группа</th>
            <th scope="col" className="px-3 py-2.5 text-right">Участников ФСП</th>
            <th scope="col" className="px-3 py-2.5 text-right">Приглашены</th>
            <th scope="col" className="px-3 py-2.5 text-right">Доля приглашённых</th>
            <th scope="col" className="px-3 py-2.5 text-right">Приняли</th>
            <th scope="col" className="px-3 py-2.5 text-right">Наняты</th>
            <th scope="col" className="px-3 py-2.5 text-right">Доля ФСП среди приглашённых</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-brand-night/10">
              <th scope="row" className="px-3 py-2 font-semibold text-brand-night">{r.title}{r.secondary_suppressed && <span className="ml-1 text-xs font-normal text-brand-ink/65">(скрыто, чтобы не вычислить малую группу)</span>}</th>
              <td className="px-3 py-2 text-right">{fk(r.candidates_fsp)}</td>
              <td className="px-3 py-2 text-right">{fk(r.invited_fsp)}</td>
              <td className="px-3 py-2 text-right">{fpct(r.invite_rate_fsp)}</td>
              <td className="px-3 py-2 text-right">{fk(r.accepted_fsp)}</td>
              <td className="px-3 py-2 text-right">{fk(r.hired_fsp)}</td>
              <td className="px-3 py-2 text-right">{fpct(r.fsp_invite_share)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FspBenefit() {
  usePageTitle("Польза для ФСП");
  const on = useTariffsOn();
  const [days, setDaysS] = useState(() => localStorage.getItem(KEY) ?? "all");
  const setDays = (d: string) => { localStorage.setItem(KEY, d); setDaysS(d); };
  const { data: rep, loading, error } = useApi<any>(on ? `/fsp-cabinet/benefit${q(days)}` : null, [on, days]);
  const [err, setErr] = useState<string | null>(null);
  if (!on) return <Off title="Польза для ФСП" />;
  async function csv() {
    setErr(null);
    try { await apiDownload(`/fsp-cabinet/benefit/export.csv${q(days)}`, "fsp_benefit.csv"); } catch (e) { setErr(errText(e)); }
  }
  const t = rep?.total;
  const pt = rep?.partners_total;
  return (
    <div className="max-w-6xl space-y-6">
      <PageTitle title="Польза для ФСП" subtitle="Что платформа даёт участникам соревнований ФСП: приглашения и наймы по регионам и направлениям, вклад партнёров федерации." />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="hidden sm:inline-flex"><Seg label="Период" value={days} onChange={setDays} options={PERIODS} /></span>
        <label className="flex items-center gap-2 text-sm sm:hidden">
          <span className="font-semibold text-brand-night">Период</span>
          <select className="input w-auto py-2" value={days} onChange={(e) => setDays(e.target.value)}>
            {PERIODS.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        </label>
        <span className="text-xs text-brand-ink/65" aria-live="polite">{loading ? "Обновляем…" : rep ? `Только агрегаты · группы меньше ${rep.k} человек скрыты` : ""}</span>
        <button className="btn-ghost px-3 py-1.5 text-xs sm:ml-auto" onClick={csv}>CSV: польза для ФСП</button>
      </div>
      {err && <Alert>{err}</Alert>}
      {error && !rep ? <Alert>{error}</Alert> : loading && !rep ? <Loading /> : rep && (
        <>
          {rep.demo_share >= 0.99 && <Alert kind="info">Сейчас в данных только демо-компании и демо-кандидаты стенда (модель, не люди): приглашения и наймы сгенерированы по модели поведения. На живых данных раздел считает те же показатели.</Alert>}
          <div className="grid grid-cols-2 gap-3 md:gap-5 lg:grid-cols-4">
            <Stat label="Участников ФСП" value={fk(t.candidates_fsp)} hint="с подтверждённым достижением (T2), с категорией" />
            <Stat label="Приглашены" value={fk(t.invited_fsp)} hint={`участников ФСП · доля ${fpct(t.invite_rate_fsp)}`} />
            <Stat label="Наняты" value={fk(t.hired_fsp)} hint={`участников ФСП · приняли приглашение ${fk(t.accepted_fsp)}`} />
            <Stat label="С ФСП-бонусом" value={fpct(rep.fsp_bonus_share)} hint={`приглашений участникам ФСП: ${rep.invitations_with_fsp_bonus ?? "< 5"} из ${rep.invitations}`} />
          </div>
          <section className="card min-w-0 space-y-4">
            <div>
              <h2 className="text-lg font-bold text-brand-night">По регионам</h2>
              <p className="mt-1 text-sm text-brand-ink/65">Регион — по городу из профиля кандидата. Полоса — приглашённые участники ФСП.</p>
            </div>
            <BarList rows={rep.regions.map((r: any) => ({ key: r.key, label: r.title, value: r.invited_fsp ?? 0, display: fk(r.invited_fsp), muted: r.invited_fsp == null, sub: `наняты ${fk(r.hired_fsp)}` }))} />
            <GroupTable caption="Участники ФСП по регионам" rows={rep.regions} />
          </section>
          <section className="card min-w-0 space-y-4">
            <h2 className="text-lg font-bold text-brand-night">По направлениям</h2>
            <GroupTable caption="Участники ФСП по направлениям" rows={rep.directions} />
          </section>
          <section className="card min-w-0 space-y-4" aria-labelledby="partners-h">
            <div>
              <h2 id="partners-h" className="text-lg font-bold text-brand-night">Вклад партнёров ФСП</h2>
              <p className="mt-1 text-sm text-brand-ink/65">Компании с меткой «Партнёр ФСП»: метка публична, поэтому названия показаны. Связь наблюдательная, не причинная.</p>
            </div>
            <div className="grid grid-cols-2 gap-3 md:gap-5 lg:grid-cols-4">
              <Stat label="Партнёров" value={pt.companies} hint={`приглашений от партнёров: ${pt.invitations} (${fpct(pt.invitations_share)} всех)`} />
              <Stat label="Участникам ФСП" value={pt.invitations_fsp ?? "< 5"} hint="приглашений от партнёров" />
              <Stat label="Доля ФСП у партнёров" value={fpct(pt.fsp_share_of_partner_invitations)} hint={`у остальных компаний — ${fpct(pt.fsp_share_of_other_invitations)}`} />
              <Stat label="Наняты партнёрами" value={fk(pt.hired_fsp)} hint="участников ФСП" />
            </div>
            {!rep.partners.length ? <p className="text-sm text-brand-ink/65">Партнёров пока нет — метку выдаёт раздел «Партнёры ФСП».</p> : (
              <div className="overflow-x-auto rounded-2xl border border-brand-night/10 bg-white">
                <table className="w-full min-w-[40rem] text-left text-sm">
                  <caption className="sr-only">Партнёры ФСП: приглашения и наймы</caption>
                  <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.08em] text-brand-night">
                    <tr><th scope="col" className="px-3 py-2.5">Компания</th><th scope="col" className="px-3 py-2.5 text-right">Потребности</th><th scope="col" className="px-3 py-2.5 text-right">Приглашения</th><th scope="col" className="px-3 py-2.5 text-right">Из них участникам ФСП</th><th scope="col" className="px-3 py-2.5 text-right">Наняты</th></tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {rep.partners.map((p: any) => (
                      <tr key={p.company_id} className="border-t border-brand-night/10">
                        <th scope="row" className="px-3 py-2 font-semibold text-brand-night">{p.name}{p.city ? <span className="font-normal text-brand-ink/65"> · {p.city}</span> : null}</th>
                        <td className="px-3 py-2 text-right">{p.needs}</td>
                        <td className="px-3 py-2 text-right">{p.invitations}</td>
                        <td className="px-3 py-2 text-right">{p.invitations_fsp ?? "< 5"}{p.fsp_invite_share != null && <span className="text-brand-ink/65"> ({fpct(p.fsp_invite_share)})</span>}</td>
                        <td className="px-3 py-2 text-right">{fk(p.hired)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-xs text-brand-ink/65">Тарифы активных компаний: {rep.plans.map((p: any) => `«${p.title}» — ${p.companies}`).join(", ")}.</p>
          </section>
          <section className="card">
            <h2 className="text-lg font-bold text-brand-night">Методика</h2>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-brand-ink/85">
              {rep.methodology.map((m: string, i: number) => <li key={i}>{m}</li>)}
            </ol>
          </section>
        </>
      )}
    </div>
  );
}

function CompanyRow({ c, onChange }: { c: any; onChange: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function act(action: "grant" | "revoke") {
    setBusy(true); setErr(null);
    try { await api(`/fsp-cabinet/partners/${c.company_id}`, { body: { action, note: note.trim() || null } }); onChange(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const nid = `pn-${c.company_id}`;
  return (
    <li className="rounded-xl border border-brand-night/10 p-3 text-sm" data-testid="partner-row">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-brand-night">{c.name}</span>
        <PartnerBadge on={c.fsp_partner} />
        <span className="text-brand-ink/65">{[c.city, c.inn && `ИНН ${c.inn}`, `тариф «${c.plan_title}»`].filter(Boolean).join(" · ")}</span>
      </div>
      {c.fsp_partner && <p className="mt-1 text-brand-ink/75">С {dateOnly(c.partner_since)}{c.partner_note ? ` · ${c.partner_note}` : ""}</p>}
      {!c.fsp_partner && c.requested_at && <p className="mt-1 text-brand-ink/75">Заявка {dateOnly(c.requested_at)}{c.request_note ? `: «${c.request_note}»` : ""}</p>}
      {c.can_manage ? (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          {!c.fsp_partner && <div className="min-w-0 flex-1"><Field label="Основание (договор, пакет)" htmlFor={nid}><input id={nid} className="input" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Спонсорский пакет, договор № …" /></Field></div>}
          {c.fsp_partner
            ? <button className="btn-ghost !py-2" disabled={busy} onClick={() => act("revoke")}>Снять метку</button>
            : <button className="btn-primary !py-2" disabled={busy} onClick={() => act("grant")}>Выдать метку «Партнёр ФСП»</button>}
        </div>
      ) : <p className="mt-1 text-xs text-brand-ink/65">Менять метку этой компании из демо-песочницы нельзя.</p>}
      {err && <div className="mt-2"><Alert>{err}</Alert></div>}
    </li>
  );
}

export function FspPartners() {
  usePageTitle("Партнёры ФСП");
  const on = useTariffsOn();
  const ov = useApi<any>(on ? "/fsp-cabinet/partners" : null, [on]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!on) return <Off title="Партнёры ФСП" />;
  async function search(e?: React.FormEvent) {
    e?.preventDefault(); setErr(null);
    try { setFound(await api<any[]>(`/fsp-cabinet/partners/search?q=${encodeURIComponent(query.trim())}`)); } catch (x) { setErr(errText(x)); }
  }
  const reload = () => { ov.reload(); if (found) void search(); };
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Партнёры ФСП" subtitle="Метка «Партнёр ФСП» входит в спонсорский пакет федерации: расширенный тариф, отборочные задачи компании на соревнованиях ФСП (проводит ФСП), метка в карточке компании и приглашениях." />
      {ov.loading && !ov.data ? <Loading /> : ov.error ? <Alert>{ov.error}</Alert> : ov.data && (
        <>
          <section className="card space-y-3" aria-labelledby="req-h">
            <h2 id="req-h" className="text-lg font-bold text-brand-night">Заявки компаний</h2>
            {!ov.data.requests.length ? <p className="text-sm text-brand-ink/65">Новых заявок нет.</p>
              : <ul className="space-y-2">{ov.data.requests.map((c: any) => <CompanyRow key={c.company_id} c={c} onChange={reload} />)}</ul>}
          </section>
          <section className="card space-y-3" aria-labelledby="par-h">
            <h2 id="par-h" className="text-lg font-bold text-brand-night">Партнёры ({ov.data.partners.length})</h2>
            {!ov.data.partners.length ? <p className="text-sm text-brand-ink/65">Партнёров пока нет.</p>
              : <ul className="space-y-2">{ov.data.partners.map((c: any) => <CompanyRow key={c.company_id} c={c} onChange={reload} />)}</ul>}
          </section>
        </>
      )}
      <section className="card space-y-3" aria-labelledby="find-h">
        <h2 id="find-h" className="text-lg font-bold text-brand-night">Найти компанию</h2>
        <form className="flex flex-wrap items-end gap-2" onSubmit={search}>
          <div className="min-w-0 flex-1"><Field label="Название или ИНН (от 3 символов)" htmlFor="partner-q"><input id="partner-q" className="input" value={query} onChange={(e) => setQuery(e.target.value)} /></Field></div>
          <button className="btn-ghost" type="submit" disabled={query.trim().length < 3}>Найти</button>
        </form>
        {err && <Alert>{err}</Alert>}
        {found && (!found.length ? <p className="text-sm text-brand-ink/65">Ничего не найдено.</p>
          : <ul className="space-y-2">{found.map((c) => <CompanyRow key={c.company_id} c={c} onChange={reload} />)}</ul>)}
      </section>
    </div>
  );
}
