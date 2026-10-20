// Публичная проверка паспорта грейда /verify/:id — без входа и без пароля стенда (infra/nginx/…passport.conf).
// KF1 «Паспорт-щит»: верхний блок криптостатуса, три ключевых факта, достижения ФСП T2, офлайн-проверка
// (JSON паспорта + открытый ключ JWKS) и проверка подписи Ed25519 прямо в браузере — без обращения к серверу.
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Alert, Loading, NB, dt, dtt, errText, num, pct } from "../components/ui";
import { api } from "../lib/api";
import { GRADE_STATUS, INTEGRITY, STATE_HINT, STATE_STYLE, StateBadge, type PassportClaims, type PassportPublic } from "./common";

interface FileCheck { state: string; signature_valid: boolean; kid_known: boolean; matches_registry: boolean; registry: { title: string; reason_title: string | null } | null }

const FILE_STATE: Record<string, string> = {
  valid: "Подпись верна, паспорт совпадает с реестром и действителен.",
  revoked: "Подпись верна, но паспорт отозван.",
  expired: "Подпись верна, но срок паспорта истёк.",
  invalid_signature: "Подпись не сходится: файл изменён или подписан не нашим ключом.",
  differs: "Подпись верна, но файл отличается от записи реестра.",
  not_in_registry: "Подпись верна, но паспорта с таким id в реестре нет.",
};

// паспорт заменён автоматически (пересдача, обновление данных, экспертная проверка) — кандидат не скомпрометирован
const REPLACED = new Set(["superseded", "reviewed"]);

