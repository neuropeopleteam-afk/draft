import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Field, Stat, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function EmployerOverview() {
  const { me } = useAuth();
  const company = me?.employer?.company;
  const needs = useApi<any[]>("/employer/needs");
  const inv = useApi<any[]>("/employer/invitations");
  const probes = useApi<any[]>("/employer/probes");
  const accepted = inv.data?.filter((i) => i.status === "accepted").length ?? 0;
  const steps = [
    { done: !!company?.description, title: "Заполните профиль компании", text: "Кандидат увидит его в приглашении.", to: "company" },
    { done: !!needs.data?.length, title: "Опишите потребность", text: "Текстом, как в обычной вакансии, — требования структурируем автоматически.", to: "needs" },
    { done: !!probes.data?.length, title: "Отправьте зонд", text: "Короткая задача с вилкой зарплаты — свежий сигнал до приглашения.", to: "needs" },
    { done: !!inv.data?.length, title: "Пригласите кандидата", text: "С вилкой «от–до» в рублях. Контакты откроются после согласия кандидата.", to: "search" },
  ];
  return (
    <div className="max-w-4xl">
      <PageTitle title={company?.name ?? "Кабинет работодателя"} subtitle="Найдите проверенных кандидатов по категории и выйдите на контакт первым." />
      <div className="mt-8 grid gap-5 md:grid-cols-3">
        <Stat label="Потребности" value={needs.data?.length ?? "…"} />
        <Stat label="Приглашения" value={inv.data?.length ?? "…"} hint={inv.data ? `принято: ${accepted}` : undefined} />
        <Stat label="Зонды" value={probes.data?.length ?? "…"} hint={probes.data ? `ждут оценки: ${probes.data.filter((p) => p.status === "submitted").length}` : undefined} />
      </div>
      <section className="card mt-8">
        <h2 className="text-lg font-bold text-brand-night">С чего начать</h2>
        <ol className="mt-5 space-y-4">
          {steps.map((s, i) => (
            <li key={s.title} className="flex items-start gap-4">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${s.done ? "bg-brand text-white" : "bg-brand-plum text-white"}`}>{s.done ? "✓" : i + 1}</span>
              <div className="flex-1">
                <p className="font-semibold">{s.title}</p>
                <p className="text-sm text-brand-ink/65">{s.text}</p>
              </div>
              <Link to={s.to} className="text-sm font-semibold text-brand hover:text-brand-soft">Перейти</Link>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

export function Company() {
  const { me, refresh } = useAuth();
  const c: any = me?.employer?.company ?? {};
  const [f, setF] = useState({ name: "", inn: "", industry: "", description: "", website: "", city: "", contact_email: "", contact_phone: "" });
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  useEffect(() => {
    setF({ name: c.name ?? "", inn: c.inn ?? "", industry: c.industry ?? "", description: c.description ?? "", website: c.website ?? "", city: c.city ?? "", contact_email: c.contact_email ?? "", contact_phone: c.contact_phone ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setMsg(null);
    try {
      const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || null]));
      if (!body.name) { setMsg({ k: "error", t: "Укажите название компании" }); return; }
      await api("/me/company", { method: "PATCH", body });
      await refresh(); setMsg({ k: "ok", t: "Профиль компании сохранён." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  return (
    <div className="max-w-3xl space-y-6">
      <PageTitle title="Профиль компании" subtitle="Эти сведения кандидат увидит в зонде и приглашении." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <section className="card grid gap-4 sm:grid-cols-2">
        <Field label="Название" htmlFor="cn"><input id="cn" className="input" value={f.name} onChange={set("name")} /></Field>
        <Field label="ИНН" htmlFor="ci" hint="10 или 12 цифр"><input id="ci" className="input" value={f.inn} onChange={set("inn")} /></Field>
        <Field label="Сфера" htmlFor="cind"><input id="cind" className="input" value={f.industry} onChange={set("industry")} placeholder="Финтех, ритейл, госсектор…" /></Field>
        <Field label="Город" htmlFor="ccity"><input id="ccity" className="input" value={f.city} onChange={set("city")} /></Field>
        <div className="sm:col-span-2"><Field label="О компании" htmlFor="cd"><textarea id="cd" className="input min-h-[110px]" value={f.description} onChange={set("description")} /></Field></div>
        <Field label="Сайт" htmlFor="cw"><input id="cw" className="input" value={f.website} onChange={set("website")} placeholder="https://" /></Field>
        <Field label="Почта для кандидатов" htmlFor="ce"><input id="ce" className="input" value={f.contact_email} onChange={set("contact_email")} /></Field>
        <Field label="Телефон" htmlFor="cp"><input id="cp" className="input" value={f.contact_phone} onChange={set("contact_phone")} /></Field>
        <div className="flex items-end"><button className="btn-primary" onClick={save}>Сохранить</button></div>
      </section>
    </div>
  );
}
