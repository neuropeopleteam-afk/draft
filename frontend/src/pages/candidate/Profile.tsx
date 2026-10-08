import { useRef, useState } from "react";
import { PageTitle } from "../../components/CabinetLayout";
import { CandidateCard } from "../../components/CandidateCard";
import { Alert, Field, Level, Loading, dtt, errText, useApi, years } from "../../components/ui";
import { api, apiDownload, apiUpload } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { LlmOff } from "../../components/LlmOff";

export default function Profile() {
  const { me, refresh } = useAuth();
  const c: any = me?.candidate ?? {};
  const [form, setForm] = useState({ full_name: c.full_name ?? "", phone: c.phone ?? "", telegram: c.telegram ?? "" });
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const resume = useApi<any>("/me/resume");
  const card = useApi<any>("/me/card");
  const [upload, setUpload] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function saveContacts(extra?: Partial<typeof form>) {
    setMsg(null);
    try {
      const body = { ...form, ...extra };
      await api("/me/candidate-profile", { method: "PATCH", body: { full_name: body.full_name || null, phone: body.phone || null, telegram: body.telegram || null } });
      setForm(body); await refresh(); setMsg({ k: "ok", t: "Контакты сохранены. Работодатель увидит их только после того, как вы примете приглашение." });
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
    try { await api(`/me/resume/${id}/apply`, { body: {} }); await card.reload(); setMsg({ k: "ok", t: "Поля резюме добавлены в профиль как самоописание (T0)." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }

  const r = upload ?? resume.data;
  const found = upload?.pii_found;

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Профиль и резюме" subtitle="Контакты скрыты от работодателей до принятия приглашения. Резюме обрабатывается без передачи ФИО и контактов наружу." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <section className="card">
        <h2 className="font-bold text-brand-night">Контакты</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <Field label="Имя и фамилия" htmlFor="fn"><input id="fn" className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="Телефон" htmlFor="ph"><input id="ph" className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+7 900 000-00-00" /></Field>
          <Field label="Telegram" htmlFor="tg"><input id="tg" className="input" value={form.telegram} onChange={(e) => setForm({ ...form, telegram: e.target.value })} placeholder="@username" /></Field>
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button className="btn-primary" onClick={() => saveContacts()}>Сохранить контакты</button>
          <button className="btn-ghost" onClick={() => apiDownload("/me/profile.pdf", `profile-${c.public_ref ?? "me"}.pdf`).catch((e) => setMsg({ k: "error", t: errText(e) }))}>Скачать PDF-профиль</button>
        </div>
      </section>

      <section className="card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-bold text-brand-night">Резюме PDF</h2>
            <p className="mt-1 max-w-xl text-sm text-brand-ink/65">Извлечём стек, роли, стаж и софт-скиллы. ФИО и контакты вырезаются на нашем сервере до любой обработки моделью; исходный файл не хранится.</p>
            <LlmOff className="mt-1 max-w-xl text-xs text-brand-ink/65">LLM на этой установке не подключён: резюме разбирается по словарям и правилам, нераспознанное добавьте вручную.</LlmOff>
          </div>
          <label className={`btn-primary cursor-pointer ${busy ? "pointer-events-none opacity-60" : ""}`}>
            {busy ? "Распознаём…" : "Загрузить PDF"}
            <input ref={fileRef} type="file" accept="application/pdf" className="sr-only" onChange={(e) => onFile(e.target.files?.[0])} />
          </label>
        </div>
        {resume.loading && !r ? <div className="mt-4"><Loading /></div> : r ? (
          <div className="mt-5 space-y-4">
            <p className="text-sm text-brand-ink/65">{r.filename} · {r.pages} стр. · {r.created_at ? dtt(r.created_at) : "только что"} · {r.method === "rules" ? "разбор по словарям" : "разбор: словари + LLM"}</p>
            <div className="rounded-xl bg-[#F3F2FB] p-4 text-sm">
              <p className="font-semibold text-brand-night">Вырезано до обработки</p>
              <p className="mt-1 text-brand-ink/70">
                {Object.entries(r.pii_summary ?? {}).filter(([k]) => k !== "ner").map(([k, v]) => `${({ person: "ФИО", email: "почта", phone: "телефон", telegram: "Telegram", url_messenger: "ссылки на профили", birthdate: "дата рождения", snils: "СНИЛС", passport: "паспорт", address: "адрес" } as any)[k] ?? k}: ${v}`).join(" · ") || "персональных данных не найдено"}
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

      <section>
        <h2 className="mb-3 font-bold text-brand-night">Как вас видит работодатель</h2>
        {card.data ? <CandidateCard c={card.data} /> : <Loading />}
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
