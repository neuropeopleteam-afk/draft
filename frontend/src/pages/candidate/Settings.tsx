import { useEffect, useState } from "react";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Toggle, dt, errText, num, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { FspIdLinkButton } from "../../integrations/FspId";
import { CupPassportEvents } from "../../ideas/cup/Candidate";
import { useAuth } from "../../lib/auth";
import { useMeta } from "../../lib/meta";
import { CameraSettings } from "../../proctor/CameraReport";
import { MutualPrefs } from "../mutual/Candidate";  // интересы для взаимного подбора (Н9)

export function Fsp() {
  const { data, loading, error, reload } = useApi<any>("/me/fsp");
  const [id, setId] = useState("");
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  useEffect(() => { if (data?.fsp_id_claimed) setId(data.fsp_id_claimed); }, [data]);
  async function link() {
    setMsg(null);
    try { const r = await api<any>("/me/fsp/link", { body: { fsp_id: id } }); setMsg({ k: "ok", t: r.message }); await reload(); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  return (
    <div className="max-w-3xl space-y-6">
      <PageTitle title="Паспорт ФСП" subtitle="Достижения в соревнованиях по дисциплинам спортивного программирования (ЕВСК) — подтверждённые реестром факты (T2)." />
      <section className="card space-y-4">
        <div className="flex items-center gap-3"><Level level={data.linked ? "T2" : "none"} /><p className="font-semibold text-brand-night">{data.linked ? "Паспорт связан" : "Паспорт не связан"}</p></div>
        <p className="text-sm text-brand-ink/70">{data.link_source === "keycloak" ? `Паспорт связан через ФСП ID${data.fsp_id_claimed ? ` (${data.fsp_id_claimed})` : ""}: достижения подтверждены реестром (T2).` : data.note}</p>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-xl bg-[#F3F2FB] p-4 text-center text-sm" data-testid="fsp-identity-link">
          <div className="min-w-0"><p className="font-bold text-brand-night">ФСП ID</p><p className="mt-1 break-all text-xs text-brand-ink/70">{data.fsp_id_claimed || "Не указан"}</p></div>
          <span className="text-brand-plum" aria-label="Связь">↔</span>
          <div><p className="font-bold text-brand-night">Ваш профиль</p><p className="mt-1 text-xs text-brand-ink/70">{data.identity_linked ? "Вход подтверждён OIDC" : data.linked ? "Демо-паспорт" : "Ожидает связи"}</p></div>
        </div>
        {data.registry?.demo && <Alert kind="info">Достижения получены из синтетического API реестра. Это демонстрационные данные, не официальный реестр ФСП.</Alert>}
        {data.registry_warning && <Alert kind="info">{data.registry_warning}</Alert>}
        {data.sport_rank && <p className="text-sm">Спортивный разряд: <b>{data.sport_rank}</b></p>}
        <FspIdLinkButton linkedVia={data.link_source} />
        {data.registry_sync_available && <button className="btn-ghost" data-testid="button-fsp-registry-sync" onClick={async () => {
          setMsg(null);
          try { await api("/me/fsp/registry-sync", { body: {} }); await reload(); setMsg({ k: "ok", t: "Достижения обновлены из API реестра." }); }
          catch (e) { setMsg({ k: "error", t: errText(e) }); }
        }}>Обновить достижения из реестра{data.link_source === "demo" ? " (мок)" : ""}</button>}
        {data.link_source !== "keycloak" && <>
        <p className="pt-2 text-xs font-semibold uppercase tracking-[0.12em] text-brand-ink/65">Или укажите ФСП ID вручную — до подтверждения реестром</p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1"><Field label="ФСП ID" htmlFor="fid"><input id="fid" className="input" value={id} onChange={(e) => setId(e.target.value)} placeholder="FSP-123456" /></Field></div>
          <button className="btn-primary" disabled={id.trim().length < 4} onClick={link}>Сохранить</button>
        </div>
        </>}
        {data.fsp_id_claimed && !data.linked && <p className="text-xs text-brand-plum">Указан ФСП ID {data.fsp_id_claimed} — ожидает подтверждения реестром.</p>}
        {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      </section>
      {data.rating && <section className="card space-y-3"><h2 className="font-bold text-brand-night">Сила паспорта ФСП: {num(data.rating.strength, 3)}</h2><p className="text-sm text-brand-ink/70">{data.rating.policy}</p><p className="text-xs text-brand-ink/65">Учтено соревнований: {num(data.rating.competitions, 0)}. В подборке ФСП — бонус с весом 0,10; грейд он не меняет.</p></section>}
      {data.achievements?.length ? (
        <section className="card">
          <h2 className="font-bold text-brand-night">Достижения</h2>
          <ul className="mt-3 space-y-3 text-sm">{data.achievements.map((a: any, i: number) => <li key={i} className="flex items-start gap-2"><Level level="T2" /><div><p>{a.text}</p>{(a.team || a.evsk_code || a.sport_rank) && <p className="mt-1 text-xs text-brand-ink/65">{[a.team ? `Команда: ${a.team}` : null, a.team_result?.place ? `командное место: ${num(a.team_result.place, 0)}` : null, a.evsk_code ? `ЕВСК: ${a.evsk_code}` : null, a.sport_rank ? `разряд: ${a.sport_rank}` : null].filter(Boolean).join(" · ")}</p>}</div></li>)}</ul>
        </section>
      ) : <Empty title="Достижений нет" text="Это нейтральное состояние: на категорию и рейтинг не влияет отрицательно." />}
      <CupPassportEvents />
    </div>
  );
}

const CONSENT_TITLE: Record<string, string> = { processing: "Обработка персональных данных", publication: "Публикация обезличенного профиля" };

export function Settings() {
  const { me, refresh } = useAuth();
  const meta = useMeta();
  const onb = useApi<any>("/me/onboarding");
  const consents = useApi<any[]>("/me/consents");
  const [privacy, setPrivacy] = useState<Record<string, boolean>>({});
  const [salary, setSalary] = useState("");
  const [text, setText] = useState<{ title: string; text: string } | null>(null);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  useEffect(() => {
    if (onb.data) { setPrivacy(onb.data.answers.privacy); setSalary(onb.data.answers.salary_min_hidden?.toString() ?? ""); }
  }, [onb.data]);
  const active = (k: string) => consents.data?.some((c) => c.kind === k && !c.revoked_at);

  async function savePrivacy(next: Record<string, boolean>) {
    setPrivacy(next);
    try { await api("/me/privacy", { method: "PUT", body: { privacy: next } }); } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function saveSalary() {
    try { await api("/me/candidate-profile", { method: "PATCH", body: { salary_min_hidden: salary ? Number(salary) : null } }); setMsg({ k: "ok", t: "Минимум сохранён. Работодатель его не видит." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function consent(kind: string, on: boolean) {
    setMsg(null);
    try {
      await api(`/me/consents/${kind}`, { method: on ? "POST" : "DELETE" });
      await consents.reload(); await refresh();
      setMsg({ k: "ok", t: on ? "Согласие дано: профиль виден работодателям." : "Согласие отозвано: профиль скрыт из подборок и поиска." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function showText(kind: string) { setText(await api(`/legal/consents/${kind}`, { auth: false })); }

  if (onb.loading || consents.loading) return <Loading />;
  return (
    <div className="max-w-3xl space-y-6">
      <PageTitle title="Настройки и приватность" subtitle="Что видит работодатель и какие согласия вы дали." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <section className="card">
        <h2 className="font-bold text-brand-night">Поля обезличенной карточки</h2>
        <p className="mt-1 text-sm text-brand-ink/65">Имя, почта, телефон и сумма минимума зарплаты не показываются никогда. Контакты — только после принятия приглашения. По умолчанию работодатель видит лишь «вилка в ожиданиях / ниже ожиданий» — это выключается ниже, в «Интересах».</p>
        <div className="mt-3 divide-y divide-brand-night/5">
          {onb.data?.options.privacy_fields.map((f: any) => <Toggle key={f.id} label={f.title} checked={privacy[f.id] ?? true} onChange={(v) => savePrivacy({ ...privacy, [f.id]: v })} />)}
        </div>
        <p className="mt-2 text-xs text-brand-ink/65">Профиль {me?.candidate?.visible_to_employers ? "виден" : "не виден"} работодателям.</p>
      </section>
      <section className="card">
        <h2 className="font-bold text-brand-night">Скрытый минимум зарплаты</h2>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div className="min-w-[14rem] flex-1"><Field label="₽ в месяц" htmlFor="smin"><input id="smin" type="number" className="input" value={salary} onChange={(e) => setSalary(e.target.value)} /></Field></div>
          <button className="btn-primary" onClick={saveSalary}>Сохранить</button>
        </div>
      </section>
      <MutualPrefs />
      <section className="card">
        <h2 className="font-bold text-brand-night">Согласия (152-ФЗ)</h2>
        <ul className="mt-3 space-y-3 text-sm">
          {["processing", "publication"].map((k) => {
            const c = consents.data?.find((x) => x.kind === k && !x.revoked_at);
            return (
              <li key={k} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-night/10 p-4">
                <div>
                  <p className="font-semibold">{CONSENT_TITLE[k]}</p>
                  <p className="text-brand-ink/65">{c ? `Дано ${dt(c.granted_at)}, редакция ${/^\d{4}-\d{2}-\d{2}$/.test(c.version) ? dt(c.version) : c.version}` : "Не дано"} · <button className="font-semibold text-brand hover:underline" onClick={() => showText(k)}>текст</button></p>
                </div>
                {k === "publication" && (active(k)
                  ? <button className="btn-ghost" onClick={() => consent(k, false)}>Отозвать</button>
                  : <button className="btn-primary" onClick={() => consent(k, true)}>Дать согласие</button>)}
                {k === "processing" && <span className="text-xs text-brand-ink/65">Отзыв — через обращение к оператору: {meta?.operator?.email}</span>}
              </li>
            );
          })}
        </ul>
        {text && <div className="mt-4 rounded-xl bg-[#F3F2FB] p-4 text-xs leading-relaxed text-brand-ink/80"><p className="mb-2 font-semibold">{text.title}</p><p className="whitespace-pre-line">{text.text}</p></div>}
      </section>
      <CameraSettings />
    </div>
  );
}
