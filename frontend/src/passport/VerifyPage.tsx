// Публичная проверка паспорта грейда /verify/:id — без входа и без пароля стенда (infra/nginx/…passport.conf).
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Alert, Loading, dt, dtt, errText, num, pct } from "../components/ui";
import { api } from "../lib/api";
import { GRADE_STATUS, INTEGRITY, STATE_HINT, STATE_STYLE, StateBadge, type PassportPublic } from "./common";

interface FileCheck { state: string; signature_valid: boolean; kid_known: boolean; matches_registry: boolean; registry: { title: string; reason_title: string | null } | null }

const FILE_STATE: Record<string, string> = {
  valid: "Подпись верна, паспорт совпадает с реестром и действителен.",
  revoked: "Подпись верна, но паспорт отозван.",
  expired: "Подпись верна, но срок паспорта истёк.",
  invalid_signature: "Подпись не сходится: файл изменён или подписан не нашим ключом.",
  differs: "Подпись верна, но файл отличается от записи реестра.",
  not_in_registry: "Подпись верна, но паспорта с таким id в реестре нет.",
};

export default function PassportVerify() {
  const { id = "" } = useParams();
  const [d, setD] = useState<PassportPublic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  useEffect(() => {
    document.title = "Проверка паспорта грейда · Встречный";
    api<PassportPublic>(`/passport/${encodeURIComponent(id)}`, { auth: false })
      .then(setD)
      .catch((e) => { if ((e as { status?: number }).status === 404) setNotFound(true); else setError(errText(e)); });
  }, [id]);

  return (
    <div className="min-h-screen bg-[#F7F6FB]">
      <header className="border-b border-brand-night/10 bg-white">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <Link to="/" aria-label="На главную"><Logo /></Link>
          <span className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Проверка паспорта грейда</span>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8 sm:px-6">
        {notFound && (
          <section className="card">
            <h1 className="text-xl font-bold text-brand-night">Паспорт не найден</h1>
            <p className="mt-2 text-sm text-brand-ink/75">Проверьте ссылку: такого паспорта в реестре платформы нет. Если ссылку прислал кандидат, попросите выпустить новую.</p>
          </section>
        )}
        <Alert>{error}</Alert>
        {!d && !notFound && !error && <Loading text="Проверяем подпись…" />}
        {d && <Body d={d} />}
      </main>
    </div>
  );
}

