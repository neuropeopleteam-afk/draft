// ATS работодателя: Хантфлоу (API v2), Talantix (GraphQL, OAuth-токены), «Поток» (REST v3) и универсальный вебхук.
// У каждой системы — режим «Демо» (заглушка повторяет её API) или «Реальный» (токены владельца аккаунта),
// «Проверить подключение», выбор вакансии и этапа из ATS. Журнал передач со статусами, шагами и «Повторить».
import { useEffect, useState } from "react";
import { PageTitle } from "../components/CabinetLayout";
import { Alert, Empty, Field, Loading, Seg, Toggle, dtt, errText, useApi } from "../components/ui";
import { api, apiDownload } from "../lib/api";

interface Settings {
  auto_push: boolean;
  huntflow: { enabled: boolean; base_url: string; account_id: number | null; vacancy_id: number | null; status_id: number | null; token_set: boolean; token_masked: string | null };
  webhook: { enabled: boolean; url: string | null; secret_set: boolean; secret_masked: string | null; signature_header: string };
  stub: { connected: boolean; huntflow_base_url: string; webhook_url: string | null };
}
interface Provider {
  code: "huntflow" | "talantix" | "potok"; title: string; docs_url: string; enabled: boolean; mode: "demo" | "real";
  base_url: string; real_base_url: string; custom_base_url?: string | null; token_set: boolean; token_masked: string | null;
  refresh_set?: boolean; token_expires_at?: string | null; refresh_expires_at?: string | null; token_refreshed_at?: string | null;
  vacancy_id: number | null; vacancy_title: string | null; stage_id: number | null; stage_title: string | null;
  vacancy_map: Record<string, { id: number; title?: string | null; stage_id?: number | null; stage_title?: string | null }>;
  last_check_at: string | null; last_check_ok: boolean | null; last_check_info: { details?: string[]; error?: string };
  candidates_linked: number; account_id?: number | null;
}
interface AtsVacancy { id: number; title: string | null; status: string; department?: string | null }
interface Stage { id: number; title: string | null }
type Tab = "huntflow" | "talantix" | "potok" | "webhook";
type Msg = { k: "ok" | "error" | "info"; t: string } | null;

const TITLES: Record<string, string> = { huntflow: "Хантфлоу", talantix: "Talantix", potok: "Поток", webhook: "Вебхук" };
const NEEDS: Record<Tab, string[]> = {
  talantix: ["Тариф Talantix «Оптимальный» — на других тарифах API недоступно.",
    "Пользователь с ролью «Администратор» и рабочим местом: токены выпускает администратор, без рабочего места кандидатов создать нельзя.",
    "Личный кабинет Talantix → токены API: ссылка на JSON с парой access/refresh живёт 30 дней или до первого обновления. Вставьте JSON целиком — дальше токены обновляются сами.",
    "Одна пара токенов — на одну среду: refresh одноразовый, две системы с одной парой выбьют друг друга."],
  potok: ["Настройки компании в «Потоке» → «Генерация токенов» (доступ — по ролям «Потока»).",
    "В «Источники кандидатов» добавьте источник с адресом сайта платформы — кандидаты придут с ним, а не в «Другие».",
    "API «Потока» ограничивает частоту запросов; одна передача — 1–3 запроса."],
  huntflow: ["Хантфлоу → Настройки → API: токен доступа.", "ID организации (account_id) — покажет «Проверить подключение».",
    "Вакансию и этап можно выбрать из списка после проверки."],
  webhook: ["Любая система, принимающая POST JSON. Подпись HMAC-SHA256 — по секрету, проверка описана в docs/ATS.md."],
};
const KIND: Record<string, string> = {
  huntflow_applicant: "кандидат создан", huntflow_vacancy: "на вакансии", webhook: "вебхук",
  talantix_person: "createPerson — кандидат создан", talantix_response: "createResponses — отклик на вакансию",
  talantix_comment: "createPersonComment — комментарий", talantix_transfer: "переведён на этап",
  potok_applicant: "applicants.json — кандидат создан", potok_join: "ajs_joins — на вакансии", potok_stage: "change_stage — этап",
  potok_event: "events.json — комментарий",
};

