// Индекс доверия работодателя: бейдж (кратко) и панель с причинами (ЕГРЮЛ, почта, вилка, поведение).
import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, dateOnly, dt, errText, fmtHoursText, useApi } from "../components/ui";
import { api } from "../lib/api";
import { OriginTag, type Origin } from "../components/Origin";

export { dateOnly };

export interface TrustShort {
  score: number; level: "high" | "medium" | "low"; level_title: string; preliminary: boolean; critical: boolean;
  summary: string; offer_salary?: { status: string; text: string } | null; company_id?: string;
  origin?: Origin | null;  // Я8: сведения ФНС — модельные данные / реальный запрос / не проверено
  response_badge?: { median_hours: number; sample_size: number; label: string } | null;
}
export interface TrustFactor { id: string; title: string; status: "ok" | "warn" | "bad" | "unknown" | "neutral"; points: number; max: number; text: string }
export interface Trust extends TrustShort {
  company_id: string; company_name: string; factors: TrustFactor[];
  registry: { status: string; name?: string; ogrn?: string; registered_at?: string; liquidated_at?: string | null; director?: string; director_role?: string; checked_at?: string; error?: string | null; source?: string } | null;
  computed_at: string;
}

const LEVEL: Record<string, [string, string]> = {
  high: ["bg-emerald-50 text-emerald-800 ring-emerald-200", "bg-emerald-500"],
  medium: ["bg-amber-50 text-amber-800 ring-amber-200", "bg-amber-500"],
  low: ["bg-brand-blush/60 text-brand-plum ring-brand/30", "bg-brand"],
};
const FACTOR_ICON: Record<string, [string, string]> = {
  ok: ["✓", "text-emerald-600"], warn: ["!", "text-amber-600"], bad: ["✕", "text-brand"],
  unknown: ["?", "text-brand-ink/65"], neutral: ["·", "text-brand-ink/65"],
};

export function TrustBadge({ t, compact }: { t?: TrustShort | null; compact?: boolean }) {
  if (!t) return null;
  const [cls, dot] = LEVEL[t.level] ?? LEVEL.medium;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${cls}`}
        title={`Индекс доверия работодателя: ${t.score} из 100. ${t.summary}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
        {compact ? `Доверие ${t.score}` : `Доверие ${t.score}/100 · ${t.level_title}`}{t.preliminary ? " · предв." : ""}
      </span>
      {t.response_badge?.label && (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2.5 py-1 text-xs font-semibold text-sky-900 ring-1 ring-sky-200"
          title={`Медиана времени ответа компании по ${t.response_badge.sample_size} реальным приглашениям и откликам`}
          data-testid="company-response-badge"
        >
          ⏱ {fmtHoursText(t.response_badge.label)}
        </span>
      )}
    </span>
  );
}

function FactorRow({ f }: { f: TrustFactor }) {
  const [ic, c] = FACTOR_ICON[f.status] ?? FACTOR_ICON.neutral;
  return (
    <li className="flex items-start gap-3 text-sm">
      <span className={`mt-0.5 w-4 shrink-0 text-center font-bold ${c}`} aria-label={f.status}>{ic}</span>
      <span className="flex-1"><span className="font-semibold text-brand-night">{f.title}.</span> <span className="text-brand-ink/75">{fmtHoursText(f.text)}</span></span>
      <span className="shrink-0 tabular-nums text-xs text-brand-ink/65">{f.max ? `${Math.round(f.points)}/${f.max}` : f.points < 0 ? `−${Math.abs(Math.round(f.points))}` : "0"}</span>
    </li>
  );
}

/** brief (Ф6 В6, оффер у кандидата): на виду — итог, вилка, сведения ФНС, жалобы кандидатов и серьёзные замечания;
 *  остальные составляющие — по раскрытию. */
