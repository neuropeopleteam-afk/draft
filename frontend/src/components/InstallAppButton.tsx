// «На телефон / RuStore»: кнопка в шапке, подвале и на главной + окно установки в 1 клик.
// Android/компьютер — системный запрос установки на главный экран, iOS — «На экран „Домой“» в Safari,
// Android и RuStore — подписанный пакет APK, см. /app/rustore.json.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { canPromptInstall, isInAppBrowser, isStandalone, onInstallChange, platform, promptInstall } from "../integrations/pwa";

interface RuStoreInfo { apk: string; package: string; version: string; size_mb: number; min_android?: string; sha256: string; status: string }

export function PhoneIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="6.5" y="2.5" width="11" height="19" rx="2.5" /><path d="M10.5 18.5h3" strokeLinecap="round" />
    </svg>
  );
}

function useRuStore() {
  const [info, setInfo] = useState<RuStoreInfo | null>(null);
  useEffect(() => { fetch("/app/rustore.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).then(setInfo).catch(() => setInfo(null)); }, []);
  return info;
}

export function AndroidBetaDialog({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const rs = useRuStore();
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center bg-brand-night/60 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="android-beta-title"
        data-testid="install-dialog"
        className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-white p-5 text-brand-ink shadow-2xl outline-none sm:rounded-3xl sm:p-6"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <img src="/icons/icon-192.png" alt="" className="h-12 w-12 rounded-2xl" />
            <div>
              <h2 id="android-beta-title" className="text-lg font-extrabold text-brand-night">Бета-версия приложения</h2>
              <p className="font-mono text-xs text-brand-ink/65">
                {rs ? `Версия ${rs.version} · ${String(rs.size_mb).replace(".", ",")} МБ · Android ${rs.min_android ?? "7.0"} и новее` : "Загружаем параметры пакета…"}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-brand-ink/60 hover:bg-brand-blush/40"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" /></svg>
          </button>
        </div>

        <p className="mt-4 text-sm leading-relaxed text-brand-ink/85" data-testid="android-beta-text">
          Это ранняя версия приложения «Драфт» для Android: внутри — тот же сайт, все функции работают так же. Возможны недочёты в оформлении и уведомлениях. Приложение подписано командой «Драфта», в RuStore пока не опубликовано — телефон попросит разрешить установку из этого источника.
        </p>

        <div className="mt-4 rounded-2xl border border-brand-night/10 bg-[#F4F6FC] px-4 py-3 text-xs text-brand-ink/75" data-testid="android-beta-meta">
          {rs ? `Пакет ${rs.package} · ${String(rs.size_mb).replace(".", ",")} МБ · Android ${rs.min_android ?? "7.0"} и новее` : "Версия … · … МБ · Android … и новее"}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost min-h-[44px] px-4 py-2.5 text-sm"
            data-testid="android-beta-cancel"
          >
            Отмена
          </button>
          <a
            href={rs?.apk ?? "/app/draft-rustore.apk"}
            download
            className="btn-primary inline-flex min-h-[44px] items-center px-5 py-2.5 text-sm"
            data-testid="rustore-apk"
          >
            Скачать бета-версию
          </a>
        </div>
      </div>
    </div>
  );
}

export function AndroidBetaButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="landing-android-apk-btn"
        aria-haspopup="dialog"
        className="np-btn-ghost inline-flex items-center gap-2 px-4 py-2.5 text-xs font-bold sm:text-sm"
      >
        <PhoneIcon className="h-4 w-4 text-[#A59DFF]" />
        <span>Скачать приложение для Android</span>
      </button>
      {open && createPortal(<AndroidBetaDialog onClose={() => setOpen(false)} />, document.body)}
    </>
  );
}

export function InstallDialog({ onClose }: { onClose: () => void }) {
  const [, force] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const rs = useRuStore();
  useEffect(() => onInstallChange(() => force((x) => x + 1)), []);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);
  const p = platform();
  if (p === "android") {
    return <AndroidBetaDialog onClose={onClose} />;
  }
  const installed = isStandalone();
  const inApp = isInAppBrowser();
  async function one() {
    const r = await promptInstall();
    setMsg(r === "accepted" ? "Готово — значок «Драфт» появился на главном экране." : r === "dismissed" ? "Установка отменена. Можно повторить в любой момент." : null);
  }
  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-brand-night/50 p-0 sm:items-center sm:p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="install-title" data-testid="install-dialog"
        className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-white p-5 text-brand-ink shadow-2xl outline-none sm:rounded-3xl sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <img src="/icons/icon-192.png" alt="" className="h-12 w-12 rounded-2xl" />
            <div>
              <h2 id="install-title" className="text-lg font-extrabold text-brand-night">«Драфт» на телефоне</h2>
              <p className="text-sm text-brand-ink/65">iPhone и APK для Android · бесплатно</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-brand-ink/60 hover:bg-brand-blush/40"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" /></svg>
          </button>
        </div>

        <div className="mt-5 space-y-3">
          {inApp && (
            <p className="rounded-2xl border border-amber-300 bg-amber-50 p-3.5 text-xs leading-relaxed text-amber-950">
              Вы открыли ссылку внутри мессенджера. Нажмите «⋯» и выберите «Открыть в Safari / браузере», чтобы установить приложение на главный экран.
            </p>
          )}
          {installed ? (
            <p className="rounded-2xl bg-emerald-50 p-4 text-sm font-semibold text-emerald-800">Приложение уже установлено и открыто с главного экрана.</p>
          ) : canPromptInstall() ? (
            <button type="button" onClick={one} className="btn-primary min-h-[48px] w-full !py-3.5 text-base" data-testid="install-one-click">Установить в 1 клик</button>
          ) : p === "ios" ? (
            <div className="rounded-2xl border border-brand/30 bg-brand-blush/20 p-4 text-sm">
              <p className="font-semibold text-brand-night">iPhone и iPad — 3 касания в Safari</p>
              <ol className="mt-2 list-decimal space-y-1.5 pl-5">
                <li>Нажмите <strong>«Поделиться»</strong> <span aria-hidden="true">(квадрат со стрелкой вверх)</span> на панели Safari.</li>
                <li>Выберите в списке <strong>«На экран „Домой“»</strong>.</li>
                <li>Нажмите <strong>«Добавить»</strong> — «Драфт» откроется на весь экран и сможет присылать уведомления (iOS 16.4+).</li>
              </ol>
            </div>
          ) : (
            <div className="rounded-2xl border border-brand-night/10 p-4 text-sm">
              <p className="font-semibold text-brand-night">Компьютер — Chrome, Edge или Яндекс Браузер</p>
              <p className="mt-1 text-brand-ink/75">Значок установки в адресной строке или меню браузера → «Установить Драфт». На телефон — отсканируйте QR-код.</p>
            </div>
          )}
          {msg && <p className="text-sm font-semibold text-emerald-700" aria-live="polite">{msg}</p>}

          <div className="rounded-2xl border border-brand-night/10 p-4" id="rustore">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-semibold text-brand-night">Бета-версия приложения для Android</p>
                <p className="text-xs text-brand-ink/65">{rs ? `Версия ${rs.version} · ${rs.size_mb} МБ · Android ${rs.min_android ?? "7.0"} и новее` : "загрузка параметров пакета…"}</p>
              </div>
              {rs ? <a href={rs.apk} download className="btn-primary inline-flex min-h-[44px] shrink-0 items-center !px-4 !py-2 text-sm" data-testid="rustore-apk">Скачать APK</a>
                : <span className="shrink-0 text-xs text-brand-ink/60">готовится</span>}
            </div>
            {rs && <p className="mt-2 text-[11px] leading-relaxed text-brand-ink/60">{rs.status}</p>}
          </div>

          {p === "desktop" && (
            <div className="flex items-center gap-4 rounded-2xl border border-brand-night/10 p-4">
              <img src="/app/qr.svg" alt="QR-код: открыть «Драфт» на телефоне" className="h-28 w-28 shrink-0 rounded-lg bg-white" />
              <p className="text-sm text-brand-ink/75">Наведите камеру телефона на код — откроется эта страница с кнопкой установки.</p>
            </div>
          )}
          <p className="text-center text-xs">
            <Link to="/install" onClick={onClose} className="inline-flex min-h-[44px] items-center font-semibold text-brand-plum hover:underline">
              Подробная инструкция и уведомления
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

/** Кнопка «На телефон / RuStore»: variant="header" — компактная в шапке/подвале, "hero" — крупная на главной. */
export function InstallAppButton({ variant = "header", premium = false }: { variant?: "header" | "hero"; premium?: boolean }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { if (new URLSearchParams(window.location.search).get("install") === "1") setOpen(true); }, []);
  if (variant === "header" && isStandalone()) return null;
  const cls = variant === "hero"
    ? `${premium ? "np-btn-ghost" : "btn-ghost"} inline-flex min-h-[44px] items-center gap-2 px-6 py-3.5 text-base`
    : `inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 whitespace-nowrap rounded-xl px-2.5 py-2 text-sm font-semibold ring-1 transition-colors ${premium ? "np-install" : "text-brand-plum ring-brand-night/15 hover:bg-brand-blush/40"}`;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={cls} data-testid={variant === "hero" ? "install-hero" : "install-header"} aria-haspopup="dialog" title="Установить «Драфт» на телефон (iOS, APK для Android)">
        <PhoneIcon className={variant === "hero" ? "h-5 w-5" : "h-4 w-4"} />
        {variant === "hero" ? <span>На телефон / APK для Android</span> : <><span className="hidden flex-col text-left leading-none sm:flex"><span className="text-[13px]">На телефон</span><span className="mt-0.5 text-[10px] font-semibold opacity-85">iOS · APK для Android</span></span><span className="sr-only sm:hidden">На телефон / APK для Android</span></>}
      </button>
      {/* портал в body: у стеклянной шапки backdrop-filter, иначе fixed-окно привязывается к шапке */}
      {open && createPortal(<InstallDialog onClose={() => setOpen(false)} />, document.body)}
    </>
  );
}
