import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { AuthShell, FormError } from "../components/AuthShell";
import { PageTitle } from "../components/CabinetLayout";
import { Alert, Field, Loading, Modal, dt, dtt, errText, useApi } from "../components/ui";
import { api, type TokenOut } from "../lib/api";
import { useAuth } from "../lib/auth";
import { scenario } from "../lib/jury";
import { useDemoUi } from "../lib/juryMode";
import { useProductName } from "../lib/meta";
import { downloadCodes, pending } from "../lib/twofa";

/* Второй фактор входа (TOTP, RFC 6238): подключение приложения-аутентификатора по QR, резервные коды, ввод кода при
   входе, перевыпуск и отключение с подтверждением, сброс администратором. Тексты — честные: что проверяется и как. */

interface Status {
  enabled: boolean; required: boolean; pending_setup: boolean; rotation_pending: boolean; confirmed_at: string | null;
  last_verified_at: string | null; recovery_codes_left: number; recovery_codes_total: number; locked_until: string | null;
  method: string; params: { algorithm: string; digits: number; period_s: number; window_steps: number };
  can_disable: boolean; is_demo: boolean; demo_note: string | null;
}
interface Setup { secret: string; secret_grouped: string; otpauth_uri: string; qr_svg: string; issuer: string; account: string; rotation: boolean }
interface Confirm { enabled: boolean; recovery_codes: string[]; token: TokenOut | null }

const ROLE: Record<string, string> = { admin: "администратор", fsp_analyst: "аналитик ФСП", expert: "эксперт", candidate: "кандидат", employer: "работодатель" };

/* ------------------------------------------------------------------ ввод кода */
function CodeInput({ value, onChange, id = "otp", label = "Код из приложения", hint, autoFocus }: { value: string; onChange: (v: string) => void; id?: string; label?: string; hint?: string; autoFocus?: boolean }) {
  return (
    <Field label={label} htmlFor={id} hint={hint ?? "6 цифр из приложения-аутентификатора или резервный код вида XXXX-XXXX"}>
      <input id={id} className="input font-mono text-lg tracking-[0.2em]" value={value} onChange={(e) => onChange(e.target.value)}
        inputMode="text" autoComplete="one-time-code" autoCapitalize="characters" spellCheck={false} maxLength={16} autoFocus={autoFocus} placeholder="123 456" />
    </Field>
  );
}

const codeReady = (v: string) => v.replace(/[\s-]/g, "").length >= 6;

