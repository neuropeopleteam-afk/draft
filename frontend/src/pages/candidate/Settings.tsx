import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Toggle, dt, errText, num, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { NO_FSP, OriginTag } from "../../components/Origin";
import { FspIdLinkButton } from "../../integrations/FspId";
import { CupPassportEvents } from "../../ideas/cup/Candidate";
import { useAuth } from "../../lib/auth";
import { CameraSettings } from "../../proctor/CameraReport";
import { MutualPrefs } from "../mutual/Candidate";  // интересы для взаимного подбора (Н9)

export function Fsp() {
  const { data, loading, error, reload } = useApi<any>("/me/fsp");
  const [id, setId] = useState("");
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const [fio, setFio] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [team, setTeam] = useState("");
  const [pRes, setPRes] = useState<any>(null);
  const [pPick, setPPick] = useState<string[]>([]);
  const [pConsent, setPConsent] = useState(true);
  const [pBusy, setPBusy] = useState(false);
  useEffect(() => {
    if (data?.fsp_id_claimed) setId(data.fsp_id_claimed);
    if (data?.full_name && !fio) setFio(data.full_name);
    if (typeof data?.show_fsp === "boolean") setPConsent(data.show_fsp);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  async function link() {
    setMsg(null);
    try { const r = await api<any>("/me/fsp/link", { body: { fsp_id: id } }); setMsg({ k: "ok", t: r.message }); await reload(); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function searchProtocols() {
    setMsg(null); setPBusy(true);
    try {
      const r = await api<any>("/me/fsp/protocols/search", {
        body: { fio: fio.trim() || null, birth_date: birthDate.trim() || null, team: team.trim() || null },
      });
      setPRes(r);
      setPPick((r.matches ?? []).map((m: any) => m.record_id ?? m.key_hash));
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
    finally { setPBusy(false); }
  }
  async function confirmProtocols() {
    if (!pPick.length) return;
    setMsg(null); setPBusy(true);
    try {
      const r = await api<any>("/me/fsp/protocols/confirm", {
        body: { key_hashes: pPick, consent_employers: pConsent },
      });
      setMsg({ k: "ok", t: r.message || "Подтверждено по официальному протоколу ФСП." });
      setPRes(null);
      await reload();
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
    finally { setPBusy(false); }
  }
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  return (
    <div className="max-w-3xl space-y-6">
      <PageTitle title="Паспорт ФСП" subtitle="Достижения в соревнованиях по дисциплинам спортивного программирования (ЕВСК) — факты, подтверждённые реестром и официальными протоколами Федерации." />
      <section className="card space-y-4">
        <div className="flex flex-wrap items-center gap-3"><Level level={data.linked ? "T2" : "none"} /><p className="font-semibold text-brand-night">{data.linked ? "Паспорт связан" : "Паспорт не связан"}</p>{data.origin && <OriginTag o={data.origin} />}</div>
        <p className="text-sm text-brand-ink/70">{data.link_source === "keycloak" ? `Паспорт связан через ФСП ID${data.fsp_id_claimed ? ` (${data.fsp_id_claimed})` : ""}: достижения подтверждены реестром ФСП.` : data.note}</p>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-xl bg-[#F3F2FB] p-4 text-center text-sm" data-testid="fsp-identity-link">
          <div className="min-w-0"><p className="font-bold text-brand-night">ФСП ID</p><p className="mt-1 break-all text-xs text-brand-ink/70">{data.fsp_id_claimed || "Не указан"}</p></div>
          <span className="text-brand-plum" aria-label="Связь">↔</span>
          <div><p className="font-bold text-brand-night">Ваш профиль</p><p className="mt-1 text-xs text-brand-ink/70">{data.identity_linked ? "Вход подтверждён OIDC" : data.linked ? "Реестр ФСП подключается по договору с федерацией" : "Ожидает связи"}</p></div>
        </div>
        {data.registry?.demo && <Alert kind="info">Реестр ФСП подключается по договору с федерацией. На демонстрационном стенде показаны тестовые достижения для проверки сценария.</Alert>}
        {data.registry_warning && <Alert kind="info">{data.registry_warning}</Alert>}
        {data.sport_rank && <p className="text-sm">Спортивный разряд: <b>{data.sport_rank}</b></p>}
        <FspIdLinkButton linkedVia={data.link_source} />
        {data.registry_sync_available && <button className="btn-ghost" data-testid="button-fsp-registry-sync" onClick={async () => {
          setMsg(null);
          try { await api("/me/fsp/registry-sync", { body: {} }); await reload(); setMsg({ k: "ok", t: "Достижения обновлены из API реестра." }); }
          catch (e) { setMsg({ k: "error", t: errText(e) }); }
        }}>Обновить достижения из реестра</button>}
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
      <section className="card space-y-4" data-testid="fsp-protocol-verify">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="font-bold text-brand-night">Подтверждение по официальным протоколам ФСП (2025–2026)</h2>
            <p className="mt-1 text-sm text-brand-ink/70">
              Поиск по индексу 18 официальных итоговых протоколов соревнований ФСП и списку кандидатов в сборную РФ 2026 (fsp-russia.ru). Работодатели увидят подтверждённый результат только с вашего согласия.
            </p>
          </div>
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${data.protocols_available ? "bg-emerald-50 text-emerald-800" : "bg-gray-100 text-gray-600"}`}>
            {data.protocols_available ? `Протоколы подключены (${num(data.protocols_indexed, 0)} записей)` : "Индекс не подключён"}
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="ФИО спортсмена" htmlFor="pfio">
            <input id="pfio" className="input" value={fio} onChange={(e) => setFio(e.target.value)} placeholder="Фамилия Имя Отчество" />
          </Field>
          <Field label="Дата или год рождения (необязательно)" htmlFor="pbirth">
            <input id="pbirth" className="input" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} placeholder="Например: 2004 или 22.02.2004" />
          </Field>
          <Field label="Команда (необязательно)" htmlFor="pteam">
            <input id="pteam" className="input" value={team} onChange={(e) => setTeam(e.target.value)} placeholder="Для командных зачётов" />
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" disabled={pBusy || (!fio.trim() && !team.trim())} onClick={searchProtocols} data-testid="fsp-protocol-search-btn">
            {pBusy ? "Проверяем протоколы…" : "Проверить по протоколам ФСП"}
          </button>
        </div>
        {pRes && (
          <div className="space-y-3 rounded-xl border border-brand-night/10 bg-[#F7F6FB] p-4 text-sm">
            <p className="font-semibold text-brand-night">{pRes.message}</p>
            {(pRes.matches ?? []).length > 0 && (
              <>
                <ul className="space-y-2">
                  {pRes.matches.map((m: any) => {
                    const key = m.record_id ?? m.key_hash;
                    const checked = pPick.includes(key);
                    return (
                      <li key={key} className="rounded-xl bg-white p-3 ring-1 ring-brand-night/10">
                        <label className="flex cursor-pointer items-start gap-3">
                          <input
                            type="checkbox"
                            className="mt-1 accent-brand"
                            checked={checked}
                            onChange={(e) => setPPick(e.target.checked ? [...pPick, key] : pPick.filter((x) => x !== key))}
                          />
                          <div className="min-w-0 flex-1 space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-800">
                                {m.status_title ?? "Подтверждено по официальному протоколу ФСП"}
                              </span>
                              {m.rank && <span className="chip">Разряд/звание: {m.rank}</span>}
                              {m.place != null && <span className="chip">Место: {m.place}</span>}
                            </div>
                            <p className="font-semibold text-brand-night">{m.event_title}</p>
                            <p className="text-xs text-brand-ink/70">
                              {[
                                m.discipline_title ? `Дисциплина: ${m.discipline_title}` : null,
                                m.ekp_no ? `ЕКП № ${m.ekp_no}` : null,
                                m.date ? `Дата: ${m.date}` : null,
                                m.team ? `Команда: ${m.team}` : null,
                                m.region ? `Регион: ${m.region}` : null,
                              ].filter(Boolean).join(" · ")}
                            </p>
                            {m.pdf_url && (
                              <p className="text-xs">
                                <a href={m.pdf_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-brand hover:underline">
                                  Официальный протокол PDF (fsp-russia.ru){m.page ? `, стр. ${m.page}` : ""} ↗
                                </a>
                              </p>
                            )}
                          </div>
                        </label>
                      </li>
                    );
                  })}
                </ul>
                <Toggle
                  checked={pConsent}
                  onChange={setPConsent}
                  label="Показывать подтверждённые достижения работодателям в обезличенной карточке"
                  hint="ФИО и дата рождения не передаются — работодатель видит только факт достижения, дисциплину, место/разряд и ссылку на протокол."
                />
                <button type="button" className="btn-primary" disabled={pBusy || !pPick.length} onClick={confirmProtocols} data-testid="fsp-protocol-confirm-btn">
                  Подтвердить и прикрепить к паспорту ({pPick.length})
                </button>
              </>
            )}
          </div>
        )}
      </section>
      {data.rating && (
        <section className="card space-y-3" title={`Коэффициент: ${num(data.rating.strength, 3)}`}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-bold text-brand-night">Индекс достижений ФСП: {Math.round((Number(data.rating.strength) || 0) * 100)} из 100</h2>
            <span className="text-xs font-semibold text-emerald-800">+10 % вес в подборках работодателей</span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-brand-night/10" aria-hidden="true">
            <div className="h-full rounded-full bg-brand-strong" style={{ width: `${Math.max(4, Math.min(100, Math.round((Number(data.rating.strength) || 0) * 100)))}%` }} />
          </div>
          <p className="text-sm text-brand-ink/70">{data.rating.policy}</p>
          <p className="text-xs text-brand-ink/65">Учтено соревнований: {num(data.rating.competitions, 0)}. Даёт приоритет внутри своей категории и виден компаниям как подтверждённый факт.</p>
        </section>
      )}
      {data.achievements?.length ? (
        <section className="card">
          <h2 className="font-bold text-brand-night">Достижения</h2>
          <ul className="mt-3 space-y-3 text-sm">
            {data.achievements.map((a: any, i: number) => (
              <li key={i} className="flex items-start gap-2">
                <Level level="T2" />
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p>{a.text}</p>
                    {a.protocol_verified && (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                        {a.status_title ?? "Подтверждено по официальному протоколу ФСП"}
                      </span>
                    )}
                  </div>
                  {(a.team || a.evsk_code || a.ekp_no || a.sport_rank || a.region) && (
                    <p className="mt-1 text-xs text-brand-ink/65">
                      {[
                        a.team ? `Команда: ${a.team}` : null,
                        a.team_result?.place ? `командное место: ${num(a.team_result.place, 0)}` : null,
                        a.ekp_no ? `ЕКП № ${a.ekp_no}` : a.evsk_code ? `ЕВСК: ${a.evsk_code}` : null,
                        a.sport_rank ? `разряд: ${a.sport_rank}` : null,
                        a.region ? `регион: ${a.region}` : null,
                      ].filter(Boolean).join(" · ")}
                    </p>
                  )}
                  {a.pdf_url && (
                    <p className="mt-1 text-xs">
                      <a href={a.pdf_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-brand hover:underline">
                        Официальный протокол PDF (fsp-russia.ru){a.page ? `, стр. ${a.page}` : ""} ↗
                      </a>
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : <Empty title="Достижений нет" text={`${NO_FSP}.`} />}
      <CupPassportEvents />
    </div>
  );
}

const CONSENT_TITLE: Record<string, string> = { processing: "Обработка персональных данных", publication: "Публикация обезличенного профиля" };

export function Settings() {
  const { me, refresh } = useAuth();
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
        <p className="mt-1 text-sm text-brand-ink/65">Имя, почта, телефон и сумма минимума зарплаты в подборке и карточке не показываются. Контакты — только после принятия приглашения. По умолчанию работодатель видит лишь «вилка в ожиданиях / ниже ожиданий» — это выключается ниже, в «Интересах».</p>
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
                {k === "processing" && <Link className="text-xs font-semibold text-brand hover:underline" to="/candidate/mydata#delete">Отозвать: удалить учётную запись</Link>}
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-sm text-brand-ink/70">Скачать все данные, закрыть доступ к контактам и удалить учётную запись — в разделе <Link className="font-semibold text-brand hover:underline" to="/candidate/mydata">«Мои данные»</Link>.</p>
        {text && <div className="mt-4 rounded-xl bg-[#F3F2FB] p-4 text-xs leading-relaxed text-brand-ink/80"><p className="mb-2 font-semibold">{text.title}</p><p className="whitespace-pre-line">{text.text}</p></div>}
      </section>
      <CameraSettings />
    </div>
  );
}
