// «Приложение и уведомления»: установка на главный экран (iPhone / Android / компьютер), пакет для RuStore и уведомления.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../components/CabinetLayout";
import { Logo } from "../components/Logo";
import { Alert, errText } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  canPromptInstall,
  currentSubscription,
  isInAppBrowser,
  isStandalone,
  onInstallChange,
  platform,
  promptInstall,
  pushSupported,
  subscribePush,
  unsubscribePush,
} from "./pwa";

interface RuStoreInfo {
  apk: string;
  package: string;
  version: string;
  size_mb: number;
  sha256: string;
  status: string;
}

interface TelegramStatus {
  configured: boolean;
  bot_username: string;
  linked: boolean;
  enabled: boolean;
  tg_username: string | null;
  tg_first_name: string | null;
  linked_at: string | null;
  last_sent_at: string | null;
  code: string | null;
  deep_link: string | null;
  code_expires_at: string | null;
  status_text: string;
}

function ShareIosIcon() {
  return (
    <svg viewBox="0 0 20 20" className="inline-block h-4 w-4 -translate-y-0.5 text-brand-plum" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M10 12.5V3m0 0L6.8 6.2M10 3l3.2 3.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.5 8.5H4.8A1.3 1.3 0 003.5 9.8v6.4a1.3 1.3 0 001.3 1.3h10.4a1.3 1.3 0 001.3-1.3V9.8a1.3 1.3 0 00-1.3-1.3h-.7" strokeLinecap="round" />
    </svg>
  );
}

function AddHomeIcon() {
  return (
    <svg viewBox="0 0 20 20" className="inline-block h-4 w-4 -translate-y-0.5 text-brand-plum" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="3.5" y="3.5" width="13" height="13" rx="2.5" />
      <path d="M10 6.8v6.4M6.8 10h6.4" strokeLinecap="round" />
    </svg>
  );
}