function Body({ d }: { d: PassportPublic }) {
  const p = d.passport;
  const s = d.status;
  const a = p.assessment;
  return (
    <>
      <section role="status" aria-live="polite" className={`rounded-2xl border p-5 sm:p-6 ${STATE_STYLE[s.state]}`}>
        <p className="text-xs font-semibold uppercase tracking-[0.12em] opacity-75">Статус паспорта</p>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">{s.title}</h1>
        <p className="mt-2 text-sm">{STATE_HINT[s.state]}{s.reason_title ? ` Причина: ${s.reason_title}${s.revoked_at ? `, ${dt(s.revoked_at).replace(/ г\.$/, "")}` : ""}.` : ""}</p>
        <p className="mt-2 text-xs opacity-80">Проверено {dtt(s.checked_at)} · подпись Ed25519 {s.signature_valid ? "верна" : "не сходится"}{s.kid_known ? "" : " · ключ подписи неизвестен"}</p>
        {s.test_key && <p className="mt-2 rounded-lg bg-white/70 px-3 py-2 text-xs font-semibold">Подписано тестовым ключом стенда разработки: это демонстрация механизма, а не доказательство.</p>}
      </section>

      <section className="card" aria-labelledby="pp-composition">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Категория</p>
            <h2 id="pp-composition" className="mt-1 text-2xl font-extrabold tracking-tight text-brand-night">{p.category.title}</h2>
            <p className="mt-1 text-sm text-brand-ink/70">Кандидат {p.subject.public_ref} · обезличенный идентификатор, без ФИО и контактов</p>
          </div>
          <StateBadge state={p.grade_status === "confirmed" ? "valid" : "expired"}>{GRADE_STATUS[p.grade_status] ?? p.grade_status}</StateBadge>
        </div>
        {a && (
          <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
            <Row k="Тест пройден" v={dt(a.test_date)} />
            <Row k="Оценка уровня θ" v={a.theta != null ? `${num(a.theta)} ± ${num(a.se)}` : "—"} />
            <Row k={`Вероятность уровня не ниже ${p.category.grade_title}`} v={a.p_grade_or_higher != null ? pct(a.p_grade_or_higher) : "—"} />
            <Row k="Верных ответов" v={a.answered ? `${a.correct} из ${a.answered}` : "—"} />
            {a.integrity && <Row k="Достоверность результата" v={INTEGRITY[a.integrity] ?? a.integrity} />}
            <Row k="Действителен до" v={dt(p.valid_until)} />
          </dl>
        )}
        <h3 className="mt-6 flex items-center gap-2 font-bold text-brand-night"><Lvl t="T1" /> Навыки, подтверждённые заданиями теста</h3>
        {p.skills_t1.length ? (
          <ul className="mt-2 flex flex-wrap gap-2">
            {p.skills_t1.map((x) => <li key={x.tag} className="chip">{x.title}{x.score != null ? ` · ${pct(x.score)}` : ""}</li>)}
          </ul>
        ) : <p className="mt-2 text-sm text-brand-ink/70">Отдельных навыков с результатом от 50 % нет.</p>}
        <h3 className="mt-6 flex items-center gap-2 font-bold text-brand-night"><Lvl t="T2" /> Достижения ФСП, подтверждённые реестром</h3>
        {p.achievements_t2.length ? (
          <ul className="mt-2 space-y-2 text-sm">
            {p.achievements_t2.map((x, i) => (
              <li key={i} className="rounded-xl bg-[#F3F2FB] px-3 py-2">
                <b className="text-brand-night">{x.result ? x.result[0].toUpperCase() + x.result.slice(1) : x.place ? `${x.place} место` : "Участник"}</b>: {x.event}
                <span className="block text-xs text-brand-ink/70">{x.discipline_title} · {x.level_title}{x.date ? ` · ${dt(x.date).replace(/ г\.$/, "")}` : ""} · источник: {x.source.demo ? "демо-реестр хакатона" : x.source.registry === "keycloak" ? "ФСП ID" : "реестр ФСП"}</span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-2 text-sm text-brand-ink/70">Нет или скрыты кандидатом. Отсутствие истории ФСП — нейтральное состояние.</p>}
      </section>

      <Signature d={d} />

      <section className="card text-sm">
        <h2 className="font-bold text-brand-night">Как получен грейд</h2>
        <p className="mt-2 text-brand-ink/80">Категорию присваивает только адаптивный тест платформы: задания банка подбираются под уровень кандидата, θ — оценка уровня по модели IRT, грейд подтверждается, если вероятность уровня не ниже заявленного достаточно высока. Самоописание (T0) в паспорт не входит. Сигналы античита только снижают «достоверность», автоматических наказаний нет.</p>
        <a className="mt-3 inline-block font-semibold text-brand underline-offset-4 hover:underline" href={p.methodology_url}>Методика и проверка качества теста</a>
      </section>
    </>
  );
}

function Signature({ d }: { d: PassportPublic }) {
  const p = d.passport;
  const input = useRef<HTMLInputElement>(null);
  const [check, setCheck] = useState<FileCheck | null>(null);
  const [err, setErr] = useState<string | null>(null);
  function download() {
    const blob = new Blob([JSON.stringify({ passport: d.passport, signature: d.signature, keys: d.keys }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = url; el.download = `passport-${p.id}.json`; document.body.appendChild(el); el.click(); el.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  async function onFile(f: File | undefined) {
    if (!f) return;
    setErr(null); setCheck(null);
    try {
      const doc = JSON.parse(await f.text());
      setCheck(await api<FileCheck>("/passport/verify", { body: { passport: doc.passport, signature: doc.signature }, auth: false }));
    } catch (e) { setErr(e instanceof SyntaxError ? "Файл не похож на паспорт: это не JSON" : errText(e)); }
    if (input.current) input.current.value = "";
  }
  return (
    <section className="card text-sm">
      <h2 className="font-bold text-brand-night">Подпись и проверка без нас</h2>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <Row k="Издатель" v={p.issuer.name} />
        <Row k="Алгоритм" v={`Ed25519 (${d.signature.alg})`} />
        <Row k="Ключ (kid)" v={<span className="break-all font-mono text-xs">{d.signature.kid}</span>} />
        <Row k="Выпущен" v={dtt(p.issued_at)} />
      </dl>
      <p className="mt-4 text-brand-ink/80">Подписан канонический JSON состава паспорта. Изменение любого поля — грейда, даты, навыка — делает подпись неверной. Проверить можно и без нашей базы данных, по открытому ключу:</p>
      <pre className="mt-2 overflow-x-auto rounded-xl bg-brand-night px-3 py-2 text-xs text-white"><code>python tools/passport/verify.py {window.location.origin}/verify/{p.id}</code></pre>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="btn-ghost" onClick={download}>Скачать файл паспорта</button>
        <button className="btn-ghost" onClick={() => input.current?.click()}>Проверить файл</button>
        <a className="btn-ghost" href="/api/passport/keys" target="_blank" rel="noreferrer">Открытые ключи</a>
        <input ref={input} type="file" accept="application/json,.json" className="sr-only" aria-label="Файл паспорта для проверки" onChange={(e) => void onFile(e.target.files?.[0])} />
      </div>
      <div className="mt-3" aria-live="polite">
        <Alert>{err}</Alert>
        {check && <Alert kind={check.state === "valid" ? "ok" : "error"}><b>{check.state === "valid" ? "Файл подлинный" : check.state === "invalid_signature" ? "Подпись не сходится" : "Файл не подтверждён"}.</b> {FILE_STATE[check.state] ?? ""}{check.registry?.reason_title ? ` Причина отзыва: ${check.registry.reason_title}.` : ""}</Alert>}
      </div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl bg-[#F7F6FB] px-3 py-2">
      <dt className="text-xs text-brand-ink/65">{k}</dt>
      <dd className="mt-0.5 font-semibold text-brand-night">{v}</dd>
    </div>
  );
}

function Lvl({ t }: { t: "T1" | "T2" }) {
  return <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-bold ${t === "T2" ? "bg-brand-night text-white" : "bg-[#E0004C] text-white"}`} title={t === "T2" ? "Подтверждено реестром ФСП" : "Подтверждено тестом на платформе"}>{t}</span>;
}
