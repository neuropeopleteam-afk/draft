import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { CandidateCard } from "../../components/CandidateCard";
import { Alert, Field, Level, Loading, dtt, errText, useApi, years } from "../../components/ui";
import { api, apiDownload, apiUpload } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { YouthProfile } from "../../integrations/Youth";
import { LlmOff } from "../../components/LlmOff";

export default function Profile() {
  const { me, refresh } = useAuth();
  const c: any = me?.candidate ?? {};
  const ageGroup = c.age_group ?? "18+";
  const maxExpByAge = ageGroup === "14-15" ? 1 : ageGroup === "16-17" ? 3 : 45;
  const [form, setForm] = useState({
    full_name: c.full_name ?? "",
    phone: c.phone ?? "",
    telegram: c.telegram ?? "",
    experience_years: c.experience_years != null ? String(c.experience_years) : "",
  });
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const resume = useApi<any>("/me/resume");
  const card = useApi<any>("/me/card");
  const fsp = useApi<any>("/me/fsp");
  const [upload, setUpload] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const expVal = form.experience_years.trim();
  const expNum = Number(expVal);
  const expOutOfRange = expVal !== "" && !(expNum >= 0 && expNum <= 45);
  const expExceedsAge = expVal !== "" && !expOutOfRange && expNum > maxExpByAge;
  const expBad = expOutOfRange || expExceedsAge;
  const expErrMsg = expExceedsAge
    ? `Стаж не может быть больше возраста минус 14 лет (для возрастной группы ${ageGroup} — максимум ${maxExpByAge} г.)`
    : "Стаж — от 0 до 45 лет (и не больше, чем возраст минус 14 лет)";

  async function saveContacts(extra?: Partial<typeof form>) {
    setMsg(null);
    const body = { ...form, ...extra };
    const ev = body.experience_years.trim();
    if (ev !== "") {
      const n = Number(ev);
      if (!(n >= 0 && n <= 45)) {
        setMsg({ k: "error", t: "Стаж — от 0 до 45 лет (и не больше, чем возраст минус 14 лет)" });
        return;
      }
      if (n > maxExpByAge) {
        setMsg({ k: "error", t: `Стаж не может быть больше возраста минус 14 лет (для возрастной группы ${ageGroup} — максимум ${maxExpByAge} г.)` });
        return;
      }
    }
    try {
      const patchBody: Record<string, unknown> = {
        full_name: body.full_name || null,
        phone: body.phone || null,
        telegram: body.telegram || null,
      };
      if (ev !== "") patchBody.experience_years = Number(ev);
      await api("/me/candidate-profile", { method: "PATCH", body: patchBody });
      setForm(body); await refresh(); await card.reload();
      setMsg({ k: "ok", t: "Контакты сохранены. Работодатель увидит их только после того, как вы примете приглашение." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }

  async function onFile(f: File | undefined) {
    if (!f) return;
    setBusy(true); setMsg(null);
    try { setUpload(await apiUpload<any>("/me/resume", f)); await resume.reload(); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function applyResume(id: string) {
    try { await api(`/me/resume/${id}/apply`, { body: {} }); await card.reload(); setMsg({ k: "ok", t: "Поля резюме добавлены в профиль как самозаявленные: работодатель видит их с пометкой «самозаявлено». Подтверждает навыки проверка на платформе." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }

  const r = upload ?? resume.data;
  const found = upload?.pii_found;

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Профиль и резюме" subtitle="Контакты скрыты от работодателей до принятия приглашения. Резюме обрабатывается без передачи ФИО и контактов наружу." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <YouthProfile onSaved={() => { void card.reload(); }} />
      <section className="card">
        <h2 className="font-bold text-brand-night">Контакты</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Имя и фамилия" htmlFor="fn"><input id="fn" className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="Телефон" htmlFor="ph"><input id="ph" className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+7 900 000-00-00" /></Field>
          <Field label="Telegram" htmlFor="tg"><input id="tg" className="input" value={form.telegram} onChange={(e) => setForm({ ...form, telegram: e.target.value })} placeholder="@username" /></Field>
          <Field label="Коммерческий стаж, лет" htmlFor="profile-exp" hint={expBad ? undefined : maxExpByAge < 45 ? `От 0 до ${maxExpByAge} лет (не больше возраста − 14)` : "От 0 до 45 лет (не больше возраста − 14)"}>
            <input id="profile-exp" type="number" min={0} max={maxExpByAge} step={0.5} className="input" value={form.experience_years} onChange={(e) => setForm({ ...form, experience_years: e.target.value })} aria-invalid={expBad} aria-describedby={expBad ? "profile-exp-err" : undefined} />
            {expBad && <p id="profile-exp-err" role="alert" className="mt-1 text-xs font-semibold text-brand-plum">{expErrMsg}</p>}
          </Field>
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button className="btn-primary" disabled={expBad} onClick={() => saveContacts()}>Сохранить контакты</button>
          <button className="btn-ghost" onClick={() => apiDownload("/me/profile.pdf", `profile-${c.public_ref ?? "me"}.pdf`).catch((e) => setMsg({ k: "error", t: errText(e) }))}>Скачать PDF-профиль</button>
        </div>
        <p className="mt-3 text-xs text-brand-ink/65">Все данные одним файлом и удаление учётной записи — в разделе <Link className="font-semibold text-brand hover:underline" to="/candidate/mydata">«Мои данные»</Link>.</p>
      </section>

      <section className="card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-bold text-brand-night">Резюме PDF или DOCX</h2>
            <p className="mt-1 max-w-xl text-sm text-brand-ink/65">Извлечём стек, роли, стаж и софт-скиллы — как самозаявленные, не подтверждённые тестом. ФИО, контакты, адрес, дата рождения и возраст вырезаются на нашем сервере до любой обработки моделью (город остаётся для подбора); исходный файл не хранится. До 5 МБ.</p>
            <LlmOff className="mt-1 max-w-xl text-xs text-brand-ink/65">Языковая модель на этой установке не подключена: резюме разбирается по словарям и правилам, нераспознанное добавьте вручную.</LlmOff>
          </div>
          <label className={`btn-primary cursor-pointer ${busy ? "pointer-events-none opacity-60" : ""}`}>
            {busy ? "Распознаём…" : "Загрузить PDF или DOCX"}
            <input ref={fileRef} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="sr-only" onChange={(e) => onFile(e.target.files?.[0])} />
          </label>
        </div>
        {resume.loading && !r ? <div className="mt-4"><Loading /></div> : r ? (
          <div className="mt-5 space-y-4">
            <p className="break-words text-sm text-brand-ink/65">{r.filename} · {r.pages ? `${r.pages} стр.` : "DOCX"} · {r.created_at ? dtt(r.created_at) : "только что"} · {r.method === "rules" ? "разбор по словарям" : `разбор: словари + ${r.extracted?.llm?.model_label ?? "LLM"}`}</p>
            <div className="rounded-xl bg-[#F3F2FB] p-4 text-sm">
              <p className="font-semibold text-brand-night">Вырезано до обработки</p>
              <p className="mt-1 text-brand-ink/70">
                {Object.entries(r.pii_summary ?? {}).filter(([k]) => k !== "ner").map(([k, v]) => `${({ person: "ФИО", email: "почта", phone: "телефон", telegram: "Telegram", url_messenger: "ссылки на профили", birthdate: "дата рождения", age: "возраст", gender: "пол", snils: "СНИЛС", passport: "паспорт", inn: "ИНН", address: "адрес" } as any)[k] ?? k}: ${v}`).join(" · ") || "персональных данных не найдено"}
              </p>
              {found && (found.full_name || found.email || found.phone) && (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <span className="text-brand-ink/70">Найдено в резюме: {[found.full_name, found.email, found.phone].filter(Boolean).join(", ")}</span>
                  <button className="text-sm font-semibold text-brand hover:underline" onClick={() => saveContacts({
                    full_name: form.full_name || found.full_name || "", phone: form.phone || found.phone || "", telegram: form.telegram || found.telegram || "",
                  })}>Перенести в контакты</button>
                </div>
              )}
            </div>
            {r.text_preview && (
              <details className="rounded-xl border border-brand-night/10 bg-[#F7F6FB] p-3.5 text-sm" data-testid="resume-llm-view">
                <summary className="cursor-pointer font-semibold text-brand-night">
                  Что видит языковая модель (текст резюме после вырезания ФИО и контактов, 152-ФЗ)
                </summary>
                <p className="mt-1 text-xs text-brand-ink/65">
                  Ниже — обезличенный текст, очищенный на сервере до извлечения навыков. ФИО, телефон, почта, ссылки и паспортные данные в модель не передаются.
                </p>
                <pre className="mt-2 max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-white p-3 font-mono text-xs text-brand-ink/80 ring-1 ring-brand-night/10">
                  {r.text_preview}
                </pre>
              </details>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <Extracted title="Стек" items={r.extracted?.stack?.map((s: any) => s.title)} />
              <Extracted title="Роли" items={r.extracted?.roles?.map((s: any) => s.title)} />
              <Extracted title="Софт-скиллы" items={r.extracted?.soft_skills?.map((s: any) => s.title)} />
              <Extracted title="Стаж" items={r.extracted?.experience_years != null ? [years(r.extracted.experience_years)] : []} />
            </div>
            <button className="btn-ghost" onClick={() => applyResume(r.id)}>Добавить в профиль</button>
          </div>
        ) : <p className="mt-4 text-sm text-brand-ink/65">Резюме ещё не загружено.</p>}
      </section>

      <section className="card space-y-3" data-testid="profile-fsp-block">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-bold text-brand-night">Паспорт ФСП</h2>
            <Level level={fsp.data?.linked ? "T2" : "none"} />
          </div>
          <Link to="/candidate/fsp" className="btn-ghost !px-3.5 !py-1.5 text-xs">
            Управление паспортом и протоколы ФСП →
          </Link>
        </div>
        {fsp.data?.achievements?.length ? (
          <div className="space-y-2 text-sm">
            {fsp.data.sport_rank && <p className="text-brand-ink/80">Спортивный разряд: <b>{fsp.data.sport_rank}</b></p>}
            <ul className="space-y-1 text-brand-ink/75">
              {fsp.data.achievements.slice(0, 3).map((a: any, i: number) => (
                <li key={i}>• {a.text}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-brand-ink/70">
            Подтвердите спортивные достижения по официальным протоколам ФСП (2025–2026) или укажите ФСП ID — это даёт дополнительный вес в подборках работодателей. Отсутствие истории ФСП не штрафуется.
          </p>
        )}
      </section>

      <section>
        <h2 className="mb-3 font-bold text-brand-night">Как вас видит работодатель</h2>
        {card.data ? <CandidateCard c={card.data} viewerRole="candidate" /> : <Loading />}
      </section>
    </div>
  );
}

function Extracted({ title, items }: { title: string; items?: string[] }) {
  return (
    <div className="rounded-xl border border-brand-night/10 p-4">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{title} <Level level="T0" /></p>
      <p className="mt-2 text-sm">{items?.length ? items.join(", ") : <span className="text-brand-ink/65">не найдено</span>}</p>
    </div>
  );
}
