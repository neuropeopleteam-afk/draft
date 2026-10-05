// «Приложение и уведомления»: установка PWA на главный экран (iPhone / Android / компьютер) и Web Push.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../components/CabinetLayout";
import { Logo } from "../components/Logo";
import { Alert, errText } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { canPromptInstall, currentSubscription, isStandalone, onInstallChange, platform, promptInstall, pushSupported, subscribePush, unsubscribePush } from "./pwa";

function Steps({ items }: { items: string[] }) {
  return <ol className="mt-3 space-y-2 text-sm">{items.map((s, i) => <li key={i} className="flex gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-blush text-xs font-bold text-brand-plum">{i + 1}</span><span className="pt-0.5 text-brand-ink/80">{s}</span></li>)}</ol>;
}

function InstallGuide() {
  const [, force] = useState(0);
  useEffect(() => onInstallChange(() => force((x) => x + 1)), []);
  const p = platform();
  const installed = isStandalone();
  return (
    <section className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-bold text-brand-night">Установить на главный экран</h2>
          <p className="text-sm text-brand-ink/60">Приложение открывается без адресной строки и присылает уведомления. Магазин приложений не нужен.</p>
        </div>
        {installed ? <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">Установлено</span>
          : canPromptInstall() ? <button className="btn-primary" onClick={() => promptInstall()}>Установить</button> : null}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className={`rounded-xl border p-4 ${p === "ios" ? "border-brand/40 bg-brand-blush/20" : "border-brand-night/10"}`}>
          <p className="font-semibold text-brand-night">iPhone и iPad (Safari)</p>
          <Steps items={["Откройте fsp.neuropeople.pro в Safari.", "Нажмите «Поделиться» (квадрат со стрелкой вверх).", "Выберите «На экран „Домой“» и подтвердите «Добавить».", "Откройте приложение с главного экрана и включите уведомления ниже (iOS 16.4 и новее)."]} />
        </div>
        <div className={`rounded-xl border p-4 ${p === "android" ? "border-brand/40 bg-brand-blush/20" : "border-brand-night/10"}`}>
          <p className="font-semibold text-brand-night">Android (Chrome, Яндекс Браузер)</p>
          <Steps items={["Откройте fsp.neuropeople.pro.", "Нажмите «Установить» на этой странице или в меню ⋮ → «Установить приложение» / «Добавить на главный экран».", "Подтвердите установку — значок появится среди приложений.", "Разрешите уведомления кнопкой ниже."]} />
        </div>
      </div>
      <p className="text-xs text-brand-ink/50">На компьютере (Chrome, Edge, Яндекс Браузер) — значок установки в адресной строке или кнопка «Установить» выше.</p>
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
      <p className="text-sm text-brand-ink/60">{role === "candidate" ? "Новое приглашение с вилкой зарплаты и изменения статуса ваших откликов." : "Кандидат принял приглашение, новый отклик на вакансию."}</p>
      {!pushSupported() && <Alert kind="info">Этот браузер не поддерживает Web Push. На iPhone сначала установите приложение на главный экран.</Alert>}
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <div className="flex flex-wrap gap-3">
        {on ? <>
          <button className="btn-primary" onClick={test}>Прислать тестовое</button>
          <button className="btn-ghost" onClick={async () => { await unsubscribePush(); setOn(false); setMsg({ k: "info", t: "Уведомления на этом устройстве выключены." }); }}>Выключить</button>
        </> : <button className="btn-primary" disabled={busy || !pushSupported() || !me} onClick={enable}>{busy ? "Включаем…" : "Включить уведомления"}</button>}
      </div>
    </section>
  );
}

/** Раздел кабинета (кандидат и работодатель). */
export function AppSection() {
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Приложение и уведомления" subtitle="Платформа работает как приложение (PWA): установка на главный экран и push-уведомления." />
      <PushCard />
      <InstallGuide />
    </div>
  );
}

/** Публичная страница /install. */
export function InstallPage() {
  const { me } = useAuth();
  return (
    <div className="min-h-screen bg-[#FBF8FC] px-6 py-10">
      <div className="mx-auto max-w-4xl space-y-6">
        <Link to="/"><Logo /></Link>
        <PageTitle title="Приложение «Встречный»" subtitle="Установите платформу на телефон как приложение — без магазина приложений." />
        <InstallGuide />
        {me ? <PushCard /> : <Alert kind="info">Чтобы включить уведомления, <Link to="/login" className="font-semibold underline">войдите</Link>.</Alert>}
      </div>
    </div>
  );
}
