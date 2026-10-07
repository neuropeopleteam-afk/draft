// Кабинет кандидата: «Поделиться паспортом» — QR, ссылка, отзыв и новая ссылка, история.
import { useState } from "react";
import { Alert, dt, errText, useApi } from "../components/ui";
import { api } from "../lib/api";
import { GRADE_STATUS, StateBadge, verifyHref, type PassportPublic, type PassportState } from "./common";

interface Owner {
  active: (PassportPublic & { id: string }) | null; eligible: boolean; opted_out: boolean;
  history: { id: string; category_id: string; grade_status: string; issued_at: string; valid_until: string; revoked_at: string | null; reason: string | null; reason_title: string | null }[];
}

export function PassportShare() {
  const { data, error, setData } = useApi<Owner>("/me/passport");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  if (error) return <section className="card"><Alert>{error}</Alert></section>;
  if (!data) return null;
  const a = data.active;
  async function act(path: string, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true); setErr(null);
    try { setData(await api<Owner>(path, { method: "POST" })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function copy(url: string) {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2500); } catch { setErr("Не удалось скопировать — выделите ссылку вручную"); }
  }
  const past = data.history.filter((h) => !a || h.id !== a.id).slice(0, 3);
  return (
    <section className="card" aria-labelledby="passport-share">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="passport-share" className="font-bold text-brand-night">Паспорт грейда</h2>
          <p className="mt-1 text-sm text-brand-ink/70">Подписанная электронной подписью платформы выписка: категория, навыки T1 и достижения ФСП T2. Без ФИО и контактов. Работодатель проверит её по ссылке или QR-коду без входа.</p>
        </div>
        {a && <StateBadge state={a.status.state as PassportState}>{a.status.title}</StateBadge>}
      </div>
      <Alert>{err}</Alert>
      {a ? (
        <div className="mt-4 grid gap-5 sm:grid-cols-[160px_1fr]">
          <img src={`/api/passport/${a.id}/qr.svg`} alt="QR-код ссылки на проверку паспорта" className="h-40 w-40 rounded-xl border border-brand-night/10 bg-white p-2" />
          <div className="min-w-0 space-y-3 text-sm">
            <p><b className="text-brand-night">{a.passport.category.title}</b> · {GRADE_STATUS[a.passport.grade_status]} · действителен до {dt(a.passport.valid_until)}</p>
            <p className="break-all rounded-xl bg-[#F7F6FB] px-3 py-2 font-mono text-xs text-brand-night">{verifyHref(a.id)}</p>
            <div className="flex flex-wrap gap-3">
              <button className="btn-primary" onClick={() => void copy(verifyHref(a.id))}>{copied ? "Ссылка скопирована" : "Поделиться паспортом"}</button>
              <a className="btn-ghost" href={`/verify/${a.id}`} target="_blank" rel="noreferrer">Открыть страницу проверки</a>
              <button className="btn-ghost" disabled={busy} onClick={() => void act("/me/passport/revoke", "Отозвать ссылку? Страница проверки по ней покажет «Отозван». Новую ссылку можно выпустить сразу.")}>Отозвать ссылку</button>
            </div>
            {a.status.test_key && <p className="text-xs text-brand-ink/65">Стенд подписывает тестовым ключом — страница проверки честно это показывает.</p>}
          </div>
        </div>
      ) : data.eligible ? (
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          <p className="text-brand-ink/75">{data.opted_out ? "Вы отозвали ссылку. Старая ссылка показывает «Отозван»." : "Паспорт ещё не выпущен."}</p>
          <button className="btn-primary" disabled={busy} onClick={() => void act("/me/passport/reissue")}>Выпустить новую ссылку</button>
        </div>
      ) : <p className="mt-4 text-sm text-brand-ink/70">Паспорт выпускается автоматически, когда тест присвоит категорию.</p>}
      {a && <button className="mt-3 text-xs font-semibold text-brand underline-offset-4 hover:underline" disabled={busy} onClick={() => void act("/me/passport/reissue", "Выпустить паспорт с новой ссылкой? Старая ссылка покажет «Отозван».")}>Выпустить с новой ссылкой</button>}
      {past.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-semibold text-brand-night">Прежние паспорта</summary>
          <ul className="mt-2 space-y-1 text-brand-ink/75">
            {past.map((h) => <li key={h.id} className="break-words">{dt(h.issued_at).replace(/ г\.$/, "")} · {h.category_id} · {h.revoked_at ? `отозван: ${h.reason_title ?? h.reason}` : "действует"}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}

/** Карточка у работодателя: ссылка на подписанный паспорт кандидата. */
export function PassportEmployerBadge({ refId }: { refId: string }) {
  const { data } = useApi<{ id: string; path: string; state: PassportState; title: string; grade_status: string; valid_until: string; test_key: boolean }>(`/employer/candidates/${refId}/passport`);
  if (!data) return null;
  return (
    <section className="card flex flex-wrap items-center justify-between gap-3 text-sm" aria-label="Подписанный паспорт грейда">
      <div className="min-w-0">
        <p className="font-bold text-brand-night">Подписанный паспорт грейда</p>
        <p className="mt-1 text-brand-ink/70">Категория, навыки T1 и достижения ФСП T2 подписаны платформой. Действителен до {dt(data.valid_until)}{data.test_key ? " · тестовый ключ стенда" : ""}.</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <StateBadge state={data.state}>{data.title}</StateBadge>
        <a className="btn-ghost" href={data.path} target="_blank" rel="noreferrer">Проверить паспорт</a>
      </div>
    </section>
  );
}
