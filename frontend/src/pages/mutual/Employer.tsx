// Взаимный подбор в подборке работодателя (Н9), отзывы «подходит / не подходит» (Н2), ссылка руководителю (Н3)
// и подсказка в форме приглашения. Порядок подборки по умолчанию — match-v1; другой порядок — только по выбору.
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Field, Modal, Seg, dtt, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { FitBadge, FitFactors, type Fit } from "./shared";

const REASONS = [
  { id: "skill", title: "навык" }, { id: "grade", title: "грейд" }, { id: "format", title: "формат" },
  { id: "salary", title: "зарплата" }, { id: "other", title: "другое" },
] as const;
type Reason = (typeof REASONS)[number]["id"];
type Order = "match" | "mutual";

export interface MutualData {
  version: number; items: Record<string, Fit>; mutual_order: string[]; counts: Record<string, number>; note: string;
  feedback: Record<string, { verdict: "fit" | "unfit"; reason: Reason | null; reason_title: string | null; comment: string | null; version: number }>;
  reactions: Record<string, { verdict: "interesting" | "no"; verdict_title: string; comment: string | null; author: string | null; share_label: string | null; updated_at: string }[]>;
}

/** Данные взаимного подбора для версии и выбранный порядок (в адресе: ?order=mutual). */
export function useMutual(needId?: string, version?: number) {
  const m = useApi<MutualData>(needId && version ? `/employer/needs/${needId}/selections/${version}/mutual` : null, [needId, version]);
  const [sp, setSp] = useSearchParams();
  const order: Order = sp.get("order") === "mutual" ? "mutual" : "match";
  const setOrder = (o: Order) => { const n = new URLSearchParams(sp); if (o === "mutual") n.set("order", "mutual"); else n.delete("order"); setSp(n, { replace: true }); };
  /** Результаты в выбранном порядке; по умолчанию — без изменений (match-v1). */
  function sorted<T extends { ref: string }>(results: T[]): T[] {
    if (order !== "mutual" || !m.data) return results;
    const pos = new Map(m.data.mutual_order.map((r, i) => [r, i]));
    return [...results].sort((a, b) => (pos.get(a.ref) ?? 1e6) - (pos.get(b.ref) ?? 1e6));
  }
  return { ...m, order, setOrder, sorted };
}

