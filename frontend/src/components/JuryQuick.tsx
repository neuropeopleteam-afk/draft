import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { isJury, NEED_PRESETS, needPreset, personaOf, quick, QUICK, QUICK_MINUTES, quickInfo, type GuideMode, type Persona,
  type QuickPersona } from "../lib/jury";

/** Я9 «Проверка за 12 минут»: короткий режим проводника жюри (шаги — lib/jury.ts, QUICK). Своя потребность →
 *  первые три → сравнение → приглашение с вилкой → ответ кандидата → экспресс-тест (краткий режим жюри) → категория →
 *  доказательства. У шага — что он проверяет и какой критерий ТЗ, ориентир времени; таймер — ориентир, не ограничение. */
export const QUICK_LEN = QUICK.length;
const SELECTION = 1, COMPARE = 2, INVITE = 3, ANSWER = 4, LAST = QUICK.length - 1;
const PLAN = QUICK.reduce<number[]>((a, s) => [...a, (a.at(-1) ?? 0) + s.min], []);  // минуты к концу шага
const mmss = (ms: number) => { const t = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
const mins = (m: number) => `${String(m).replace(".", ",")}\u00A0мин`;
const NEED_RE = /^\/employer\/needs\/([0-9a-f-]{36})(?:\/|$)/;

/** Адрес шага: подборка, сравнение и приглашение — по потребности, которую эксперт открыл последней. */
function pathOf(i: number): string {
  const n = quick.need();
  if (!n) return QUICK[i].path;
  return i === COMPARE ? `/employer/needs/${n}/compare` : i === SELECTION || i === INVITE ? `/employer/needs/${n}` : QUICK[i].path;
}

/** Шаг по текущему адресу (как у справочника): текущий, если экран ему подходит, иначе ближайший следующий подходящий. */
export function useQuickStep(mode: GuideMode, pathname: string, email?: string | null): [number, (i: number) => void] {
  const [q, setQ] = useState(quick.step());
  const set = (i: number) => { setQ(i); quick.setStep(i); };
  useEffect(() => {
    if (mode !== "quick") return;
    const m = NEED_RE.exec(pathname);
    if (m) quick.setNeed(m[1]);
    const who = personaOf(email);
    const fits = (i: number) => QUICK[i].match.test(pathname) && (!QUICK[i].persona || i === ANSWER || QUICK[i].persona === who);
    const cur = quick.step();
    if (fits(cur)) { setQ(cur); return; }
    const all = QUICK.map((_, i) => i).filter(fits);
    const i = all.find((x) => x > cur) ?? all[0];
    if (i !== undefined) set(i); else setQ(cur);
  }, [mode, pathname, email]); // eslint-disable-line react-hooks/exhaustive-deps
  return [q, set];
}

/** Кому отвечать в шаге «Ответ кандидата»: демо-персоне, которой эксперт сам отправил приглашение по своей потребности,
 *  иначе — Илье Сергееву (ему демо-работодатель уже написал). */
function answerer(info: QuickPersona[] | null): { persona: Persona; name: string; own: boolean } {
  const need = quick.need();
  const own = info?.filter((p) => p.invitation && need && p.invitation.need_id === need)
    .sort((a, b) => b.invitation!.created_at.localeCompare(a.invitation!.created_at))[0];
  if (own) return { persona: own.persona, name: own.name, own: true };
  const ilya = info?.find((p) => p.persona === "candidate_nofsp");
  return { persona: "candidate_nofsp", name: ilya?.name ?? "Илья Сергеев", own: false };
}

export function QuickGuide({ q, setQ, busy, msg, setMsg, open, onReset, who }: {
  q: number; setQ: (i: number) => void; busy: boolean; msg: string | null; setMsg: (m: string | null) => void;
  open: (path: string, persona: Persona | null) => Promise<void>; onReset: () => void; who: string | null;
}) {
  const { me } = useAuth();
  const loc = useLocation();
  const [now, setNow] = useState(Date.now());
  const [info, setInfo] = useState<QuickPersona[] | null>(null);
  useEffect(() => { quick.touch(); const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const jury = isJury(me?.email);
  const need = quick.need();
  // демо-персоны своей копии в подборке — только там, где они нужны (приглашение и ответ)
  useEffect(() => {
    if (!jury || (q !== INVITE && q !== ANSWER)) return;
    let off = false;
    quickInfo(need).then((r) => { if (!off) setInfo(r.personas); }).catch(() => { if (!off) setInfo(null); });
    return () => { off = true; };
  }, [q, need, jury, loc.pathname, me?.email]);

  const s = QUICK[q];
  const ans = answerer(info);
  const persona = q === ANSWER ? ans.persona : s.persona;
  const needLogin = !!persona && personaOf(me?.email) !== persona;
  const here = s.match.test(loc.pathname) && !needLogin;
  const t0 = quick.t0() ?? now;
  const late = now - t0 > PLAN[q] * 60_000;

  async function go(i: number) {
    setQ(i); setMsg(null);
    let p = QUICK[i].persona;
    if (i === ANSWER) {  // приглашение могли отправить только что — спрашиваем перед входом
      const r = jury ? await quickInfo(quick.need()).catch(() => null) : null;
      if (r) setInfo(r.personas);
      p = answerer(r?.personas ?? info).persona;
    }
    await open(pathOf(i), p);
  }
  async function preset(text: string) {
    needPreset.put(text);  // поле «Кого вы ищете» заберёт текст, как только экран откроется
    if (!(QUICK[0].match.test(loc.pathname) && personaOf(me?.email) === "employer")) await open("/employer/needs", "employer");
  }
  const first = (n: string) => n.split(" ")[0];
  const invitable = (info ?? []).filter((p) => p.rank && p.can_invite).sort((a, b) => a.rank! - b.rank!)[0];
  const invited = q === INVITE && ans.own;

  return (
    <>
      <div className="mt-2 flex gap-1" aria-hidden>
        {QUICK.map((_, i) => <span key={i} className={`h-1 flex-1 rounded-full ${i < q ? "bg-brand-soft" : i === q ? "bg-white" : "bg-white/20"}`} />)}
      </div>
      <p className="mt-2 flex flex-wrap justify-between gap-x-3 text-xs text-white/75">
        <span>Шаг {q + 1} из {QUICK.length} · ≈{"\u00A0"}{mins(s.min)}</span>
        <span role="timer" data-testid="quick-timer" className={late ? "text-brand-blush" : undefined}
          title="Ориентир, а не ограничение: проверку можно проходить в своём темпе">
          Прошло {mmss(now - t0)} · план {mins(PLAN[q])} из {QUICK_MINUTES}
        </span>
      </p>
      <p className="mt-2 text-base font-bold">{s.title}</p>
      <p className="mt-1 text-sm leading-relaxed text-white/80">{s.text}</p>
      {q === 0 && (
        <div className="mt-2.5" data-testid="quick-presets">
          <p className="text-xs text-white/75">Заготовки — вставить в поле и поправить:</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {NEED_PRESETS.map((p) => (
              <button key={p.label} type="button" title={p.text} disabled={busy} onClick={() => preset(p.text)}
                className="rounded-lg bg-white/10 px-2.5 py-1 text-xs font-semibold text-white ring-1 ring-white/20 hover:bg-white/20 disabled:opacity-40">{p.label}</button>
            ))}
          </div>
          <p className="mt-1 text-xs text-white/75">Или напишите свою — любой текст вакансии; подойдёт и файл PDF или DOCX.</p>
        </div>
      )}
      {(q === SELECTION || q === COMPARE || q === INVITE) && !need && (
        <p className="mt-2 text-xs text-brand-blush">Сначала сохраните свою потребность (шаг 1) или откройте любую из списка.</p>
      )}
      {q === INVITE && info && (
        <p className="mt-2 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs leading-relaxed text-white/85" data-testid="quick-invite-hint">
          {invited ? `Приглашение отправлено (${ans.name}, демо-кандидат вашей копии) — в следующем шаге ответите на него сами.`
            : invitable ? <>Чтобы в следующем шаге ответить на своё приглашение самому, пригласите кандидата <b>{invitable.ref}</b> (место {invitable.rank} в подборке): это демо-кандидат вашей копии — {invitable.name}.</>
            : "Демо-кандидатов, за которых можно войти, в этой подборке нет: пригласите любого — ответ покажем на готовом приглашении Илье Сергееву."}
        </p>
      )}
      {q === ANSWER && (
        <p className="mt-2 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs leading-relaxed text-white/85" data-testid="quick-answer-hint">
          {ans.own ? `Отвечаете на своё приглашение: ${ans.name}.` : "Своего приглашения демо-кандидату нет — ответ покажем на готовом приглашении Илье Сергееву от демо-работодателя."}
        </p>
      )}
      <p className="mt-2 text-xs leading-snug text-white/75"><b className="font-semibold text-white">Проверяет:</b> {s.checks}</p>
      <p className="mt-0.5 text-xs leading-snug text-brand-blush">Критерий ТЗ {s.crit}</p>
      {q === LAST && (
        <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          <Link to="/validation" className="font-semibold text-brand-blush underline-offset-2 hover:underline">Метрики — /validation</Link>
          <Link to="/validation#red-button" className="font-semibold text-brand-blush underline-offset-2 hover:underline">Красная кнопка</Link>
        </p>
      )}
      {who && <p className="mt-2 text-xs text-white/65">Вы вошли как {who}</p>}
      {msg && <p className="mt-2 rounded-lg bg-white/10 px-3 py-2 text-xs text-brand-blush" role="status">{msg}</p>}
      {/* действия шага — всегда на виду: панель на телефоне ниже 38vh и прокручивается сама */}
      <div className="sticky -bottom-3.5 -mx-3.5 -mb-3.5 mt-2 flex flex-wrap items-center gap-2 border-t border-white/10 bg-brand-night px-3.5 py-2.5 sm:-bottom-4 sm:-mx-4 sm:-mb-4 sm:px-4">
        <button className="btn bg-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/20 disabled:opacity-40" disabled={q === 0 || busy} onClick={() => go(q - 1)}>Назад</button>
        {!here
          ? <button className="btn bg-brand-strong px-3 py-1.5 text-sm text-white hover:bg-brand-deep" disabled={busy} onClick={() => go(q)}>
              {busy ? "Входим…" : q === ANSWER && needLogin ? `Войти как ${first(ans.name)} и ответить` : needLogin || !s.cta.startsWith("Войти") ? s.cta : "Открыть экран"}
            </button>
          : q < LAST
            ? <button className="btn bg-brand-strong px-3 py-1.5 text-sm text-white hover:bg-brand-deep" disabled={busy} onClick={() => go(q + 1)}>{busy ? "Входим…" : `Дальше: ${QUICK[q + 1].title}`}</button>
            : <button className="btn bg-brand-strong px-3 py-1.5 text-sm text-white hover:bg-brand-deep" onClick={() => quick.setMode("full")}>Готово · остальное — в справочнике</button>}
        <span className="ml-auto flex gap-3 text-xs font-semibold text-white/70">
          <button className="underline-offset-2 hover:text-white hover:underline" disabled={busy} onClick={() => { quick.restart(); setQ(0); setNow(Date.now()); }}>Начать заново</button>
          <button className="underline-offset-2 hover:text-white hover:underline" disabled={busy} onClick={onReset}>Сбросить демо</button>
        </span>
      </div>
    </>
  );
}
