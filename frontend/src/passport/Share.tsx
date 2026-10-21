// Кабинет кандидата: «Поделиться паспортом» — QR, ссылка, отзыв и новая ссылка, история.
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Alert, dt, errText, useApi } from "../components/ui";
import { api } from "../lib/api";
import { GRADE_STATUS, StateBadge, verifyHref, type PassportPublic, type PassportState } from "./common";

interface Owner {
  active: (PassportPublic & { id: string }) | null; eligible: boolean; opted_out: boolean;
  /** FIX7 п. 6: почему грейд в паспорте «предварительный» (тот же источник, что статус на экране «Категория»). */
  preliminary_reason?: string | null;
  history: { id: string; category_id: string; grade_status: string; issued_at: string; valid_until: string; revoked_at: string | null; reason: string | null; reason_title: string | null }[];
}

export function PassportShare() {
  const { data, error, setData } = useApi<Owner>("/me/passport");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const box = useRef<HTMLElement>(null);
  const { hash } = useLocation();
  // /candidate/category#passport (шаг проводника жюри «Паспорт грейда») — прокрутить к блоку, когда он загрузится
  useEffect(() => { if (hash === "#passport" && data) box.current?.scrollIntoView({ block: "start", behavior: "smooth" }); }, [hash, !!data]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <section className="card"><Alert>{error}</Alert></section>;
  if (!data) return null;
  const a = data.active;
  async function act(path: string, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true); setErr(null);
    try { setData(await api<Owner>(path, { method: "POST" })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  // на телефоне — системное меню «Поделиться» (мессенджер, почта), на компьютере — ссылка в буфер обмена
  async function share(url: string) {
    if (typeof navigator.share === "function" && window.matchMedia("(pointer: coarse)").matches) {
      try { await navigator.share({ title: "Паспорт грейда · Драфт", url }); return; } catch (e) { if ((e as DOMException).name === "AbortError") return; }
    }
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2500); } catch { setErr("Не удалось скопировать — выделите ссылку вручную"); }
  }
  const past = data.history.filter((h) => !a || h.id !== a.id).slice(0, 3);
  return (
    <section ref={box} id="passport" className="card scroll-mt-24" aria-labelledby="passport-share">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="passport-share" className="font-bold text-brand-night">Паспорт грейда</h2>
          <p className="mt-1 text-sm text-brand-ink/70">Подписанная электронной подписью платформы выписка: категория, подтверждённые тестом навыки и достижения ФСП из реестра. Без ФИО и контактов. Работодатель проверит её по ссылке или QR-коду без входа.</p>
        </div>
        {a && <StateBadge state={a.status.state as PassportState}>{a.status.title}</StateBadge>}
      </div>
      <Alert>{err}</Alert>
      {a ? (
        <div className="mt-4 grid gap-5 sm:grid-cols-[160px_1fr]">
          <img src={`/api/passport/${a.id}/qr.svg`} alt="QR-код ссылки на проверку паспорта" className="h-40 w-40 rounded-xl border border-brand-night/10 bg-white p-2" />
          <div className="min-w-0 space-y-3 text-sm">
            <p><b className="text-brand-night">{a.passport.category.title}</b> · {GRADE_STATUS[a.passport.grade_status]} · действителен до {dt(a.passport.valid_until)}</p>
            {a.passport.grade_status === "preliminary" && data.preliminary_reason && (
              <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-950 ring-1 ring-amber-200" data-testid="passport-preliminary-reason">{data.preliminary_reason}</p>
            )}
            <p className="break-all rounded-xl bg-[#F7F6FB] px-3 py-2 font-mono text-xs text-brand-night">{verifyHref(a.id)}</p>
            <div className="flex flex-wrap gap-3">
              <button className="btn-primary" onClick={() => void share(verifyHref(a.id))}>{copied ? "Ссылка скопирована" : "Поделиться паспортом"}</button>
              <a className="btn-ghost" href={`/verify/${a.id}`} target="_blank" rel="noreferrer">Открыть страницу проверки</a>
              <button className="btn-ghost" disabled={busy} onClick={() => void act("/me/passport/revoke", "Отозвать ссылку? Страница проверки по ней покажет «Отозван». Новую ссылку можно выпустить сразу.")}>Отозвать ссылку</button>
            </div>
            <p className="text-xs text-brand-ink/65" data-testid="passport-kid" title="Как устроено: асимметричная цифровая подпись Ed25519 по открытому ключу JWKS">Цифровая подпись платформы · ключ <span className="break-all font-mono">{a.signature.kid}</span> · проверяется любым по открытому ключу</p>
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
        <p className="mt-1 text-brand-ink/70">Категория, подтверждённые тестом навыки и достижения ФСП из реестра подписаны платформой. Действителен до {dt(data.valid_until)}{data.test_key ? " · тестовый ключ стенда" : ""}.</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <StateBadge state={data.state}>{data.title}</StateBadge>
        <a className="btn-ghost" href={data.path} target="_blank" rel="noreferrer">Проверить паспорт</a>
      </div>
    </section>
  );
}

export interface PassportBrief { id: string; path: string; state: PassportState; title: string; grade_status: string; valid_until: string; test_key: boolean; kid?: string }

const CHIP_TEXT: Record<PassportState, string> = { valid: "действует", revoked: "отозван", expired: "истёк", invalid_signature: "подпись не сходится" };

/** KF1: компактный значок криптопаспорта для таблиц работодателя (сравнение кандидатов): «Паспорт Ed25519: действует». */
export function PassportCryptoChip({ refId }: { refId: string }) {
  const [d, setD] = useState<PassportBrief | null | undefined>(undefined);
  useEffect(() => {
    let on = true;
    api<PassportBrief>(`/employer/candidates/${encodeURIComponent(refId)}/passport`).then((v) => { if (on) setD(v); }).catch(() => { if (on) setD(null); });
    return () => { on = false; };
  }, [refId]);
  if (d === undefined) return <span className="text-xs text-brand-ink/50">Паспорт: проверяем…</span>;
  if (d === null) return <span className="text-xs text-brand-ink/55" title="Кандидат не выпустил подписанный паспорт или отозвал ссылку">Цифровой паспорт: нет</span>;
  const dot: Record<PassportState, string> = { valid: "bg-emerald-600", revoked: "bg-brand", expired: "bg-amber-500", invalid_signature: "bg-brand" };
  return (
    <a href={d.path} target="_blank" rel="noreferrer" data-testid="passport-crypto-chip"
      title={`Открыть проверку цифровой подписи${d.kid ? ` · ключ ${d.kid}` : ""}${d.test_key ? " · тестовый ключ стенда" : ""}`}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold hover:underline ${d.state === "valid" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-brand/30 bg-brand-blush/40 text-brand-plum"}`}>
      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" /></svg>
      <span className={`h-1.5 w-1.5 rounded-full ${dot[d.state]}`} aria-hidden="true" />
      Цифровой паспорт: {CHIP_TEXT[d.state] ?? d.title.toLowerCase()}
    </a>
  );
}