export function MutualToolbar({ needId, version, mutual }: { needId: string; version: number; mutual: ReturnType<typeof useMutual> }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [share, setShare] = useState(false);
  const d = mutual.data;
  const unfit = d ? Object.values(d.feedback).filter((f) => f.verdict === "unfit").length : 0;
  const reacts = d ? Object.values(d.reactions).reduce((n, x) => n + x.length, 0) : 0;
  async function refine() {
    setErr(null); setBusy(true);
    try {
      const r = await api<any>(`/employer/needs/${needId}/selections/${version}/refine`, { method: "POST" });
      navigate(`/employer/needs/${needId}/v/${r.version}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <section className="card space-y-3" aria-label="Взаимный подбор">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-brand-night">Подходит ли предложение кандидатам</h2>
          {d && <p className="mt-0.5 text-xs text-brand-ink/65">подходит: {d.counts.high ?? 0} · частично: {d.counts.medium ?? 0} · вероятно, откажет: {d.counts.low ?? 0} · мало данных: {d.counts.unknown ?? 0}</p>}
        </div>
        <Seg<Order> label="Порядок кандидатов" value={mutual.order} onChange={mutual.setOrder}
          options={[{ id: "match", title: "По подбору" }, { id: "mutual", title: "С учётом интереса кандидата" }]} />
      </div>
      <p className="text-xs text-brand-ink/65">{mutual.order === "mutual"
        ? "Внутри яруса статуса грейда: сначала «подходит», затем «частично» и «мало данных», в конце «вероятно, откажет»; при равенстве — прежнее место. Скор и версия подборки не меняются."
        : "Порядок подбора (match-v1) — по подтверждённым фактам. Индикатор взаимности — самоописание кандидата (T0) и условия предложения, в скор не входит."}</p>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-ghost !py-2" disabled={busy || !unfit} onClick={refine}
          title={unfit ? "Новая версия без отмеченных «не подходит»; причины — в фильтры. Прежняя версия сохранится." : "Отметьте кандидатов «не подходит»"}>
          {busy ? "Пересчитываем…" : `Уточнить по отзывам (${unfit})`}
        </button>
        <button className="btn-ghost !py-2" onClick={() => setShare(true)}>Ссылка руководителю{reacts ? ` · отметок: ${reacts}` : ""}</button>
      </div>
      <Alert>{err || mutual.error}</Alert>
      <ShareModal open={share} onClose={() => { setShare(false); mutual.reload(); }} needId={needId} version={version} />
    </section>
  );
}

/** Блок в карточке кандидата: индикатор + строка объяснения, отзыв, «ещё похожих», отметки руководителя. */
export function MutualCardBlock({ needId, version, cref, mutual }: { needId: string; version: number; cref: string; mutual: ReturnType<typeof useMutual> }) {
  const navigate = useNavigate();
  const fit = mutual.data?.items[cref];
  const fb = mutual.data?.feedback[cref];
  const reacts = mutual.data?.reactions[cref] ?? [];
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"none" | "unfit">("none");
  const [reason, setReason] = useState<Reason | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function save(verdict: "fit" | "unfit") {
    setErr(null); setBusy(true);
    try {
      await api(`/employer/needs/${needId}/feedback`, { method: "PUT", body: { ref: cref, version, verdict, reason: verdict === "unfit" ? reason : null, comment: comment || null } });
      setMode("none"); await mutual.reload();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function clear() {
    setBusy(true);
    try { await api(`/employer/needs/${needId}/feedback/${cref}`, { method: "DELETE" }); await mutual.reload(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function similar() {
    setErr(null); setBusy(true);
    try {
      const r = await api<any>(`/employer/needs/${needId}/selections/${version}/similar`, { body: { ref: cref } });
      navigate(`/employer/needs/${needId}/v/${r.version}`);
    } catch (e) { setErr(errText(e)); setBusy(false); }
  }
  if (!mutual.data) return null;
  return (
    <div className="mt-3 space-y-2 rounded-xl border border-brand-night/10 bg-[#FBFAFD] p-3">
      {fit ? (
        <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
          <FitBadge fit={fit} />
          <p className="min-w-0 flex-1 basis-56 text-sm text-brand-ink/80">{fit.line}</p>
          <button type="button" className="text-xs font-semibold text-brand hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Скрыть" : "Подробнее"}</button>
        </div>
      ) : <p className="text-sm text-brand-ink/65">Кандидат скрыл профиль — индикатор недоступен</p>}
      {open && fit && <div className="border-t border-brand-night/5 pt-2"><FitFactors factors={fit.factors} /><p className="mt-1 text-xs text-brand-ink/65">Минимум зарплаты кандидата не раскрывается: только «в ожиданиях» или «ниже ожиданий».</p></div>}
      {reacts.map((x, i) => (
        <p key={i} className="text-sm"><span className={`chip ${x.verdict === "interesting" ? "!bg-emerald-50 !text-emerald-800" : ""}`}>руководитель: {x.verdict_title}</span>
          {x.comment && <span className="ml-2 text-brand-ink/80">«{x.comment}»</span>}
          <span className="ml-2 text-xs text-brand-ink/65">{[x.author, x.share_label, dtt(x.updated_at)].filter(Boolean).join(" · ")}</span></p>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        {fb ? (
          <>
            <span className={`chip ${fb.verdict === "fit" ? "!bg-emerald-50 !text-emerald-800" : ""}`}>вы отметили: {fb.verdict === "fit" ? "подходит" : `не подходит — ${fb.reason_title}`}{fb.version !== version ? ` (в v${fb.version})` : ""}</span>
            {fb.comment && <span className="text-xs text-brand-ink/70">«{fb.comment}»</span>}
            <button type="button" className="text-xs font-semibold text-brand hover:underline" disabled={busy} onClick={clear}>Снять отметку</button>
          </>
        ) : (
          <>
            <button type="button" className="btn-ghost !px-3 !py-1.5 text-sm" disabled={busy} onClick={() => save("fit")}>Подходит</button>
            <button type="button" className="btn-ghost !px-3 !py-1.5 text-sm" aria-expanded={mode === "unfit"} disabled={busy} onClick={() => setMode(mode === "unfit" ? "none" : "unfit")}>Не подходит</button>
          </>
        )}
        <button type="button" className="text-sm font-semibold text-brand hover:underline" disabled={busy} onClick={similar} title="Новая версия подборки: та же категория и подтверждённые навыки">Ещё похожих</button>
      </div>
      {mode === "unfit" && !fb && (
        <div className="space-y-2 border-t border-brand-night/5 pt-2">
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Причина">
            {REASONS.map((r) => (
              <button key={r.id} type="button" role="radio" aria-checked={reason === r.id} onClick={() => setReason(r.id)}
                className={`rounded-full border px-2.5 py-1 text-xs ${reason === r.id ? "border-brand bg-brand-blush/50 font-semibold" : "border-brand-night/15"}`}>{r.title}</button>
            ))}
          </div>
          <input className="input" maxLength={300} placeholder="Комментарий (необязательно)" value={comment} onChange={(e) => setComment(e.target.value)} aria-label="Комментарий" />
          <button type="button" className="btn-primary !py-2" disabled={busy || !reason} onClick={() => save("unfit")}>Сохранить отметку</button>
        </div>
      )}
      <Alert>{err}</Alert>
    </div>
  );
}

function ShareModal({ open, onClose, needId, version }: { open: boolean; onClose: () => void; needId: string; version: number }) {
  const list = useApi<any[]>(open ? `/employer/needs/${needId}/shares` : null, [open]);
  const [label, setLabel] = useState("");
  const [made, setMade] = useState<any | null>(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const url = made ? `${window.location.origin}${made.path}` : "";
  async function create() {
    setErr(null); setCopied(false);
    try { setMade(await api<any>(`/employer/needs/${needId}/shares`, { body: { version, label: label || null } })); setLabel(""); list.reload(); }
    catch (e) { setErr(errText(e)); }
  }
  async function revoke(id: string) {
    try { await api(`/employer/needs/${needId}/shares/${id}/revoke`, { method: "POST" }); list.reload(); } catch (e) { setErr(errText(e)); }
  }
  const STATUS: Record<string, string> = { active: "действует", revoked: "отозвана", expired: "истекла" };
  return (
    <Modal open={open} onClose={() => { setMade(null); onClose(); }} title="Ссылка для нанимающего руководителя">
      <div className="space-y-4">
        <p className="text-sm text-brand-ink/70">Только чтение: обезличенные карточки версии v{version} с объяснениями, без ФИО, контактов и минимума зарплаты. Ссылка действует 7 дней, её можно отозвать. Руководитель отмечает «интересно / нет» с комментарием — отметки появятся в подборке.</p>
        {made ? (
          <div className="space-y-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3">
            <p className="text-sm font-semibold text-emerald-800">Ссылка создана. Скопируйте её сейчас — повторно она не показывается.</p>
            <input className="input" readOnly value={url} aria-label="Ссылка" onFocus={(e) => e.target.select()} />
            <button type="button" className="btn-primary !py-2" onClick={() => { navigator.clipboard?.writeText(url).then(() => setCopied(true)).catch(() => setCopied(false)); }}>{copied ? "Скопировано" : "Скопировать"}</button>
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[12rem] flex-1"><Field label="Для кого (необязательно)" htmlFor="share-label"><input id="share-label" className="input" maxLength={100} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Например, руководитель команды платежей" /></Field></div>
            <button type="button" className="btn-primary" onClick={create}>Создать ссылку на v{version}</button>
          </div>
        )}
        <Alert>{err || list.error}</Alert>
        {!!list.data?.length && (
          <ul className="divide-y divide-brand-night/5 text-sm">
            {list.data.map((s) => (
              <li key={s.id} className="space-y-1 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span><b className="font-semibold">{s.label || "Без подписи"}</b> · v{s.version} · {STATUS[s.status]} · просмотров: {s.views}</span>
                  {s.status === "active" && <button type="button" className="text-xs font-semibold text-brand hover:underline" onClick={() => revoke(s.id)}>Отозвать</button>}
                </div>
                <p className="text-xs text-brand-ink/65">создана {dtt(s.created_at)} · {s.status === "revoked" ? `отозвана ${dtt(s.revoked_at)}` : `до ${dtt(s.expires_at)}`}</p>
                {s.reactions.map((r: any) => <p key={r.ref} className="text-xs"><span className="font-semibold">{r.ref}</span>: {r.verdict_title}{r.comment ? ` — «${r.comment}»` : ""}{r.author ? ` (${r.author})` : ""}</p>)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}

/** Подсказка в форме приглашения до отправки: подходит ли предложение кандидату (вилка против скрытого минимума,
 *  формат, город, интересы). Запрос — после паузы в наборе: число сравнений вилки ограничено. */
export function OfferFitHint({ cref, needId, from, to, basis }: { cref: string; needId?: string | null; from?: number; to?: number; basis?: string }) {
  const [res, setRes] = useState<(Fit & { hint: string; salary_status: string }) | null>(null);
  const seq = useRef(0);
  const valid = !!to && to >= 10000 && (!from || from <= to);
  const key = useMemo(() => (valid ? `${cref}|${needId ?? ""}|${Math.floor((to as number) / 10000)}|${basis ?? "gross"}` : ""), [cref, needId, to, valid, basis]);
  useEffect(() => {
    if (!key) { setRes(null); return; }
    const my = ++seq.current;
    const t = setTimeout(() => {
      api<any>("/employer/mutual/offer-check", { body: { candidate_ref: cref, need_id: needId || null, salary_from: from || null, salary_to: to, salary_basis: basis === "net" ? "net" : "gross" } })
        .then((r) => { if (my === seq.current) setRes(r); }).catch(() => { if (my === seq.current) setRes(null); });
    }, 700);
    return () => clearTimeout(t);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!res) return null;
  const warn = res.salary_status === "bad" || res.level === "low";
  return (
    <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${warn ? "border-brand/30 bg-brand-blush/40 text-brand-plum" : "border-brand-lavender/30 bg-[#F3F2FB] text-brand-night"}`}>
      <div className="flex flex-wrap items-center gap-2"><FitBadge fit={res} /><span className="font-semibold" data-testid="offer-fit-head">{res.salary_status === "bad" ? "С такой вилкой кандидат, вероятно, откажет" : res.hint}</span></div>
      <p className="mt-1 text-brand-ink/80">{res.line}</p>
      {res.salary_status === "bad" && <p className="mt-1 text-xs text-brand-ink/65">Верх вилки ниже ожиданий кандидата. Минимум не раскрывается; сравнений вилки — не больше пяти в сутки на кандидата.</p>}
    </div>
  );
}

/** Вход шага проводника: открыть подборку первой потребности (в песочнице жюри — «Backend … платежей»). */
export function MutualEntry() {
  const navigate = useNavigate();
  const needs = useApi<any[]>("/employer/needs");
  useEffect(() => {
    if (!needs.data) return;
    const n = needs.data.find((x) => /платеж/i.test(x.title)) ?? needs.data[0];
    navigate(n ? `/employer/needs/${n.id}` : "/employer/needs", { replace: true });
  }, [needs.data]); // eslint-disable-line react-hooks/exhaustive-deps
  return needs.error ? <Alert>{needs.error}</Alert> : <p className="text-sm text-brand-ink/65">Открываем подборку…</p>;
}
