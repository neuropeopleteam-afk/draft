import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import InterestCard from "../../components/InterestCard";
import { Alert, Empty, Field, Loading, Modal, dt, errText, num, useApi } from "../../components/ui";
import { api, apiDownload } from "../../lib/api";
import { useAuth } from "../../lib/auth";

type Msg = { k: "ok" | "error"; t: string } | null;

function Block({ title, children, id }: { title: string; children: React.ReactNode; id?: string }) {
  return <section className="card space-y-3" id={id}><h2 className="font-bold text-brand-night">{title}</h2>{children}</section>;
}

function Counts({ items, empty }: { items: Record<string, number>; empty: string }) {
  const rows = Object.entries(items);
  if (!rows.length) return <p className="text-sm text-brand-ink/65">{empty}</p>;
  return (
    <ul className={`text-sm ${rows.length > 5 ? "sm:columns-2 sm:gap-x-8" : ""}`}>
      {rows.map(([k, n]) => (
        <li key={k} className="flex break-inside-avoid items-start justify-between gap-3 border-b border-brand-night/5 py-1.5"><span className="min-w-0">{k}</span><span className="shrink-0 tabular-nums text-brand-ink/65">{num(n, 0)}</span></li>
      ))}
    </ul>
  );
}

export default function MyData() {
  const { data, loading, error, reload } = useApi<any>("/me/data");
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState("");
  const [del, setDel] = useState(false);

  async function download() {
    setMsg(null); setBusy("export");
    try { await apiDownload("/me/data/export", `moi-dannye-${new Date().toISOString().slice(0, 10)}.json`); setMsg({ k: "ok", t: "Файл скачан. В нём все ваши данные одним JSON." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
    finally { setBusy(""); }
  }
  async function revoke(kind: "publication" | "proctoring") {
    setMsg(null); setBusy(kind);
    try {
      await api(kind === "publication" ? "/me/consents/publication" : "/proctor/consent", { method: "DELETE" });
      await reload();
      setMsg({ k: "ok", t: kind === "publication" ? "Согласие на публикацию отозвано: профиль скрыт из подборок и поиска." : "Согласие на камеру отозвано: тесты идут без камеры." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
    finally { setBusy(""); }
  }
  async function revokeContacts() {
    setMsg(null); setBusy("contacts");
    try {
      const r = await api<any>("/me/data/contacts/revoke", { method: "POST", body: {} });
      await reload();
      setMsg({ k: "ok", t: r.revoked ? `Доступ к контактам закрыт у работодателей: ${num(r.revoked, 0)}. Уже полученные контакты вернуть нельзя.` : "Открытых контактов нет." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
    finally { setBusy(""); }
  }

  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  const d = data;
  const consents: any[] = d.consents ?? [];
  const open: any[] = d.contacts_open_to ?? [];
  return (
    <div className="max-w-3xl space-y-6" data-testid="my-data">
      <PageTitle title="Мои данные" subtitle="Что платформа хранит о вас, как забрать всё одним файлом, отозвать согласия и удалить учётную запись (152-ФЗ)." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <InterestCard />

      <Block title="Что о вас хранится">
        <ul className="divide-y divide-brand-night/5 text-sm" data-testid="mydata-stored">
          {d.stored.map((s: any) => (
            <li key={s.key} className="flex flex-col gap-0.5 py-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
              <div className="min-w-0"><p className="font-semibold text-brand-night">{s.title}</p><p className="text-brand-ink/65">{s.what}</p></div>
              <span className="shrink-0 tabular-nums text-brand-ink/80">{s.count ? `записей: ${num(s.count, 0)}` : "нет"}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-brand-ink/65">Пароль хранится только в виде необратимого хеша. Кадры и звук камеры не хранятся вообще.</p>
      </Block>

      <Block title="Скачать всё одним файлом" id="export">
        <p className="text-sm text-brand-ink/70">Один файл JSON: профиль вместе со скрытыми полями, опросы, резюме, ваши ответы теста и итоги, согласия, события камеры, приглашения, задания, отклики, переписка, паспорта и обезличенная отметка интереса.</p>
        <p className="text-xs text-brand-ink/65">В файле нет данных других людей, текстов заданий и ключей ответов (это банк заданий оператора), секретов входа. Достоверность результата — в том виде, как её видите вы.</p>
        <button className="btn-primary" data-testid="mydata-download" disabled={busy === "export"} onClick={download}>{busy === "export" ? "Готовим файл…" : "Скачать мои данные (JSON)"}</button>
      </Block>

      <Block title="Согласия" id="consents">
        <ul className="space-y-3 text-sm">
          {consents.map((c) => (
            <li key={c.kind} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-night/10 p-4" data-testid={`mydata-consent-${c.kind}`}>
              <div className="min-w-0">
                <p className="font-semibold">{c.title}</p>
                <p className="text-brand-ink/65">{c.active ? `Дано ${dt(c.granted_at)}` : c.revoked_at ? `Отозвано ${dt(c.revoked_at)}` : "Не давалось"}</p>
              </div>
              {c.kind === "publication" && c.active && <button className="btn-ghost" disabled={busy === c.kind} onClick={() => revoke("publication")}>Отозвать</button>}
              {c.kind === "proctoring" && c.active && <button className="btn-ghost" disabled={busy === c.kind} onClick={() => revoke("proctoring")}>Отозвать</button>}
              {c.kind === "processing" && <a className="text-xs font-semibold text-brand hover:underline" href="#delete">Отзыв — удалением учётной записи</a>}
              {c.kind === "publication" && !c.active && <Link className="text-xs font-semibold text-brand hover:underline" to="/candidate/settings">Дать снова — в настройках</Link>}
            </li>
          ))}
        </ul>
      </Block>

      <Block title="Кому открыты ваши контакты" id="contacts">
        {open.length ? (
          <>
            <ul className="divide-y divide-brand-night/5 text-sm" data-testid="mydata-contacts">
              {open.map((o) => <li key={o.invitation_id} className="py-2"><p className="font-semibold">{o.company}</p><p className="text-brand-ink/65">{o.position_title} · с {dt(o.since)} · {o.what}</p></li>)}
            </ul>
            <button className="btn-ghost" disabled={busy === "contacts"} onClick={revokeContacts}>Закрыть доступ у всех</button>
            <p className="text-xs text-brand-ink/65">Карточка снова станет обезличенной. То, что работодатель уже получил, вернуть нельзя; по каждому приглашению доступ можно вернуть в разделе «Приглашения».</p>
          </>
        ) : <Empty title="Контакты никому не открыты" text="Они открываются работодателю только после того, как вы приняли его приглашение." />}
      </Block>

      <Block title="Сроки хранения">
        <ul className="divide-y divide-brand-night/5 text-sm">
          {d.retention.map((r: any) => <li key={r.what} className="flex flex-col gap-0.5 py-1.5 sm:flex-row sm:justify-between sm:gap-4"><span>{r.what}</span><span className="text-brand-ink/65 sm:text-right">{r.term}</span></li>)}
        </ul>
        <p className="text-xs leading-relaxed text-brand-ink/65">{d.backups}</p>
      </Block>

      <Block title="Удалить учётную запись" id="delete">
        <p className="text-sm text-brand-ink/70">Это же отзыв согласия на обработку персональных данных. Личные данные, тесты, ответы, резюме и согласия стираются сразу и безвозвратно. Записи работодателей (приглашения, задания, отклики) остаются без привязки к вам — так работодатель не теряет свою историю, а вас по ним узнать нельзя.</p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-brand-ink/70">{d.not_in_our_power.map((t: string) => <li key={t}>{t}</li>)}</ul>
        <button className="btn bg-red-700 text-white hover:bg-red-800" data-testid="mydata-delete-open" onClick={() => setDel(true)}>Удалить учётную запись…</button>
      </Block>

      <p className="text-xs text-brand-ink/65" data-testid="mydata-storage">Где и как обрабатываются данные: {d.operator.storage}.</p>
      <p className="text-xs text-brand-ink/65">Оператор: {d.operator.name} · обращения по данным: {d.operator.email} · редакция согласия {d.consent_version}. Подробнее: <Link className="font-semibold text-brand hover:underline" to="/candidate/settings">Настройки и приватность</Link>.</p>
      <DeleteModal open={del} onClose={() => setDel(false)} conf={d.delete} />
    </div>
  );
}

function DeleteModal({ open, onClose, conf }: { open: boolean; onClose: () => void; conf: any }) {
  const { signOut, me } = useAuth();
  const nav = useNavigate();
  const pre = useApi<any>(open ? "/me/data/delete/preview" : null, [open]);
  const [phrase, setPhrase] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<any>(null);

  async function submit() {
    setErr(""); setBusy(true);
    try {
      const body: any = { confirm: phrase };
      if (conf.needs_password) body.password = password; else body.email = email;
      if (conf.needs_code) body.code = code;
      setDone(await api<any>("/me/data/delete", { method: "POST", body }));
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  }
  function leave() { signOut(); nav("/", { replace: true }); }

  if (done) {
    return (
      <Modal open={open} onClose={leave} title="Учётная запись удалена">
        <div className="space-y-4 text-sm" data-testid="mydata-deleted">
          <Alert kind="ok">Готово. Вход под этой почтой больше невозможен, почту можно использовать для новой регистрации.</Alert>
          <div><p className="mb-1 font-semibold text-brand-night">Удалено сразу</p><Counts items={done.deleted} empty="—" /></div>
          <div><p className="mb-1 font-semibold text-brand-night">Обезличено у работодателей</p><Counts items={done.anonymized} empty="—" /></div>
          <ul className="list-disc space-y-1 pl-5 text-xs text-brand-ink/70">{done.not_in_our_power.map((t: string) => <li key={t}>{t}</li>)}</ul>
          <p className="text-xs text-brand-ink/65">{done.backups}</p>
          <button className="btn-primary" data-testid="mydata-deleted-leave" onClick={leave}>Выйти на главную</button>
        </div>
      </Modal>
    );
  }
  const ready = phrase.trim().toUpperCase() === "УДАЛИТЬ" && (conf.needs_password ? password.length > 0 : email.trim().length > 3) && (!conf.needs_code || code.trim().length >= 6);
  return (
    <Modal open={open} onClose={onClose} title="Удалить учётную запись">
      <div className="space-y-4 text-sm">
        {pre.loading && !pre.data ? <Loading /> : pre.data && (
          <>
            <div><p className="mb-1 font-semibold text-brand-night">Будет удалено сразу</p><Counts items={pre.data.deleted} empty="—" /></div>
            <div><p className="mb-1 font-semibold text-brand-night">Останется у работодателей без привязки к вам</p><Counts items={pre.data.anonymized} empty="Приглашений, заданий и откликов нет." /></div>
            {pre.data.contacts_open_to?.length > 0 && <Alert kind="info">Контакты открыты работодателям: {pre.data.contacts_open_to.length}. Копии у них мы удалить не можем — закройте доступ до удаления в разделе «Кому открыты ваши контакты».</Alert>}
          </>
        )}
        <Field label="Введите слово УДАЛИТЬ" htmlFor="del-phrase"><input id="del-phrase" data-testid="mydata-delete-phrase" className="input" autoComplete="off" value={phrase} onChange={(e) => setPhrase(e.target.value)} /></Field>
        {conf.needs_password
          ? <Field label="Пароль" htmlFor="del-pass"><input id="del-pass" data-testid="mydata-delete-password" type="password" autoComplete="current-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          : <Field label="Ваша почта" hint={conf.demo ? "Демо-учётка входит без пароля — подтвердите почтой, она показана в шапке кабинета." : "Вход через ФСП ID без пароля — подтвердите своей почтой."} htmlFor="del-mail"><input id="del-mail" data-testid="mydata-delete-email" type="email" autoComplete="email" placeholder={me?.email} className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>}
        {conf.needs_code && <Field label="Код из приложения-аутентификатора или резервный код" htmlFor="del-code"><input id="del-code" data-testid="mydata-delete-code" inputMode="text" autoComplete="one-time-code" className="input" value={code} onChange={(e) => setCode(e.target.value)} /></Field>}
        {err && <Alert>{err}</Alert>}
        <div className="flex flex-wrap gap-3">
          <button className="btn bg-red-700 text-white hover:bg-red-800 disabled:opacity-50" data-testid="mydata-delete-confirm" disabled={!ready || busy} onClick={submit}>{busy ? "Удаляем…" : "Удалить безвозвратно"}</button>
          <button className="btn-ghost" onClick={onClose}>Не удалять</button>
        </div>
        <p className="text-xs text-brand-ink/65">Действие необратимо: восстановить учётную запись, тесты и профиль нельзя. Начнёте заново — пройдёте опрос и тест с нуля.</p>
      </div>
    </Modal>
  );
}