function recordLine(r: any): string {
  const p = r.payload ?? {};
  switch (r.kind) {
    case "huntflow_applicant": return [`${p.last_name ?? ""} ${p.first_name ?? ""}`.trim(), p.email, p.phone, p.money].filter(Boolean).join(" · ");
    case "huntflow_vacancy": return `вакансия ${p.vacancy}, этап «${p.status_name}»`;
    case "webhook": return `${p.event ?? ""}${r.signature_valid ? " · подпись верна" : " · подпись НЕ верна"}`;
    case "talantix_person": return [`${p.lastName ?? ""} ${p.firstName ?? ""}`.trim(), (p.contacts ?? []).map((c: any) => `${c.type}: ${c.value}`).join(", "),
      p.vacancyIds?.length ? `вакансия ${p.vacancyIds.join(", ")}` : "", p.structuredResume?.title].filter(Boolean).join(" · ");
    case "talantix_response": return `кандидат ${p.personIds?.join(", ")} → ${(p.vacancyTitles ?? p.vacancyIds ?? []).join(", ")}`;
    case "talantix_transfer": return `этап «${p.statusName}»`;
    case "talantix_comment": case "potok_event": return String(p.text ?? p.body ?? "").split("\n")[0];
    case "potok_applicant": return [`${p.last_name ?? ""} ${p.first_name ?? ""}`.trim(), ...(p.emails ?? []), ...(p.phones ?? []),
      (p.ajs_joins ?? []).map((j: any) => `«${j.job_name}», этап «${j.stage}»`).join(", ")].filter(Boolean).join(" · ");
    case "potok_join": return `«${p.job_name}», этап «${p.stage_name}»`;
    case "potok_stage": return `«${p.job_name}» → «${p.stage_name}»`;
    default: return "";
  }
}

function resultLine(d: any): string {
  const r = d.result ?? {};
  if (d.status !== "ok") return d.error ?? "";
  if (d.target === "webhook") return `HTTP ${d.http_status}`;
  const parts = [r.external_id ? `id в ATS ${r.external_id}` : "", r.vacancy_id ? `вакансия ${r.vacancy_title ?? r.vacancy_id}` : "",
    r.status_id ? `этап ${r.status_id}` : "", r.dedup ? "без дубликата" : "", r.token_refreshed ? "токен обновлён автоматически" : ""];
  return parts.filter(Boolean).join(" · ");
}