function InstallGuide() {
  const [, force] = useState(0);
  const [installNote, setInstallNote] = useState<string | null>(null);
  const [shaCopied, setShaCopied] = useState(false);
  const [rs, setRs] = useState<RuStoreInfo | null>(null);
  useEffect(() => onInstallChange(() => force((x) => x + 1)), []);
  useEffect(() => {
    fetch("/app/rustore.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setRs)
      .catch(() => setRs(null));
  }, []);

  const p = platform();
  const installed = isStandalone();
  const inApp = isInAppBrowser();

  async function onOneClick() {
    const res = await promptInstall();
    setInstallNote(
      res === "accepted"
        ? "Готово — значок «Драфт» добавлен на главный экран."
        : res === "dismissed"
          ? "Установка отменена. Вы можете повторить её в любой момент."
          : null,
    );
  }

  return (
    <section className="card space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-bold text-brand-night">Установить на главный экран</h2>
          <p className="text-sm text-brand-ink/65">
            Приложение открывается на весь экран без адресной строки, поддерживает быстрые ярлыки («Подборка», «Мой грейд», «Приглашения») и мгновенные уведомления.
          </p>
        </div>
        {installed ? (
          <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700">
            Установлено на устройстве
          </span>
        ) : canPromptInstall() ? (
          <button type="button" className="btn-primary min-h-[44px]" onClick={onOneClick} data-testid="install-guide-one-click">
            Установить в 1 клик
          </button>
        ) : null}
      </div>

      {installNote && <Alert kind="ok">{installNote}</Alert>}

      {inApp && (
        <Alert kind="info">
          Страница открыта во встроенном браузере мессенджера. Нажмите меню «⋯» в углу экрана и выберите «Открыть в Safari» (на iPhone) или «Открыть в браузере» (на Android), чтобы установить приложение.
        </Alert>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div className={`rounded-2xl border p-4 ${p === "ios" ? "border-brand/40 bg-brand-blush/20" : "border-brand-night/10"}`} data-testid="ios-install-guide">
          <div className="flex items-center justify-between gap-2">
            <p className="font-bold text-brand-night">iPhone и iPad (Safari)</p>
            <span className="rounded-full bg-brand-blush px-2.5 py-0.5 text-[11px] font-semibold text-brand-plum">4 шага</span>
          </div>
          <ol className="mt-3 space-y-2.5 text-sm text-brand-ink/85">
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">1</span>
              <span className="pt-0.5">Откройте <strong>fsp-draft.ru</strong> в штатном браузере Safari.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">2</span>
              <span className="pt-0.5">
                Нажмите кнопку <strong>«Поделиться»</strong> <ShareIosIcon /> на нижней панели Safari (на iPad — в правом верхнем углу).
              </span>
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">3</span>
              <span className="pt-0.5">
                Прокрутите список вниз, выберите <strong>«На экран „Домой“»</strong> <AddHomeIcon /> и нажмите <strong>«Добавить»</strong>.
              </span>
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">4</span>
              <span className="pt-0.5">
                Запустите «Драфт» со значка на экране «Домой» и включите уведомления ниже (доступно начиная с iOS 16.4).
              </span>
            </li>
          </ol>
        </div>

        <div className={`rounded-2xl border p-4 ${p === "android" ? "border-brand/40 bg-brand-blush/20" : "border-brand-night/10"}`} data-testid="android-install-guide">
          <div className="flex items-center justify-between gap-2">
            <p className="font-bold text-brand-night">Android (браузер или RuStore)</p>
            <span className="rounded-full bg-brand-blush px-2.5 py-0.5 text-[11px] font-semibold text-brand-plum">в 1 клик / APK</span>
          </div>
          <ol className="mt-3 space-y-2.5 text-sm text-brand-ink/85">
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">1</span>
              <span className="pt-0.5">Откройте <strong>fsp-draft.ru</strong> в Chrome или Яндекс Браузере.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">2</span>
              <span className="pt-0.5">Нажмите <strong>«Установить в 1 клик»</strong> выше или в меню браузера <strong>⋮ → «Установить приложение»</strong>.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">3</span>
              <span className="pt-0.5">Подтвердите установку — значок «Драфт» появится в списке приложений с быстрыми ярлыками по долгому нажатию.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">4</span>
              <span className="pt-0.5">Для телефонов без сервисов браузера используйте подписанный Android-пакет для RuStore ниже.</span>
            </li>
          </ol>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-bold text-brand-night">Android-пакет для RuStore</p>
              <p className="text-xs text-brand-ink/65">
                {rs ? `Пакет ${rs.package} · версия ${rs.version} · ${rs.size_mb} МБ` : "Подписанный установочный пакет Android"}
              </p>
            </div>
            {rs ? (
              <a
                href={rs.apk}
                download
                className="btn-primary inline-flex min-h-[44px] shrink-0 items-center !px-4 !py-2 text-sm"
                data-testid="install-page-rustore-apk"
              >
                Скачать APK
              </a>
            ) : null}
          </div>
          {rs && (
            <div className="mt-2 space-y-1.5 text-xs leading-relaxed text-brand-ink/65">
              <p>{rs.status}</p>
              <div className="flex flex-wrap items-center gap-2">
                <span>SHA-256: <code className="break-all text-[11px] text-brand-night">{rs.sha256}</code></span>
                <button
                  type="button"
                  className="btn-ghost min-h-[36px] !px-2.5 !py-1 text-[11px]"
                  onClick={() => {
                    navigator.clipboard?.writeText(rs.sha256).then(() => {
                      setShaCopied(true);
                      setTimeout(() => setShaCopied(false), 2000);
                    });
                  }}
                >
                  {shaCopied ? "Скопировано" : "Скопировать SHA-256"}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-4 rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4">
          <img src="/app/qr.svg" alt="QR-код для открытия «Драфт» на телефоне" className="h-24 w-24 shrink-0 rounded-xl bg-white p-1" />
          <div className="space-y-1 text-sm">
            <p className="font-bold text-brand-night">Открыть на телефоне</p>
            <p className="text-xs leading-relaxed text-brand-ink/70">
              Наведите камеру смартфона на QR-код, чтобы сразу открыть окно установки «Драфт» на телефоне.
            </p>
          </div>
        </div>
      </div>

      <p className="text-xs text-brand-ink/65">
        На компьютере (Chrome, Edge, Яндекс Браузер) приложение ставится через значок установки в правой части адресной строки или кнопку «Установить в 1 клик» выше.
      </p>
    </section>
  );
}

function PushCard() {
  const { me } = useAuth();
  const [on, setOn] = useState<boolean | null>(null);
  const [msg, setMsg] = useState<{ k: "ok" | "error" | "info"; t: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { currentSubscription().then((s) => setOn(!!s)).catch(() => setOn(false)); }, []);
  const role = me?.role === "employer" ? "employer" : "candidate";
  async function enable() {
    setBusy(true); setMsg(null);
    try { const r = await subscribePush(); setOn(r.ok); setMsg(r.ok ? { k: "ok", t: "Уведомления включены на этом устройстве." } : { k: "info", t: r.reason ?? "Не удалось включить" }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
    finally { setBusy(false); }
  }
  async function test() {
    setMsg(null);
    try { await api("/push/test", { method: "POST" }); setMsg({ k: "ok", t: "Тестовое уведомление отправлено." }); } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  return (
    <section className="card space-y-3">
      <h2 className="font-bold text-brand-night">Уведомления</h2>
      <p className="text-sm text-brand-ink/65">
        {role === "candidate"
          ? "Новое приглашение с вилкой зарплаты, сообщения от работодателя и изменения статуса ваших откликов."
          : "Кандидат принял приглашение, ответил в диалоге или откликнулся на вакансию."}
      </p>
      {!pushSupported() && (
        <Alert kind="info">
          В текущем режиме браузера уведомления недоступны. На iPhone сначала добавьте «Драфт» на экран «Домой» в Safari (iOS 16.4 и новее) и откройте приложение со значка.
        </Alert>
      )}
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <div className="flex flex-wrap gap-3">
        {on ? <>
          <button type="button" className="btn-primary min-h-[44px]" onClick={test}>Прислать тестовое</button>
          <button
            type="button"
            className="btn-ghost min-h-[44px]"
            onClick={async () => {
              await unsubscribePush();
              setOn(false);
              setMsg({ k: "info", t: "Уведомления на этом устройстве выключены." });
            }}
          >
            Выключить
          </button>
        </> : (
          <button type="button" className="btn-primary min-h-[44px]" disabled={busy || !pushSupported() || !me} onClick={enable}>
            {busy ? "Включаем…" : "Включить уведомления"}
          </button>
        )}
      </div>
    </section>
  );
}

/** Карточка привязки уведомлений в Telegram (по одноразовому коду deep-link, с кнопками «Открыть / Принять / Отклонить»). */
function TelegramCard() {
  const { me } = useAuth();
  const [st, setSt] = useState<TelegramStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [msg, setMsg] = useState<{ k: "ok" | "error" | "info"; t: string } | null>(null);

  useEffect(() => {
    if (!me) return;
    api<TelegramStatus>("/telegram/status")
      .then(setSt)
      .catch(() => setSt(null));
  }, [me]);

  async function onLink() {
    setBusy(true);
    setMsg(null);
    try {
      const next = await api<TelegramStatus>("/telegram/link", { method: "POST" });
      setSt(next);
      setMsg({
        k: "info",
        t: next.configured
          ? "Одноразовый код создан. Нажмите «Открыть бота в Telegram» и запустите бота кнопкой «Старт»."
          : "Одноразовый код привязки создан. Отправка заработает сразу после подключения токена бота на сервере.",
      });
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function onUnlink() {
    setBusy(true);
    setMsg(null);
    try {
      const next = await api<TelegramStatus>("/telegram/link", { method: "DELETE" });
      setSt(next);
      setMsg({ k: "info", t: "Уведомления в Telegram отключены." });
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function onTest() {
    setBusy(true);
    setMsg(null);
    try {
      await api("/telegram/test", { method: "POST" });
      setMsg({ k: "ok", t: "Проверочное уведомление отправлено в Telegram." });
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-3" data-testid="telegram-notify-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-bold text-brand-night">Уведомления в Telegram</h2>
          <p className="text-sm text-brand-ink/65">
            Приглашения с вилкой зарплаты и новые сообщения в диалогах приходят в Telegram с кнопками быстрого ответа («Открыть», «Принять», «Отклонить»).
          </p>
        </div>
        {st?.linked ? (
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
            Привязан {st.tg_username ? `@${st.tg_username}` : st.tg_first_name || "чат"}
          </span>
        ) : st && !st.configured ? (
          <span className="rounded-full bg-brand-blush/50 px-3 py-1 text-xs font-semibold text-brand-plum">
            Токен бота не задан на сервере
          </span>
        ) : null}
      </div>

      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}

      {st?.deep_link && st?.code && !st.linked && (
        <div className="rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm">
              <p className="font-bold text-brand-night">Одноразовый код привязки (действует 30 минут)</p>
              <p className="text-xs text-brand-ink/70">
                Перейдите в бота <strong>@{st.bot_username}</strong> по кнопке или отправьте ему команду ниже:
              </p>
            </div>
            <a
              href={st.deep_link}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary inline-flex min-h-[44px] items-center !px-4 !py-2 text-sm"
              data-testid="telegram-open-bot"
            >
              Открыть бота в Telegram
            </a>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <code className="rounded-xl bg-white px-3 py-2 text-xs font-bold text-brand-night ring-1 ring-brand-night/10">
              /start {st.code}
            </code>
            <button
              type="button"
              className="btn-ghost min-h-[44px] !px-3 !py-1.5 text-xs"
              onClick={() => {
                navigator.clipboard?.writeText(`/start ${st.code}`).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                });
              }}
            >
              {copied ? "Скопировано" : "Скопировать команду"}
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        {st?.linked ? (
          <>
            <button
              type="button"
              className="btn-primary min-h-[44px]"
              disabled={busy || !st.configured}
              onClick={onTest}
              data-testid="telegram-test-btn"
            >
              Прислать проверочное в Telegram
            </button>
            <button
              type="button"
              className="btn-ghost min-h-[44px]"
              disabled={busy}
              onClick={onUnlink}
              data-testid="telegram-unlink-btn"
            >
              Отключить Telegram
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn-primary min-h-[44px]"
            disabled={busy || !me}
            onClick={onLink}
            data-testid="telegram-link-btn"
          >
            {busy ? "Создаём код…" : st?.code ? "Обновить код привязки" : "Получать в Telegram"}
          </button>
        )}
      </div>
    </section>
  );
}

/** Раздел кабинета (кандидат и работодатель). */
export function AppSection() {
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle
        title="Приложение и уведомления"
        subtitle="Установите «Драфт» на главный экран телефона и включите мгновенные уведомления о приглашениях и откликах."
      />
      <PushCard />
      <TelegramCard />
      <InstallGuide />
    </div>
  );
}

/** Публичная страница /install. */
export function InstallPage() {
  const { me } = useAuth();
  return (
    <main id="main" className="min-h-screen bg-[#FBF8FC] px-4 py-8 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link to="/" className="inline-flex min-h-[44px] items-center"><Logo /></Link>
          <Link to="/" className="inline-flex min-h-[44px] items-center text-sm font-semibold text-brand-plum hover:underline">
            На главную
          </Link>
        </div>
        <PageTitle
          title="Приложение «Драфт»"
          subtitle="Установите платформу на iPhone или Android — в один клик из браузера или через пакет для RuStore."
        />
        <InstallGuide />
        {me ? (
          <>
            <PushCard />
            <TelegramCard />
          </>
        ) : (
          <Alert kind="info">
            Чтобы включить уведомления в браузере или в Telegram,{" "}
            <Link to="/login" className="font-semibold underline">
              войдите в личный кабинет
            </Link>
            .
          </Alert>
        )}
      </div>
    </main>
  );
}