/* ------------------------------------------------------------------ подключение: QR → первый код */
function EnrollWizard({ token, rotationCode, onDone, onCancel }: { token?: string; rotationCode?: string; onDone: (c: Confirm) => void; onCancel?: () => void }) {
  const [setup, setSetup] = useState<Setup | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api<Setup>("/auth/2fa/setup", { body: rotationCode ? { code: rotationCode } : {}, token }).then(setSetup).catch((e) => setErr(errText(e)));
  }, [token, rotationCode]);

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { onDone(await api<Confirm>("/auth/2fa/confirm", { body: { code }, token })); }
    catch (x) { setErr(errText(x)); setCode(""); }
    finally { setBusy(false); }
  }
  if (err && !setup) return <Alert>{err}</Alert>;
  if (!setup) return <Loading text="Готовим QR-код" />;
  const svgSrc = `data:image/svg+xml;utf8,${encodeURIComponent(setup.qr_svg)}`;
  return (
    <form onSubmit={confirm} className="space-y-5" noValidate>
      <ol className="space-y-5 text-sm text-brand-ink/85">
        <li className="flex gap-3">
          <Step n={1} />
          <div>
            <p className="font-semibold text-brand-night">Откройте приложение одноразовых кодов</p>
            <p className="mt-0.5 leading-relaxed" title="Как устроено: стандарт одноразовых кодов по времени TOTP (RFC 6238)">Подойдёт любое мобильное приложение двухэтапной защиты (например, «Яндекс Ключ» или другое стандартное приложение кодов по времени). Если на телефоне его ещё нет — установите из магазина приложений.</p>
          </div>
        </li>
        <li className="flex gap-3">
          <Step n={2} />
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-brand-night">Отсканируйте QR-код{setup.rotation ? " нового ключа" : ""}</p>
            <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start">
              <img src={svgSrc} alt="QR-код для приложения-аутентификатора" className="h-44 w-44 shrink-0 rounded-xl border border-brand-night/10 bg-white" data-testid="twofa-qr" />
              <div className="min-w-0 space-y-2">
                <a href={setup.otpauth_uri} className="btn-ghost w-full sm:hidden">Открыть в приложении на этом телефоне</a>
                <button type="button" className="text-left text-sm font-semibold text-brand hover:text-brand-soft" onClick={() => setManual((v) => !v)} aria-expanded={manual}>
                  {manual ? "Скрыть ключ для ручного ввода" : "Не сканируется — ввести ключ вручную"}
                </button>
                {manual && (
                  <div className="rounded-xl bg-[#F3F2FB] p-3 text-xs leading-relaxed text-brand-ink/80">
                    <p>Учётная запись: <span className="break-all font-semibold text-brand-night">{setup.account}</span></p>
                    <p className="mt-1">Ключ: <code className="break-all font-mono text-sm font-bold tracking-wider text-brand-night" data-testid="twofa-secret">{setup.secret_grouped}</code></p>
                    <p className="mt-1" title="Как устроено: TOTP RFC 6238, SHA1, 6 цифр, 30 секунд">Тип — по времени, 6 цифр, смена каждые 30 секунд. Издатель: {setup.issuer}.</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </li>
        <li className="flex gap-3">
          <Step n={3} />
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-brand-night">Введите код, который показывает приложение</p>
            <div className="mt-3 max-w-xs">
              <CodeInput value={code} onChange={setCode} label="Первый код" hint="Так мы убеждаемся, что приложение настроено верно. Код меняется каждые 30 секунд." autoFocus />
            </div>
          </div>
        </li>
      </ol>
      <FormError message={err} />
      <div className="flex flex-wrap gap-3">
        <button type="submit" className="btn-primary" disabled={busy || !codeReady(code)}>{busy ? "Проверяем…" : setup.rotation ? "Подтвердить новый ключ" : "Подключить"}</button>
        {onCancel && <button type="button" className="btn-ghost" onClick={onCancel}>Отмена</button>}
      </div>
    </form>
  );
}

const Step = ({ n }: { n: number }) => <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-night text-xs font-bold text-white" aria-hidden="true">{n}</span>;

/* ------------------------------------------------------------------ резервные коды: показываются один раз */
function RecoveryCodes({ codes, account, onDone, doneLabel = "Готово" }: { codes: string[]; account: string; onDone: () => void; doneLabel?: string }) {
  const product = useProductName();
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(codes.join("\n")); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* буфер недоступен — есть файл */ }
  }
  return (
    <div className="space-y-4">
      <Alert kind="info">Сохраните резервные коды сейчас — больше они не будут показаны. Каждый код входит один раз, если телефон с приложением недоступен. Храните их отдельно от пароля.</Alert>
      <ul className="grid grid-cols-2 gap-2 rounded-xl bg-[#F3F2FB] p-4 font-mono text-sm font-bold tracking-wider text-brand-night sm:grid-cols-5" aria-label="Резервные коды" data-testid="twofa-recovery">
        {codes.map((c) => <li key={c} className="rounded-lg bg-white px-2 py-1.5 text-center">{c}</li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" onClick={copy}>{copied ? "Скопировано" : "Скопировать"}</button>
        <button type="button" className="btn-ghost" onClick={() => downloadCodes(codes, account, product || "Драфт")}>Скачать файлом</button>
      </div>
      <label className="flex items-start gap-2 text-sm text-brand-ink/85">
        <input type="checkbox" className="mt-0.5" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>Я сохранил резервные коды в надёжном месте</span>
      </label>
      <button type="button" className="btn-primary" disabled={!saved} onClick={onDone}>{doneLabel}</button>
    </div>
  );
}

/* ------------------------------------------------------------------ подтверждение действия кодом */
function CodeModal({ open, title, text, cta, danger, onClose, onSubmit }: { open: boolean; title: string; text: ReactNode; cta: string; danger?: boolean; onClose: () => void; onSubmit: (code: string) => Promise<void> }) {
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setCode(""); setErr(null); } }, [open]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await onSubmit(code); } catch (x) { setErr(errText(x)); } finally { setBusy(false); }
  }
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="text-sm leading-relaxed text-brand-ink/80">{text}</div>
        <CodeInput value={code} onChange={setCode} id="confirm-otp" autoFocus />
        <FormError message={err} />
        <div className="flex flex-wrap gap-3">
          <button type="submit" className={danger ? "btn bg-brand-night text-white hover:bg-brand-plum" : "btn-primary"} disabled={busy || !codeReady(code)}>{busy ? "Проверяем…" : cta}</button>
          <button type="button" className="btn-ghost" onClick={onClose}>Отмена</button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ страница кабинета «Безопасность входа» */