export function EmployerAts() {
  const s = useApi<Settings>("/employer/ats/settings");
  const prov = useApi<Provider[]>("/employer/ats/providers");
  const deliveries = useApi<any[]>("/employer/ats/deliveries");
  const records = useApi<any[]>("/employer/ats/stub/records");
  const [tab, setTab] = useState<Tab>("talantix");
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);

  const reloadAll = () => { void s.reload(); void prov.reload(); void deliveries.reload(); void records.reload(); };
  async function connectAll() {
    setMsg(null); setBusy(true);
    try {
      await api("/employer/ats/demo/connect-all", { method: "POST" }); reloadAll();
      setMsg({ k: "ok", t: "Подключены демо-ATS: Хантфлоу, Talantix, «Поток» и вебхук. Примите приглашение кандидатом — карточка уйдёт во все системы, записи появятся в журнале и во входящих тестовой ATS." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); } finally { setBusy(false); }
  }
  async function retry(id: string) {
    setMsg(null);
    try {
      const r = await api<any[]>(`/employer/ats/deliveries/${id}/retry`, { method: "POST" });
      setMsg(r[0]?.status === "ok" ? { k: "ok", t: `${r[0].target_title}: передано повторно, дубликат не создан.` } : { k: "error", t: r[0]?.error ?? "Не удалось" });
      void deliveries.reload(); void records.reload();
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }

  if (s.loading || prov.loading || !s.data || !prov.data) return <Loading />;
  const byCode = Object.fromEntries(prov.data.map((p) => [p.code, p])) as Record<string, Provider>;
  const on = (t: Tab) => (t === "webhook" ? s.data!.webhook.enabled : byCode[t]?.enabled);
  const anyDemo = prov.data.some((p) => p.mode === "demo" && p.enabled) || s.data.stub.connected;
  return (
    <div className="max-w-5xl space-y-6">
      <PageTitle title="Интеграция с ATS" subtitle="Когда кандидат принимает приглашение, его верифицированный профиль с контактами уходит в вашу ATS: категория и грейд, подтверждённые навыки T1/T2, паспорт ФСП, вилка оффера и ссылка на PDF. До принятия контакты закрыты — и в ATS тоже." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <section className="card flex flex-wrap items-center justify-between gap-4 border-brand-lavender/30 bg-[#FBFAFF]">
        <div className="max-w-xl">
          <p className="font-bold text-brand-night">Демо без своих аккаунтов</p>
          <p className="text-sm text-brand-ink/65">Заглушки на нашем сервере повторяют API Talantix (GraphQL, OAuth-токены с автообновлением), «Потока» (REST v3) и Хантфлоу (API v2) и принимают вебхук с проверкой подписи. Платформа ходит к ним по настоящему HTTP тем же кодом, что и к реальным системам.</p>
        </div>
        <button className="btn-primary" disabled={busy} onClick={connectAll}>{busy ? "Подключаем…" : anyDemo ? "Переподключить все демо-ATS" : "Подключить все демо-ATS"}</button>
      </section>

      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Seg label="ATS" value={tab} onChange={setTab} options={(["talantix", "potok", "huntflow", "webhook"] as Tab[]).map((t) => ({ id: t, title: `${TITLES[t]}${on(t) ? " · вкл." : ""}` }))} />
          {tab !== "webhook" && <a className="text-sm font-semibold text-brand-plum hover:text-brand" href={byCode[tab]?.docs_url} target="_blank" rel="noreferrer">Документация API {TITLES[tab]}</a>}
        </div>
        {tab === "talantix" || tab === "potok"
          ? <ConnectionPanel key={tab} p={byCode[tab]} onSaved={(np) => { prov.setData(prov.data!.map((x) => (x.code === np.code ? np : x))); void records.reload(); }} setMsg={setMsg} />
          : <SettingsPanel key={tab} tab={tab} s={s.data} hf={byCode.huntflow} onSaved={(ns) => { s.setData(ns); void prov.reload(); }} setMsg={setMsg} />}
        <details className="rounded-xl bg-brand-blush/25 px-4 py-3 text-sm">
          <summary className="cursor-pointer font-semibold text-brand-night">Что нужно для реального подключения</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-brand-ink/75">{NEEDS[tab].map((x) => <li key={x}>{x}</li>)}</ul>
        </details>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between"><h2 className="font-bold text-brand-night">Журнал передач</h2><button className="text-sm font-semibold text-brand-plum hover:text-brand" onClick={() => { void deliveries.reload(); void records.reload(); }}>Обновить</button></div>
        {!deliveries.data?.length ? <Empty title="Передач пока не было" text="Появятся, когда кандидат примет приглашение или вы нажмёте «В ATS» у принятого приглашения или отклика." /> : (
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#FBF8FC] text-xs uppercase tracking-wider text-brand-ink/50"><tr><th className="px-4 py-2">Когда</th><th>Кандидат</th><th>Куда</th><th>Итог</th><th>Подробности</th><th className="pr-4" /></tr></thead>
              <tbody className="divide-y divide-brand-night/5">
                {deliveries.data.map((d) => (
                  <tr key={d.id} className="align-top">
                    <td className="whitespace-nowrap px-4 py-2">{dtt(d.created_at)}<div className="text-xs text-brand-ink/45">{d.trigger === "manual" ? "вручную" : d.trigger === "retry" ? "повтор" : "автоматически"}</div></td>
                    <td className="py-2 pr-3">{d.candidate_ref}<div className="text-xs text-brand-ink/50">{d.position_title}</div></td>
                    <td className="py-2 pr-3 font-medium">{d.target_title ?? TITLES[d.target]}</td>
                    <td className="whitespace-nowrap py-2 pr-3"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${d.status === "ok" ? "bg-emerald-50 text-emerald-700" : d.status === "pending" ? "bg-[#F3F2FB] text-brand-ink/60" : "bg-brand-blush text-brand-plum"}`}>{d.status === "ok" ? (d.already_sent ? "уже передано" : "передано") : d.status === "pending" ? "в работе" : "ошибка"}</span> <span className="text-xs text-brand-ink/45" title="Попыток">×{d.attempts}</span></td>
                    <td className="py-2 pr-3 text-xs text-brand-ink/65">{resultLine(d)}
                      {d.result?.steps?.length > 0 && <details className="mt-1"><summary className="cursor-pointer font-semibold text-brand-plum">Шаги</summary><ol className="mt-1 list-decimal space-y-0.5 pl-4">{d.result.steps.map((x: string, i: number) => <li key={i}>{x}</li>)}</ol></details>}
                    </td>
                    <td className="py-2 pr-4">{d.status === "error" && <button className="btn-ghost px-3 py-1 text-xs" onClick={() => retry(d.id)}>Повторить</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {anyDemo && (
        <section className="space-y-3">
          <h2 className="font-bold text-brand-night">Тестовая ATS: что пришло</h2>
          {!records.data?.length ? <Empty title="Пока пусто" text="Отправьте приглашение демо-кандидату и примите его — записи появятся здесь." /> : (
            <ul className="space-y-2">
              {records.data.map((r) => (
                <li key={r.id} className="card text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-brand-night"><span className="mr-2 rounded-full bg-[#F3F2FB] px-2 py-0.5 text-xs font-semibold text-brand-plum">{r.system}</span>{KIND[r.kind] ?? r.kind}{r.external_id ? ` · #${r.external_id}` : ""}</p>
                    <span className="text-xs text-brand-ink/50">{dtt(r.created_at)}</span>
                  </div>
                  <p className="mt-1 text-brand-ink/70">{recordLine(r)}</p>
                  <details className="mt-2"><summary className="cursor-pointer text-xs font-semibold text-brand-plum">JSON</summary><pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-brand-ink p-3 text-[11px] leading-relaxed text-white/90">{JSON.stringify(r.payload, null, 2)}</pre></details>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function CheckResult({ res }: { res: any }) {
  if (!res) return null;
  if (res.error) return <Alert kind="error">{res.error}</Alert>;
  return <Alert kind="ok">Подключение работает. {(res.details ?? []).join(". ")}{res.token_refreshed ? ". Access-токен обновлён по refresh-токену и сохранён." : ""}</Alert>;
}

function VacancyPicker({ code, value, stage, onChange }: { code: string; value: { id: number | null; title: string | null }; stage: { id: number | null; title: string | null };
  onChange: (v: { id: number | null; title: string | null }, s: { id: number | null; title: string | null }) => void }) {
  const [list, setList] = useState<AtsVacancy[] | null>(null);
  const [stages, setStages] = useState<Stage[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function load() {
    setErr(null);
    try { setList(await api<AtsVacancy[]>(`/employer/ats/providers/${code}/vacancies`)); } catch (e) { setErr(errText(e)); }
  }
  // выбранная вакансия есть — сразу подтягиваем список, чтобы было видно название и этапы
  useEffect(() => { if (value.id && !list) void load(); }, [code]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!value.id || !list) { setStages(null); return; }
    api<Stage[]>(`/employer/ats/providers/${code}/vacancies/${value.id}/stages`).then(setStages).catch(() => setStages([]));
  }, [code, value.id, list]);
  return (
    <div className="grid gap-4 sm:col-span-2 sm:grid-cols-2">
      <Field label="Вакансия в ATS" htmlFor={`${code}-v`} hint={value.id ? `Выбрана: ${value.title ?? ""} (id ${value.id})` : "Пусто — кандидат попадёт только в базу"}>
        {list ? (
          <select id={`${code}-v`} className="input" value={value.id ?? ""} onChange={(e) => { const v = list.find((x) => x.id === Number(e.target.value)); onChange({ id: v?.id ?? null, title: v?.title ?? null }, { id: null, title: null }); }}>
            <option value="">— без вакансии —</option>
            {list.map((v) => <option key={v.id} value={v.id} disabled={v.status === "archive"}>{v.title}{v.department ? ` · ${v.department}` : ""}{v.status === "archive" ? " (архив)" : ""}</option>)}
          </select>
        ) : <button type="button" className="btn-ghost w-full" onClick={load}>Загрузить вакансии из ATS</button>}
      </Field>
      <Field label="Этап (необязательно)" htmlFor={`${code}-s`} hint="Пусто — первый этап воронки">
        <select id={`${code}-s`} className="input" disabled={!stages?.length} value={stage.id ?? ""} onChange={(e) => { const st = stages?.find((x) => x.id === Number(e.target.value)); onChange(value, { id: st?.id ?? null, title: st?.title ?? null }); }}>
          <option value="">— первый этап —</option>
          {(stages ?? []).map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
        </select>
      </Field>
      {err && <div className="sm:col-span-2"><Alert>{err}</Alert></div>}
    </div>
  );
}

function ConnectionPanel({ p, onSaved, setMsg }: { p: Provider; onSaved: (p: Provider) => void; setMsg: (m: Msg) => void }) {
  const [f, setF] = useState({ enabled: p.enabled, mode: p.mode, token: "", refresh_token: "", base_url: p.custom_base_url ?? "",
    vacancy: { id: p.vacancy_id, title: p.vacancy_title }, stage: { id: p.stage_id, title: p.stage_title } });
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const tx = p.code === "talantix";
  async function save(over: Partial<typeof f> = {}) {
    const x = { ...f, ...over };
    setMsg(null); setBusy(true);
    try {
      const np = await api<Provider>(`/employer/ats/providers/${p.code}`, { method: "PUT", body: {
        enabled: x.enabled, mode: x.mode, base_url: x.base_url || null, token: x.token || null, refresh_token: x.refresh_token || null,
        vacancy_id: x.vacancy.id, vacancy_title: x.vacancy.title, stage_id: x.stage.id, stage_title: x.stage.title, vacancy_map: p.vacancy_map } });
      onSaved(np);
      setF({ ...x, token: "", refresh_token: "", vacancy: { id: np.vacancy_id, title: np.vacancy_title }, stage: { id: np.stage_id, title: np.stage_title } });
      setMsg({ k: "ok", t: `${p.title}: настройки сохранены. Токены хранятся зашифрованными и не показываются.` });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); } finally { setBusy(false); }
  }
  async function check() {
    setRes(null); setBusy(true);
    try { setRes(await api(`/employer/ats/providers/${p.code}/check`, { method: "POST" })); } catch (e) { setRes({ error: errText(e) }); } finally { setBusy(false); }
  }
  async function demo() {
    setMsg(null); setBusy(true);
    try { const np = await api<Provider>(`/employer/ats/providers/${p.code}/demo`, { method: "POST" }); onSaved(np); setF({ ...f, enabled: true, mode: "demo", vacancy: { id: np.vacancy_id, title: np.vacancy_title }, stage: { id: null, title: null } }); setMsg({ k: "ok", t: `${p.title}: демо-режим включён, вакансия «${np.vacancy_title}».` }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm text-brand-ink/70">
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${p.enabled ? "bg-emerald-50 text-emerald-700" : "bg-[#F3F2FB] text-brand-ink/60"}`}>{p.enabled ? "подключено" : "выключено"}</span>
        <span>{p.mode === "demo" ? "демо-заглушка" : "реальный API"}: <code className="text-xs">{p.base_url}</code></span>
        {p.token_set && <span>токен {p.token_masked}{tx && p.refresh_set ? " + refresh" : ""}</span>}
        {tx && p.token_expires_at && <span>access до {dtt(p.token_expires_at)}{p.token_refreshed_at ? `, обновлён ${dtt(p.token_refreshed_at)}` : ""}</span>}
        {tx && p.refresh_expires_at && <span>refresh до {dtt(p.refresh_expires_at)}</span>}
        {p.candidates_linked > 0 && <span>кандидатов связано: {p.candidates_linked}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <Seg label="Режим" value={f.mode} onChange={(m) => setF({ ...f, mode: m })} options={[{ id: "demo", title: "Демо" }, { id: "real", title: "Реальный" }]} />
        <div className="min-w-[16rem] flex-1"><Toggle checked={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} label={`Передавать в ${p.title}`} hint={tx ? "Кандидат, резюме TMS, отклик на вакансию, этап и комментарий" : "Кандидат с резюме на вакансии, этап и комментарий"} /></div>
      </div>
      {f.mode === "demo" ? (
        <p className="text-sm text-brand-ink/65">Демо-{p.title} на нашем сервере: {tx ? "GraphQL с теми же типами, OAuth-токены (access живёт 15 минут и обновляется сам)" : "REST v3 с теми же методами и ответами"}. {p.mode !== "demo" && "После переключения нажмите «Включить демо»."}</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {tx ? (<>
            <Field label="Токены Talantix (JSON со ссылки или access-токен)" htmlFor="tx-t" hint={p.token_set && p.mode === "real" ? `Сохранён: ${p.token_masked}. Пусто — не менять.` : "Вставьте JSON целиком: access_token, refresh_token, expires_in, created_at"}>
              <textarea id="tx-t" className="input min-h-[5.5rem] font-mono text-xs" autoComplete="off" spellCheck={false} value={f.token} onChange={(e) => setF({ ...f, token: e.target.value })} />
            </Field>
            <Field label="Refresh-токен (если вставили только access)" htmlFor="tx-r" hint="Без него токен не обновится через сутки">
              <input id="tx-r" type="password" autoComplete="off" className="input" value={f.refresh_token} onChange={(e) => setF({ ...f, refresh_token: e.target.value })} />
            </Field>
          </>) : (
            <Field label="Токен «Потока»" htmlFor="pt-t" hint={p.token_set && p.mode === "real" ? `Сохранён: ${p.token_masked}. Пусто — не менять.` : "Настройки компании → «Генерация токенов»"}>
              <input id="pt-t" type="password" autoComplete="off" className="input" value={f.token} onChange={(e) => setF({ ...f, token: e.target.value })} />
            </Field>
          )}
          <Field label="Адрес API" htmlFor={`${p.code}-b`} hint={`Пусто — ${p.real_base_url}`}><input id={`${p.code}-b`} className="input" value={f.base_url} placeholder={p.real_base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} /></Field>
        </div>
      )}
      {p.token_set && f.mode === p.mode && (
        <div className="grid gap-4 sm:grid-cols-2">
          <VacancyPicker code={p.code} value={f.vacancy} stage={f.stage} onChange={(v, st) => setF({ ...f, vacancy: v, stage: st })} />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {f.mode === "demo" && p.mode !== "demo" ? <button className="btn-primary" disabled={busy} onClick={demo}>Включить демо</button>
          : <button className="btn-primary" disabled={busy} onClick={() => save()}>Сохранить</button>}
        {f.mode === "demo" && p.mode === "demo" && <button className="btn-ghost" disabled={busy} onClick={demo}>Выпустить новые демо-токены</button>}
        <button className="btn-ghost" disabled={busy || !p.token_set || f.mode !== p.mode} onClick={check}>Проверить подключение</button>
      </div>
      <CheckResult res={res} />
      {!res && p.last_check_at && <p className="text-xs text-brand-ink/55">Последняя проверка {dtt(p.last_check_at)}: {p.last_check_ok ? "успешно" : `ошибка — ${p.last_check_info?.error ?? ""}`}</p>}
    </div>
  );
}

function SettingsPanel({ tab, s, hf, onSaved, setMsg }: { tab: "huntflow" | "webhook"; s: Settings; hf: Provider; onSaved: (s: Settings) => void; setMsg: (m: Msg) => void }) {
  const [f, setF] = useState<any>({ auto_push: s.auto_push, huntflow: { ...s.huntflow, token: "" }, webhook: { ...s.webhook, secret: "" } });
  const [res, setRes] = useState<any>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const set = (grp: "huntflow" | "webhook", k: string, v: any) => setF({ ...f, [grp]: { ...f[grp], [k]: v } });
  async function save() {
    setMsg(null);
    const h = f.huntflow, w = f.webhook;
    const body = { auto_push: f.auto_push,
      huntflow: { enabled: h.enabled, base_url: h.base_url || null, account_id: h.account_id ? Number(h.account_id) : null, vacancy_id: h.vacancy_id ? Number(h.vacancy_id) : null, status_id: h.status_id ? Number(h.status_id) : null, token: h.token || null },
      webhook: { enabled: w.enabled, url: w.url || null, secret: w.secret || null } };
    try { const ns = await api<Settings>("/employer/ats/settings", { method: "PUT", body }); onSaved(ns); setF({ ...f, huntflow: { ...ns.huntflow, token: "" }, webhook: { ...ns.webhook, secret: "" } }); setMsg({ k: "ok", t: "Настройки ATS сохранены. Токены хранятся зашифрованными и не показываются." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function check() {
    setRes(null);
    try { setRes(await api("/employer/ats/providers/huntflow/check", { method: "POST" })); } catch (e) { setRes({ error: errText(e) }); }
  }
  return (
    <div className="space-y-4">
      <Toggle checked={f.auto_push} onChange={(v) => setF({ ...f, auto_push: v })} label="Передавать автоматически при принятии приглашения и при «Пригласить» по отклику" hint="Вручную — кнопкой «В ATS» в приглашениях и откликах. Настройка общая для всех ATS." />
      {tab === "huntflow" ? (
        <div className="border-t border-brand-night/5 pt-4">
          <Toggle checked={f.huntflow.enabled} onChange={(v) => set("huntflow", "enabled", v)} label="Хантфлоу (публичный API v2)" hint={hf?.mode === "demo" ? "Сейчас — демо-заглушка Хантфлоу на нашем сервере" : "Кандидат создаётся в базе и закрепляется на вакансии на первом этапе (или указанном)"} />
          {f.huntflow.enabled && (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Field label="Адрес API" htmlFor="hb" hint="https://api.huntflow.ru/v2 — облако; для коробки — свой адрес"><input id="hb" className="input" value={f.huntflow.base_url ?? ""} onChange={(e) => set("huntflow", "base_url", e.target.value)} /></Field>
              <Field label="Токен доступа" htmlFor="ht" hint={f.huntflow.token_set ? `Сохранён: ${f.huntflow.token_masked}. Оставьте пустым, чтобы не менять.` : "Настройки Хантфлоу → API → токен"}><input id="ht" type="password" autoComplete="off" className="input" value={f.huntflow.token} onChange={(e) => set("huntflow", "token", e.target.value)} /></Field>
              <Field label="ID организации (account_id)" htmlFor="ha"><input id="ha" type="number" className="input" value={f.huntflow.account_id ?? ""} onChange={(e) => set("huntflow", "account_id", e.target.value)} /></Field>
              <Field label="ID вакансии" htmlFor="hv" hint="Пусто — только добавить в базу кандидатов"><input id="hv" type="number" className="input" value={f.huntflow.vacancy_id ?? ""} onChange={(e) => set("huntflow", "vacancy_id", e.target.value)} /></Field>
              <Field label="ID этапа (необязательно)" htmlFor="hs" hint="Пусто — первый этап подбора"><input id="hs" type="number" className="input" value={f.huntflow.status_id ?? ""} onChange={(e) => set("huntflow", "status_id", e.target.value)} /></Field>
            </div>
          )}
        </div>
      ) : (
        <div className="border-t border-brand-night/5 pt-4">
          <Toggle checked={f.webhook.enabled} onChange={(v) => set("webhook", "enabled", v)} label="Универсальный вебхук" hint="POST JSON (схема vstrechny.candidate.v1) с подписью HMAC-SHA256 — для любой ATS или своей системы" />
          {f.webhook.enabled && (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Field label="URL (https)" htmlFor="wu"><input id="wu" className="input" value={f.webhook.url ?? ""} onChange={(e) => set("webhook", "url", e.target.value)} placeholder="https://ats.example.ru/hooks/vstrechny" /></Field>
              <Field label="Секрет подписи" htmlFor="ws" hint={f.webhook.secret_set ? `Сохранён: ${f.webhook.secret_masked}` : "Пусто — сгенерируем"}><input id="ws" type="password" autoComplete="off" className="input" value={f.webhook.secret} onChange={(e) => set("webhook", "secret", e.target.value)} /></Field>
              <p className="text-xs text-brand-ink/55 sm:col-span-2">Заголовок <code>{s.webhook.signature_header}</code>. Проверка на стороне получателя — в docs/ATS.md.{" "}
                {f.webhook.secret_set && <button className="font-semibold text-brand hover:underline" onClick={async () => setSecret((await api<any>("/employer/ats/webhook-secret")).secret)}>Показать секрет</button>}
                {secret && <code className="ml-2 break-all rounded bg-[#F3F2FB] px-1.5 py-0.5">{secret}</code>}</p>
            </div>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" onClick={save}>Сохранить</button>
        {tab === "huntflow" && <button className="btn-ghost" onClick={check} disabled={!f.huntflow.token_set}>Проверить подключение</button>}
      </div>
      {tab === "huntflow" && res && (res.error ? <Alert kind="error">{res.error}</Alert>
        : <Alert kind="ok">Подключение работает: {res.me?.name}. Организации: {(res.accounts ?? []).map((a: any) => `${a.name} (id ${a.id})`).join(", ")}. Этапы: {(res.statuses ?? []).map((x: any) => `${x.name} (${x.id})`).join(", ") || "—"}.</Alert>)}
    </div>
  );
}

const pushText = (r: any[]) => r.map((d) => `${d.target_title ?? TITLES[d.target] ?? d.target}: ${d.already_sent ? "уже передано ранее" : d.status === "ok" ? (d.result?.dedup ? "обновлено, без дубликата" : "передано") : d.error}`).join("; ");

/** Кнопки у принятого приглашения (страница «Приглашения» работодателя). */
export function AtsInvitationActions({ invitationId, status, candidateRef }: { invitationId: string; status: string; candidateRef?: string }) {
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (status !== "accepted") return null;
  async function push() {
    setMsg(null); setBusy(true);
    try { const r = await api<any[]>("/employer/ats/push", { body: { invitation_id: invitationId } }); setMsg({ k: r.every((d) => d.status === "ok") ? "ok" : "error", t: pushText(r) || "Нет подключённых ATS" }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button className="btn-ghost" disabled={busy} onClick={push}>{busy ? "Передаём…" : "В ATS"}</button>
        <button className="btn-ghost" onClick={() => apiDownload(`/employer/invitations/${invitationId}/export.json`, `candidate-${candidateRef ?? invitationId}.json`)}>Экспорт JSON</button>
      </div>
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
    </div>
  );
}

export { pushText as atsPushText };