export default function PassportVerify() {
  const { id = "" } = useParams();
  const [d, setD] = useState<PassportPublic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  useEffect(() => {
    document.title = "Проверка паспорта грейда · Драфт";
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
      <main id="main" className="mx-auto max-w-3xl space-y-6 px-4 py-8 sm:px-6">
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

/** Открытый ключ JWKS по стандартному адресу (за прокси /api — тот же ответ, что /.well-known/jwks.json). */
const JWKS_HREF = "/api/.well-known/jwks.json";

function b64uBytes(s: string): Uint8Array<ArrayBuffer> {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

/** Проверка подписи Ed25519 в браузере (WebCrypto) по уже полученным данным: запросов к серверу нет.
 *  null — браузер не умеет Ed25519 (старый Safari/Chrome): тогда — файл + tools/passport/verify.py. */
async function verifyInBrowser(d: PassportPublic): Promise<boolean | null> {
  const jwk = d.keys.find((k) => k.kid === d.signature.kid) as { x?: string } | undefined;
  if (!jwk?.x || !globalThis.crypto?.subtle) return null;
  try {
    const key = await crypto.subtle.importKey("jwk", { kty: "OKP", crv: "Ed25519", x: jwk.x, ext: true }, { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, b64uBytes(d.signature.value), new TextEncoder().encode(d.document));
  } catch { return null; }
}

/** θ с 95 % доверительным интервалом: θ ± 1,96·SE. */
function thetaCi(a: PassportClaims["assessment"]) {
  if (!a || a.theta == null) return "—";
  if (a.se == null) return num(a.theta);
  return `${num(a.theta)} [${num(a.theta - 1.96 * a.se)}; ${num(a.theta + 1.96 * a.se)}]`;
}

function CryptoShield({ d }: { d: PassportPublic }) {
  const p = d.passport;
  const s = d.status;
  const [local, setLocal] = useState<boolean | null | undefined>(undefined);
  useEffect(() => { let on = true; void verifyInBrowser(d).then((v) => { if (on) setLocal(v); }); return () => { on = false; }; }, [d]);
  const ok = s.signature_valid && local !== false;
  return (
    <section data-testid="passport-shield" aria-label="Криптографический статус"
      className={`overflow-hidden rounded-2xl p-5 text-white shadow-lg sm:p-6 ${!ok ? "bg-gradient-to-br from-[#E0004C] to-brand-plum" : s.state === "valid" ? "bg-gradient-to-br from-emerald-600 to-emerald-800" : "bg-gradient-to-br from-brand-night to-brand-plum"}`}>
      <div className="flex items-start gap-4">
        <svg viewBox="0 0 24 24" className="h-12 w-12 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" />{ok ? <path d="M8.5 12l2.5 2.5 4.5-5" /> : <path d="M9 9l6 6M15 9l-6 6" />}
        </svg>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/80">Паспорт-щит · криптографическая проверка</p>
          <p className="mt-1 text-2xl font-extrabold leading-tight sm:text-3xl">{ok ? "Подпись сходится" : "Подпись не сходится"}</p>
          <p className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-sm font-semibold text-white/95">
            <span>Ed25519</span><span className="hidden sm:inline" aria-hidden="true">·</span>
            <span className="break-all font-mono text-xs leading-5">ключ {d.signature.kid}</span><span className="hidden sm:inline" aria-hidden="true">·</span>
            <span>0 обращений к серверу при офлайн-проверке</span>
          </p>
          <p className="mt-2 text-xs text-white/85" aria-live="polite">
            {local === undefined ? "Проверяем подпись в вашем браузере…"
              : local === true ? "Подпись проверена в вашем браузере по открытому ключу JWKS (WebCrypto) — без запроса к серверу."
              : local === false ? "Браузер пересчитал подпись по открытому ключу — она не совпала с документом."
              : "Ваш браузер не умеет Ed25519 — проверьте файл офлайн: tools/passport/verify.py или любая библиотека Ed25519."}
            {" "}Статус в реестре: <b>{s.title.toLowerCase()}</b>.
          </p>
        </div>
      </div>
      <dl className="mt-5 grid gap-2 sm:grid-cols-3" data-testid="passport-key-facts">
        <Fact k="Грейд" v={`${p.category.grade_title}${p.grade_status === "confirmed" ? "" : " (предв.)"}`} />
        <Fact k="Направление" v={p.category.direction_title} />
        <Fact k="θ, 95 % ДИ" v={thetaCi(p.assessment)} />
      </dl>
      <div className="mt-3 rounded-xl bg-white/15 px-3 py-2 text-sm" data-testid="passport-t2">
        <span className="mr-2 rounded-md bg-white px-1.5 py-0.5 text-[11px] font-bold text-brand-night">T2</span>
        {p.achievements_t2.length
          ? <>Достижения ФСП из реестра: <b>{p.achievements_t2.length}</b> — {p.achievements_t2.slice(0, 2).map((x) => x.event).join("; ")}{p.achievements_t2.length > 2 ? "…" : ""}</>
          : "Достижений ФСП в паспорте нет или они скрыты кандидатом (без штрафа)."}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <a className="inline-flex items-center rounded-xl bg-white px-4 py-2 text-sm font-bold text-brand-night hover:bg-white/90" href={`/api/passport/${encodeURIComponent(p.id)}/offline.json`} download={`passport-${p.id}.json`} data-testid="passport-offline">
          Проверить офлайн: скачать JSON + открытый ключ JWKS
        </a>
        <a className="inline-flex items-center rounded-xl border border-white/60 px-4 py-2 text-sm font-semibold text-white hover:bg-white/10" href={JWKS_HREF} target="_blank" rel="noreferrer">/.well-known/jwks.json</a>
      </div>
      <p className="mt-4 rounded-xl bg-black/15 px-3 py-2 text-xs leading-relaxed text-white/90">
        <b>Как это устроено:</b> HMAC-токен может проверить только выдавший сервер; асимметричную подпись Ed25519 проверяет любой по открытому ключу JWKS.
        Работодателю не нужно доверять нашему серверу: достаточно файла паспорта и открытого ключа.
      </p>
    </section>
  );
}

function Fact({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl bg-white/15 px-3 py-2">
      <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-white/75">{k}</dt>
      <dd className="mt-0.5 text-lg font-extrabold leading-tight">{v}</dd>
    </div>
  );
}

function Body({ d }: { d: PassportPublic }) {
  const p = d.passport;
  const s = d.status;
  const a = p.assessment;
  return (
    <>
      <CryptoShield d={d} />
      <section role="status" aria-live="polite" className={`rounded-2xl border p-5 sm:p-6 ${STATE_STYLE[s.state]}`}>
        <p className="text-xs font-semibold uppercase tracking-[0.12em] opacity-75">Статус паспорта</p>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">{s.title}</h1>
        <p className="mt-2 text-sm">{STATE_HINT[s.state]}{s.reason_title ? ` Причина: ${s.reason_title}${s.revoked_at ? `, ${dt(s.revoked_at).replace(/ г\.$/, "")}` : ""}.` : ""}{s.state === "revoked" && REPLACED.has(s.reason ?? "") ? " Актуальный паспорт кандидат пришлёт новой ссылкой: старая ссылка на новый паспорт не ведёт." : ""}</p>
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
            {a.p_grade_or_higher != null && <Row k={`Вероятность уровня не ниже ${p.category.grade_title}`} v={probText(a.p_grade_or_higher)} />}
            <Row k="Верных ответов" v={a.answered ? `${a.correct} из ${a.answered}` : "—"} />
            {a.integrity && <Row k="Достоверность результата" v={INTEGRITY[a.integrity] ?? a.integrity} />}
            <Row k="Действителен до" v={dt(p.valid_until)} />
          </dl>
        )}
        <h3 className="mt-6 flex items-center gap-2 font-bold text-brand-night"><Lvl t="T1" /> Навыки, подтверждённые заданиями (T1)</h3>
        {/* FIX7 п. 11 / Я4-15: сюда входят и задания теста, и задания работодателя — подпись не сужает источник до «теста» */}
        <p className="mt-1 text-xs text-brand-ink/70" data-testid="passport-skills-source">Задания теста платформы и задания работодателя с автопроверкой; навык считается подтверждённым от 50 % верных.</p>
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
        ) : <p className="mt-2 text-sm text-brand-ink/70">Нет или скрыты кандидатом. Нет истории ФСП — без штрафа; подтверждённые достижения ФСП дают бонус.</p>}
      </section>

      <Signature d={d} />

      <section className="card text-sm">
        <h2 className="font-bold text-brand-night">Как получен грейд</h2>
        <p className="mt-2 text-brand-ink/80">Категорию присваивает только адаптивный тест платформы: задания банка подбираются под уровень кандидата, θ — оценка уровня по модели IRT, грейд подтверждается, если вероятность уровня не ниже заявленного достаточно высока. Самоописание (T0) в паспорт не входит. Признаки несамостоятельного прохождения только снижают «достоверность результата», автоматических наказаний нет.</p>
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
      <pre className="mt-2 whitespace-pre-wrap break-all rounded-xl bg-brand-night px-3 py-2 text-xs text-white"><code>python tools/passport/verify.py {window.location.origin}/verify/{p.id}</code></pre>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="btn-ghost" onClick={download}>Скачать файл паспорта</button>
        <button className="btn-ghost" onClick={() => input.current?.click()}>Проверить файл</button>
        <a className="btn-ghost" href={JWKS_HREF} target="_blank" rel="noreferrer">Открытые ключи (JWKS)</a>
        <input ref={input} type="file" accept="application/json,.json" className="sr-only" aria-label="Файл паспорта для проверки" onChange={(e) => void onFile(e.target.files?.[0])} />
      </div>
      <div className="mt-3" aria-live="polite">
        <Alert>{err}</Alert>
        {check && <Alert kind={check.state === "valid" ? "ok" : "error"}><b>{check.state === "valid" ? "Файл подлинный" : check.state === "invalid_signature" ? "Подпись не сходится" : "Файл не подтверждён"}.</b> {FILE_STATE[check.state] ?? ""}{check.registry?.reason_title ? ` Причина отзыва: ${check.registry.reason_title}.` : ""}</Alert>}
      </div>
    </section>
  );
}

/** Вероятность без ложной точности: 0,999 — «более 99 %», а не «100 %» (уверенность теста не абсолютна). */
function probText(v: number | null) {
  if (v == null) return "—";
  if (v >= 0.995) return `более 99${NB}%`;
  if (v <= 0.005) return `менее 1${NB}%`;
  return pct(v);
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