export function TwoFactorSettings() {
  const { me } = useAuth();
  const demoUi = useDemoUi();
  const { data: st, error, loading, reload } = useApi<Status>("/auth/2fa");
  const [mode, setMode] = useState<"view" | "enroll" | "codes">("view");
  const [rotationCode, setRotationCode] = useState<string | undefined>();
  const [codes, setCodes] = useState<string[]>([]);
  const [modal, setModal] = useState<null | "rotate" | "recovery" | "disable">(null);
  const [check, setCheck] = useState("");
  const [checkMsg, setCheckMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const [checkBusy, setCheckBusy] = useState(false);

  if (loading && !st) return <Loading />;
  if (error || !st) return <Alert>{error ?? "Не удалось загрузить состояние"}</Alert>;
  const roleName = ROLE[me?.role ?? ""] ?? me?.role ?? "";

  // подтверждение прошло: показываем резервные коды (один раз), состояние уже «включён» — обновляем, не дожидаясь «Готово»
  function done(c: Confirm) { setCodes(c.recovery_codes); setMode("codes"); void reload(); }
  async function doCheck(e: FormEvent) {
    e.preventDefault();
    setCheckBusy(true); setCheckMsg(null);
    try {
      const r = await api<{ ok: boolean; method: string }>("/auth/2fa/check", { body: { code: check } });
      setCheckMsg({ k: "ok", t: r.method === "totp" ? "Код верный. Этот же код второй раз сервер не примет — попробуйте." : "Резервный код принят и погашен." });
      setCheck(""); void reload();
    } catch (x) { setCheckMsg({ k: "error", t: errText(x) }); }
    finally { setCheckBusy(false); }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <PageTitle title="Безопасность входа" subtitle="Это раздел двухэтапной защиты: подключите одноразовые коды в приложении на телефоне и сохраните резервные коды доступа." />
      {demoUi && st.demo_note && <Alert kind="info">{st.demo_note}</Alert>}

      <section className="card space-y-4" aria-labelledby="twofa-state">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-bold ${st.enabled ? "bg-emerald-50 text-emerald-700" : "bg-brand-blush text-brand-plum"}`} data-testid="twofa-state">
            {st.enabled ? "Второй фактор включён" : "Второй фактор не подключён"}
          </span>
          {st.required && <span className="chip" title="Политика платформы: для этой роли с реальной учётной записью второй фактор обязателен">Обязателен для роли «{roleName}»</span>}
          {st.locked_until && <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-600">Ввод кода заблокирован до {dtt(st.locked_until)}</span>}
        </div>
        <h2 id="twofa-state" className="sr-only">Состояние второго фактора</h2>

        {mode === "codes" ? (
          <RecoveryCodes codes={codes} account={me?.email ?? ""} onDone={() => { setMode("view"); setRotationCode(undefined); void reload(); }} />
        ) : mode === "enroll" ? (
          <EnrollWizard rotationCode={rotationCode} onDone={done} onCancel={() => { setMode("view"); setRotationCode(undefined); }} />
        ) : !st.enabled ? (
          <>
            <p className="text-sm leading-relaxed text-brand-ink/80">
              Пароль можно подсмотреть или подобрать; код из приложения меняется каждые 30 секунд и не покидает телефон. Подключение занимает минуту: QR-код, первый код для проверки и 10 резервных кодов на случай потери телефона.
            </p>
            {st.pending_setup && <Alert kind="info">Подключение было начато, но первый код не подтверждён. Начните заново — будет выпущен новый ключ.</Alert>}
            <button className="btn-primary" onClick={() => setMode("enroll")} data-testid="twofa-enable">Подключить приложение-аутентификатор</button>
          </>
        ) : (
          <>
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div><dt className="text-xs uppercase tracking-[0.12em] text-brand-lavender">Подключён</dt><dd className="mt-1 font-semibold text-brand-night">{dt(st.confirmed_at)}</dd></div>
              <div><dt className="text-xs uppercase tracking-[0.12em] text-brand-lavender">Последняя проверка</dt><dd className="mt-1 font-semibold text-brand-night">{st.last_verified_at ? dtt(st.last_verified_at) : "—"}</dd></div>
              <div><dt className="text-xs uppercase tracking-[0.12em] text-brand-lavender">Резервных кодов</dt><dd className="mt-1 font-semibold tabular-nums text-brand-night" data-testid="twofa-recovery-left">{st.recovery_codes_left} из {st.recovery_codes_total}</dd></div>
            </dl>
            {st.recovery_codes_left <= 2 && <Alert kind="info">Резервных кодов почти не осталось — выпустите новые, пока телефон под рукой.</Alert>}
            {st.rotation_pending && <Alert kind="info">Перевыпуск начат: новый ключ ещё не подтверждён, действует прежний.</Alert>}

            <form onSubmit={doCheck} className="rounded-xl border border-brand-night/10 p-4" noValidate>
              <p className="text-sm font-semibold text-brand-night">Проверить код</p>
              <p className="mt-0.5 text-xs leading-relaxed text-brand-ink/65">Та же проверка, что при входе: окно ±1 шаг по 30 секунд, повтор уже принятого кода отклоняется, после {5} неверных подряд — пауза 15 минут.</p>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
                <div className="sm:max-w-xs sm:flex-1"><CodeInput value={check} onChange={setCheck} id="check-otp" hint="" /></div>
                <button type="submit" className="btn-ghost" disabled={checkBusy || !codeReady(check)} data-testid="twofa-check">{checkBusy ? "Проверяем…" : "Проверить"}</button>
              </div>
              {checkMsg && <div className="mt-3"><Alert kind={checkMsg.k}>{checkMsg.t}</Alert></div>}
            </form>

            <div className="flex flex-wrap gap-2">
              <button className="btn-ghost" onClick={() => setModal("rotate")}>Перевыпустить ключ</button>
              <button className="btn-ghost" onClick={() => setModal("recovery")}>Новые резервные коды</button>
              <button className="btn-ghost" onClick={() => setModal("disable")} disabled={!st.can_disable}
                title={st.can_disable ? undefined : "Для вашей роли второй фактор обязателен: его можно только перевыпустить. Сброс при потере телефона — через администратора"} data-testid="twofa-disable">
                Отключить
              </button>
            </div>
            {!st.can_disable && <p className="text-xs leading-relaxed text-brand-ink/65">Для роли «{roleName}» второй фактор обязателен: отключить нельзя, можно перевыпустить ключ. Если телефон потерян и резервных кодов нет — второй фактор сбрасывает администратор, после чего вход потребует подключить приложение заново.</p>}
          </>
        )}
      </section>

      <CodeModal open={modal === "rotate"} onClose={() => setModal(null)} title="Перевыпустить ключ" cta="Продолжить"
        text="Новый QR-код для нового телефона или приложения. Прежний ключ действует, пока вы не подтвердите новый первым кодом. Резервные коды будут выпущены заново."
        onSubmit={async (code) => { setRotationCode(code); setModal(null); setMode("enroll"); }} />
      <CodeModal open={modal === "recovery"} onClose={() => setModal(null)} title="Новые резервные коды" cta="Выпустить"
        text="Прежние резервные коды перестанут действовать. Подтвердите кодом из приложения."
        onSubmit={async (code) => { const r = await api<Confirm>("/auth/2fa/recovery-codes", { body: { code } }); setModal(null); done(r); }} />
      <CodeModal open={modal === "disable"} onClose={() => setModal(null)} title="Отключить второй фактор" cta="Отключить" danger
        text={<>Вход снова будет только по паролю{me?.role === "expert" ? " или персональной ссылке" : ""}. Резервные коды будут удалены. Подтвердите кодом из приложения или резервным кодом.</>}
        onSubmit={async (code) => { await api("/auth/2fa/disable", { body: { code } }); setModal(null); setCheckMsg(null); await reload(); }} />

      {me?.role === "admin" && <AdminReset />}

      <section className="card text-sm leading-relaxed text-brand-ink/80">
        <h2 className="font-bold text-brand-night">Как это устроено</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li title="Как считается: стандарт TOTP (RFC 6238), алгоритм хеширования по времени">Стандарт одноразовых кодов по времени: {st.params.digits} цифр, обновление каждые {st.params.period_s} с, допуск ±{st.params.window_steps} шаг на рассинхронизацию часов. Работает с любым приложением двухэтапной защиты, без СМС и без интернета на телефоне.</li>
          <li>Секрет хранится в базе зашифрованным и после подключения сервером не выдаётся; резервные коды — только хешами, каждый гасится после использования.</li>
          <li>Повтор уже принятого кода отклоняется; после 5 неверных кодов подряд — пауза 15 минут; промежуточный токен после пароля живёт 5 минут и в кабинет не пускает.</li>
          <li>Для администратора и аналитика ФСП с реальной учётной записью второй фактор обязателен: без него после пароля открывается только подключение. Эксперт панели входит по персональной ссылке и подключает код по желанию. Демо-учётки жюри — без второго фактора, с пометкой.</li>
          <li>Ограничение: доверенных устройств («не спрашивать 30 дней») нет — код нужен при каждом входе; восстановление без телефона — резервный код или администратор.</li>
        </ul>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ администратор: кому подключено, сброс */
interface AdminRow { email: string; role: string; is_demo: boolean; enabled: boolean; confirmed_at: string | null; recovery_codes_left: number; locked_until: string | null; required: boolean }
function AdminReset() {
  const { data, error, loading, reload } = useApi<{ items: AdminRow[]; required_roles: string[] }>("/admin/2fa/users");
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmFor, setConfirmFor] = useState<string | null>(null);
  async function reset(target: string) {
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ email: string; required: boolean }>("/admin/2fa/reset", { body: { email: target } });
      setMsg({ k: "ok", t: `Второй фактор у ${r.email} снят, все сеансы отозваны.${r.required ? " При следующем входе платформа потребует подключить приложение заново." : ""}` });
      setEmail(""); setConfirmFor(null); void reload();
    } catch (e) { setMsg({ k: "error", t: errText(e) }); setConfirmFor(null); }
    finally { setBusy(false); }
  }
  return (
    <section className="card space-y-4" aria-labelledby="twofa-admin">
      <div>
        <h2 id="twofa-admin" className="font-bold text-brand-night">Администратор: сброс второго фактора</h2>
        <p className="mt-1 text-sm leading-relaxed text-brand-ink/70">Пользователь потерял телефон и резервные коды — снимите второй фактор по почте. Подключение удаляется, все его сеансы отзываются; для обязательных ролей следующий вход начнётся с подключения приложения.</p>
      </div>
      <form onSubmit={(e) => { e.preventDefault(); setConfirmFor(email.trim()); }} className="flex flex-col gap-2 sm:flex-row sm:items-end" noValidate>
        <div className="sm:max-w-sm sm:flex-1"><Field label="Почта пользователя" htmlFor="reset-email"><input id="reset-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@example.com" /></Field></div>
        <button type="submit" className="btn-ghost" disabled={busy || !email.includes("@")} data-testid="twofa-admin-reset">Сбросить второй фактор</button>
      </form>
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : data && (
        <div className="overflow-x-auto">
          <p className="mb-2 text-xs text-brand-ink/65">Подключено или начато: {data.items.length}. Обязателен для ролей: {data.required_roles.map((r) => ROLE[r] ?? r).join(", ")}.</p>
          {data.items.length === 0 ? <p className="text-sm text-brand-ink/70">Пока ни у кого не подключён.</p> : (
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wider text-brand-ink/65"><tr><th className="py-2 pr-3">Почта</th><th className="pr-3">Роль</th><th className="pr-3">Состояние</th><th className="pr-3">Резервных</th><th></th></tr></thead>
              <tbody className="divide-y divide-brand-night/5">
                {data.items.map((r) => (
                  <tr key={r.email}>
                    <td className="py-2 pr-3 font-medium text-brand-night"><span className="block max-w-[14rem] truncate" title={r.email}>{r.email}</span></td>
                    <td className="whitespace-nowrap pr-3">{ROLE[r.role] ?? r.role}{r.is_demo ? " · демо" : ""}</td>
                    <td className="whitespace-nowrap pr-3">{r.enabled ? `включён ${dt(r.confirmed_at)}` : "не завершено"}{r.locked_until ? " · заблокирован" : ""}</td>
                    <td className="pr-3 tabular-nums">{r.enabled ? r.recovery_codes_left : "—"}</td>
                    <td className="whitespace-nowrap py-1 text-right"><button className="rounded-lg px-2 py-1 text-xs font-semibold text-brand-plum hover:bg-brand-blush/50" onClick={() => setConfirmFor(r.email)} disabled={busy}>Сбросить</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      <Modal open={!!confirmFor} onClose={() => setConfirmFor(null)} title="Сбросить второй фактор">
        <p className="text-sm leading-relaxed text-brand-ink/80">Снять второй фактор у <b className="break-all">{confirmFor}</b>? Подключение и резервные коды будут удалены, все сеансы пользователя завершены. Действие нельзя отменить — только подключить заново.</p>
        <div className="mt-4 flex flex-wrap gap-3">
          <button className="btn bg-brand-night text-white hover:bg-brand-plum" disabled={busy} onClick={() => confirmFor && reset(confirmFor)} data-testid="twofa-admin-reset-confirm">{busy ? "Сбрасываем…" : "Да, сбросить"}</button>
          <button className="btn-ghost" onClick={() => setConfirmFor(null)}>Отмена</button>
        </div>
      </Modal>
    </section>
  );
}

/* ------------------------------------------------------------------ экран входа: код или обязательное подключение */
export function TwoFactorLogin() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [ch] = useState(() => pending.get());
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState(0);
  const [codes, setCodes] = useState<{ list: string[]; token: TokenOut } | null>(null);

  useEffect(() => {
    if (!ch) return;
    const tick = () => setLeft(Math.max(0, Math.round((ch.started_at + ch.expires_in * 1000 - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [ch]);

  if (!ch) return <Navigate to="/login" replace />;

  async function finish(token: TokenOut, extra?: { scenario?: string | null }) {
    pending.clear();
    if (extra?.scenario) scenario.set(extra.scenario);  // песочница жюри — как при входе в один клик
    await signIn(token.access_token);
    navigate(ch!.next || ch!.landing || "/", { replace: true });
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await api<TokenOut & { scenario?: string | null }>("/auth/2fa/verify", { auth: false, body: { pending_token: ch!.pending_token, code } });
      await finish(r, r);
    } catch (x) { setErr(errText(x)); setCode(""); }
    finally { setBusy(false); }
  }
  const expired = left <= 0;
  const mm = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;

  if (ch.setup_required) {
    return (
      <AuthShell title="Подключите второй фактор" subtitle={`Для роли «${ROLE[ch.role] ?? ch.role}» вход без приложения-аутентификатора закрыт. Это займёт минуту — учётная запись ${ch.email}.`}
        footer={<Link to="/login" onClick={() => pending.clear()} className="font-semibold text-brand hover:text-brand-soft">Войти под другой учётной записью</Link>}>
        {codes ? (
          <RecoveryCodes codes={codes.list} account={ch.email} doneLabel="Войти в кабинет" onDone={() => finish(codes.token)} />
        ) : expired ? (
          <Alert>Время на подключение вышло — <Link to="/login" className="font-semibold underline" onClick={() => pending.clear()}>введите пароль ещё раз</Link>.</Alert>
        ) : (
          <>
            <EnrollWizard token={ch.pending_token} onDone={(c) => { if (c.token) setCodes({ list: c.recovery_codes, token: c.token }); }} />
            <p className="mt-4 text-xs text-brand-ink/65">На подключение осталось {mm}.</p>
          </>
        )}
      </AuthShell>
    );
  }
  return (
    <AuthShell title="Код из приложения" subtitle={`Пароль принят. Введите код из приложения-аутентификатора для ${ch.email}${ch.persona ? " (демо-учётка жюри с включённым вторым фактором)" : ""}.`}
      footer={<Link to="/login" onClick={() => pending.clear()} className="font-semibold text-brand hover:text-brand-soft">Войти под другой учётной записью</Link>}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <CodeInput value={code} onChange={setCode} autoFocus hint="6 цифр из приложения. Нет телефона под рукой — введите один из резервных кодов вида XXXX-XXXX." />
        <FormError message={expired ? "Время вышло — введите пароль ещё раз" : err} />
        <button type="submit" className="btn-primary w-full" disabled={busy || expired || !codeReady(code)} data-testid="twofa-login-submit">{busy ? "Проверяем…" : "Войти"}</button>
        <p className="text-center text-xs text-brand-ink/65" aria-live="polite">{expired ? <Link to="/login" className="font-semibold underline" onClick={() => pending.clear()}>К вводу пароля</Link> : `Код можно ввести в течение ${mm}`}</p>
      </form>
      {ch.persona && <p className="mt-5 rounded-lg bg-brand-blush/40 px-3 py-2 text-xs leading-relaxed text-brand-ink/80">
        Это ваша демо-песочница: второй фактор здесь включили вы. Потеряли код — «Вернуть демо-данные» во вкладке <Link to="/demo" className="font-semibold text-brand hover:text-brand-soft">«Демо для жюри»</Link> пересоздаст учётки без него.
      </p>}
    </AuthShell>
  );
}