export function TrustPanel({ t, title = "Индекс доверия работодателя", companyLink, brief }: { t: Trust; title?: string; companyLink?: boolean; brief?: boolean }) {
  const [cls, dot] = LEVEL[t.level] ?? LEVEL.medium;
  const r = t.registry;
  // жалобы кандидатов — всегда на виду: это рычаг самого кандидата (кнопка «Пожаловаться» рядом), e2e 05
  const key = brief ? t.factors.filter((f) => f.id === "registry" || f.id === "complaints" || f.status === "bad") : t.factors;
  return (
    <section className="rounded-2xl border border-brand-night/10 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{title}{t.origin && <span className="normal-case tracking-normal">Сведения ФНС: <OriginTag o={t.origin} /></span>}</p>
          <p className="mt-1 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tabular-nums text-brand-night">{t.score}</span>
            <span className="text-sm text-brand-ink/65">из 100</span>
            <span className={`ml-1 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${cls}`}><span className={`h-1.5 w-1.5 rounded-full ${dot}`} />{t.level_title}</span>
          </p>
        </div>
        {companyLink && <Link to={`/candidate/companies/${t.company_id}`} className="text-sm font-semibold text-brand hover:underline">Профиль компании</Link>}
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-brand-night/10" aria-hidden><div className={`h-full ${dot}`} style={{ width: `${t.score}%` }} /></div>
      {t.preliminary && <p className="mt-2 text-xs text-brand-ink/65">Оценка предварительная: часть сведений не удалось проверить.</p>}
      {t.offer_salary && (
        <p className={`mt-3 rounded-lg px-3 py-2 text-sm ${t.offer_salary.status === "ok" ? "bg-emerald-50 text-emerald-800" : t.offer_salary.status === "warn" ? "bg-amber-50 text-amber-800" : "bg-[#F3F2FB] text-brand-night"}`}>
          <b>Вилка этого предложения:</b> {t.offer_salary.text}
        </p>
      )}
      {key.length > 0 && <ul className="mt-3 space-y-2">{key.map((f) => <FactorRow key={f.id} f={f} />)}</ul>}
      {brief && t.factors.length > key.length && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer font-semibold text-brand-plum">Остальные составляющие индекса: {t.factors.length - key.length} из {t.factors.length}</summary>
          <ul className="mt-2 space-y-2">{t.factors.filter((f) => !key.includes(f)).map((f) => <FactorRow key={f.id} f={f} />)}</ul>
        </details>
      )}
      {r && r.status === "found" && (
        <p className="mt-3 border-t border-brand-night/5 pt-3 text-xs text-brand-ink/65">
          ЕГРЮЛ (ФНС, egrul.nalog.ru): {r.name}{r.ogrn ? `, ОГРН ${r.ogrn}` : ""}{r.registered_at ? `, регистрация ${dateOnly(r.registered_at)}` : ""}{r.director ? `, ${r.director_role?.toLowerCase() ?? "руководитель"} ${r.director}` : ""}. Проверено {dt(r.checked_at).replace(/\.$/, "")}.
        </p>
      )}
    </section>
  );
}

/** Блок на странице «Профиль компании» у работодателя: проверка ИНН в ФНС и индекс доверия, как его видит кандидат. */
export function CompanyTrustCard({ hasInn }: { hasInn: boolean }) {
  const { data, loading, error, reload, setData } = useApi<Trust>("/employer/company/trust");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function check() {
    setBusy(true); setErr(null);
    try { setData(await api<Trust>("/employer/company/registry-check?force=true", { method: "POST" })); }
    catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  }
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-bold text-brand-night">Проверка в ФНС и индекс доверия</h2>
          <p className="text-sm text-brand-ink/65">Кандидат видит этот индекс в каждом приглашении и в профиле компании.</p>
        </div>
        <button className="btn-primary" onClick={check} disabled={busy || !hasInn}>{busy ? "Запрос в ФНС…" : "Проверить по ИНН"}</button>
      </div>
      {!hasInn && <Alert kind="info">Укажите ИНН компании и сохраните профиль — проверим в ЕГРЮЛ.</Alert>}
      <Alert>{err || error}</Alert>
      {loading && !data ? <div className="h-40 animate-pulse rounded-2xl bg-brand-blush/30" /> : data && <TrustPanel t={data} title="Так вас видит кандидат" />}
      {data && <button className="text-xs font-semibold text-brand-plum hover:text-brand" onClick={() => reload()}>Обновить</button>}
    </section>
  );
}

/** Индекс доверия в карточке приглашения у кандидата (с оценкой вилки этого предложения).
 * version — признак изменения приглашения (статус, ответ, жалоба): индекс перечитывается в открытом окне. */
export function InvitationTrust({ invitationId, version }: { invitationId: string; version?: string | number | null }) {
  const { data } = useApi<Trust>(`/candidate/invitations/${invitationId}/trust`, [invitationId, version ?? ""]);
  if (!data) return <div className="h-24 animate-pulse rounded-2xl bg-brand-blush/30" />;
  return <TrustPanel t={data} companyLink brief />;
}

/** Краткие индексы по всем приглашениям кандидата: { [invitation_id]: TrustShort }. */
export function useInvitationsTrust(version = 0) {
  return useApi<Record<string, TrustShort>>("/candidate/invitations-trust", [version]).data ?? {};
}
