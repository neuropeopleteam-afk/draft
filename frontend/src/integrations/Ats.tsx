// ATS работодателя: Хантфлоу (API v2: токен, id организации и вакансии), вебхук с подписью HMAC, тестовая ATS-заглушка,
// журнал передач и что пришло в заглушку; кнопки «В ATS» / «JSON» у принятых приглашений.
import { useEffect, useState } from "react";
import { PageTitle } from "../components/CabinetLayout";
import { Alert, Empty, Field, Loading, Toggle, dtt, errText, useApi } from "../components/ui";
import { api, apiDownload } from "../lib/api";

interface Settings {
  auto_push: boolean;
  huntflow: { enabled: boolean; base_url: string; account_id: number | null; vacancy_id: number | null; status_id: number | null; token_set: boolean; token_masked: string | null };
  webhook: { enabled: boolean; url: string | null; secret_set: boolean; secret_masked: string | null; signature_header: string };
  stub: { connected: boolean; huntflow_base_url: string; webhook_url: string | null };
}

export function EmployerAts() {
  const s = useApi<Settings>("/employer/ats/settings");
  const deliveries = useApi<any[]>("/employer/ats/deliveries");
  const records = useApi<any[]>("/employer/ats/stub/records");
  const [f, setF] = useState<any>(null);
  const [msg, setMsg] = useState<{ k: "ok" | "error" | "info"; t: string } | null>(null);
  const [check, setCheck] = useState<any>(null);
  const [secret, setSecret] = useState<string | null>(null);
  useEffect(() => { if (s.data) setF({ auto_push: s.data.auto_push, huntflow: { ...s.data.huntflow, token: "" }, webhook: { ...s.data.webhook, secret: "" } }); }, [s.data]);

  async function save() {
    setMsg(null);
    const h = f.huntflow, w = f.webhook;
    const body = { auto_push: f.auto_push,
      huntflow: { enabled: h.enabled, base_url: h.base_url || null, account_id: h.account_id ? Number(h.account_id) : null, vacancy_id: h.vacancy_id ? Number(h.vacancy_id) : null, status_id: h.status_id ? Number(h.status_id) : null, token: h.token || null },
      webhook: { enabled: w.enabled, url: w.url || null, secret: w.secret || null } };
    try { s.setData(await api<Settings>("/employer/ats/settings", { method: "PUT", body })); setMsg({ k: "ok", t: "Настройки ATS сохранены. Токены хранятся зашифрованными и не показываются." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function connectStub() {
    setMsg(null);
    try { s.setData(await api<Settings>("/employer/ats/stub/connect", { method: "POST" })); setMsg({ k: "ok", t: "Подключена тестовая ATS: Хантфлоу-совместимый API и вебхук на нашем сервере. Примите приглашение кандидатом — карточка появится ниже." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function runCheck() {
    setCheck(null); setMsg(null);
    try { setCheck(await api("/employer/ats/huntflow/check", { method: "POST" })); } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  const refresh = () => { void deliveries.reload(); void records.reload(); };

  if (s.loading || !f) return <Loading />;
  const set = (grp: "huntflow" | "webhook", k: string, v: any) => setF({ ...f, [grp]: { ...f[grp], [k]: v } });
  return (
    <div className="max-w-5xl space-y-6">
      <PageTitle title="Интеграция с ATS" subtitle="Когда кандидат принимает приглашение, его карточка с контактами уходит в вашу ATS. До принятия контакты закрыты — и в ATS тоже." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <section className="card flex flex-wrap items-center justify-between gap-4 border-brand-lavender/30 bg-[#FBFAFF]">
        <div className="max-w-xl">
          <p className="font-bold text-brand-night">Тестовая ATS для демо</p>
          <p className="text-sm text-brand-ink/65">Заглушка на нашем сервере повторяет методы Хантфлоу API v2 и принимает вебхук с проверкой подписи. Удобно показать передачу без своего аккаунта Хантфлоу.</p>
        </div>
        <button className="btn-primary" onClick={connectStub}>{s.data?.stub.connected ? "Переподключить тестовую ATS" : "Подключить тестовую ATS"}</button>
      </section>

      <section className="card space-y-4">
        <Toggle checked={f.auto_push} onChange={(v) => setF({ ...f, auto_push: v })} label="Передавать автоматически при принятии приглашения" hint="Вручную — кнопкой «В ATS» в приглашениях и откликах" />
        <div className="border-t border-brand-night/5 pt-4">
          <Toggle checked={f.huntflow.enabled} onChange={(v) => set("huntflow", "enabled", v)} label="Хантфлоу (публичный API v2)" hint="Кандидат создаётся в базе и закрепляется на вакансии на первом этапе (или указанном)" />
          {f.huntflow.enabled && (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Field label="Адрес API" htmlFor="hb" hint="https://api.huntflow.ru/v2 — облако; для коробки — свой адрес"><input id="hb" className="input" value={f.huntflow.base_url ?? ""} onChange={(e) => set("huntflow", "base_url", e.target.value)} /></Field>
              <Field label="Токен доступа" htmlFor="ht" hint={f.huntflow.token_set ? `Сохранён: ${f.huntflow.token_masked}. Оставьте пустым, чтобы не менять.` : "Настройки Хантфлоу → API → токен"}><input id="ht" type="password" autoComplete="off" className="input" value={f.huntflow.token} onChange={(e) => set("huntflow", "token", e.target.value)} /></Field>
              <Field label="ID организации (account_id)" htmlFor="ha"><input id="ha" type="number" className="input" value={f.huntflow.account_id ?? ""} onChange={(e) => set("huntflow", "account_id", e.target.value)} /></Field>
              <Field label="ID вакансии" htmlFor="hv" hint="Пусто — только добавить в базу кандидатов"><input id="hv" type="number" className="input" value={f.huntflow.vacancy_id ?? ""} onChange={(e) => set("huntflow", "vacancy_id", e.target.value)} /></Field>
              <Field label="ID этапа (необязательно)" htmlFor="hs" hint="Пусто — первый этап подбора"><input id="hs" type="number" className="input" value={f.huntflow.status_id ?? ""} onChange={(e) => set("huntflow", "status_id", e.target.value)} /></Field>
              <div className="flex items-end"><button className="btn-ghost" onClick={runCheck} disabled={!f.huntflow.token_set}>Проверить связь</button></div>
            </div>
          )}
          {check && <Alert kind="ok">Связь есть: {check.me?.name}. Организации: {check.accounts.map((a: any) => `${a.name} (id ${a.id})`).join(", ")}. Этапы: {check.statuses.map((x: any) => `${x.name} (${x.id})`).join(", ") || "—"}.</Alert>}
        </div>
        <div className="border-t border-brand-night/5 pt-4">
          <Toggle checked={f.webhook.enabled} onChange={(v) => set("webhook", "enabled", v)} label="Универсальный вебхук" hint="POST JSON (схема vstrechny.candidate.v1) с подписью HMAC-SHA256 — для любой ATS или своей системы" />
          {f.webhook.enabled && (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Field label="URL (https)" htmlFor="wu"><input id="wu" className="input" value={f.webhook.url ?? ""} onChange={(e) => set("webhook", "url", e.target.value)} placeholder="https://ats.example.ru/hooks/vstrechny" /></Field>
              <Field label="Секрет подписи" htmlFor="ws" hint={f.webhook.secret_set ? `Сохранён: ${f.webhook.secret_masked}` : "Пусто — сгенерируем"}><input id="ws" type="password" autoComplete="off" className="input" value={f.webhook.secret} onChange={(e) => set("webhook", "secret", e.target.value)} /></Field>
              <p className="text-xs text-brand-ink/55 sm:col-span-2">Заголовок <code>{s.data?.webhook.signature_header}</code>. Проверка на стороне получателя — в docs/ATS.md.{" "}
                {f.webhook.secret_set && <button className="font-semibold text-brand hover:underline" onClick={async () => setSecret((await api<any>("/employer/ats/webhook-secret")).secret)}>Показать секрет</button>}
                {secret && <code className="ml-2 break-all rounded bg-[#F3F2FB] px-1.5 py-0.5">{secret}</code>}</p>
            </div>
          )}
        </div>
        <button className="btn-primary" onClick={save}>Сохранить</button>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between"><h2 className="font-bold text-brand-night">Журнал передач</h2><button className="text-sm font-semibold text-brand-plum hover:text-brand" onClick={refresh}>Обновить</button></div>
        {!deliveries.data?.length ? <Empty title="Передач пока не было" text="Появятся, когда кандидат примет приглашение или вы нажмёте «В ATS»." /> : (
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#FBF8FC] text-xs uppercase tracking-wider text-brand-ink/50"><tr><th className="px-4 py-2">Когда</th><th>Кандидат</th><th>Куда</th><th>Итог</th><th className="pr-4">Ответ</th></tr></thead>
              <tbody className="divide-y divide-brand-night/5">
                {deliveries.data.map((d) => (
                  <tr key={d.id}><td className="whitespace-nowrap px-4 py-2">{dtt(d.created_at)}</td><td className="pr-3">{d.candidate_ref}<span className="text-brand-ink/50"> · {d.position_title}</span></td><td className="pr-3">{d.target === "huntflow" ? "Хантфлоу" : "Вебхук"}</td>
                    <td className="pr-3"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${d.status === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-brand-blush text-brand-plum"}`}>{d.status === "ok" ? "передано" : "ошибка"}</span> <span className="text-xs text-brand-ink/45">×{d.attempts}</span></td>
                    <td className="pr-4 text-xs text-brand-ink/65">{d.status === "ok" ? (d.result.applicant_id ? `applicant ${d.result.applicant_id}${d.result.vacancy_id ? ` → вакансия ${d.result.vacancy_id}, этап ${d.result.status_id}` : ""}` : `HTTP ${d.http_status}`) : d.error}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {s.data?.stub.connected && (
        <section className="space-y-3">
          <h2 className="font-bold text-brand-night">Тестовая ATS: что пришло</h2>
          {!records.data?.length ? <Empty title="Пока пусто" text="Отправьте приглашение демо-кандидату и примите его — запись появится здесь." /> : (
            <ul className="space-y-2">
              {records.data.map((r) => (
                <li key={r.id} className="card text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-brand-night">{r.kind === "huntflow_applicant" ? `Хантфлоу: кандидат #${r.external_id}` : r.kind === "huntflow_vacancy" ? `Хантфлоу: кандидат #${r.external_id} → вакансия ${r.payload.vacancy}, этап «${r.payload.status_name}»` : `Вебхук ${r.payload.event}`}</p>
                    <span className="text-xs text-brand-ink/50">{dtt(r.created_at)}{r.kind === "webhook" ? (r.signature_valid ? " · подпись верна" : " · подпись НЕ верна") : ""}</span>
                  </div>
                  {r.kind === "huntflow_applicant" && <p className="mt-1 text-brand-ink/70">{[`${r.payload.last_name ?? ""} ${r.payload.first_name ?? ""}`.trim(), r.payload.email, r.payload.phone, r.payload.money].filter(Boolean).join(" · ")}</p>}
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

/** Кнопки у принятого приглашения (страница «Приглашения» работодателя). */
export function AtsInvitationActions({ invitationId, status, candidateRef }: { invitationId: string; status: string; candidateRef?: string }) {
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  if (status !== "accepted") return null;
  async function push() {
    setMsg(null);
    try { const r = await api<any[]>("/employer/ats/push", { body: { invitation_id: invitationId } }); setMsg({ k: "ok", t: r.map((d) => `${d.target === "huntflow" ? "Хантфлоу" : "Вебхук"}: ${d.already_sent ? "уже передано ранее" : d.status === "ok" ? "передано" : d.error}`).join("; ") }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button className="btn-ghost" onClick={push}>В ATS</button>
        <button className="btn-ghost" onClick={() => apiDownload(`/employer/invitations/${invitationId}/export.json`, `candidate-${candidateRef ?? invitationId}.json`)}>Экспорт JSON</button>
      </div>
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
    </div>
  );
}
