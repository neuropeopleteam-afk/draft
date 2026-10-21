import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Alert, Level, catTitle, errText, range, ruText } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { juryLogin, personaOf, scenario, type Persona } from "../../lib/jury";
import { useDemoAccess } from "../../lib/juryMode";
import { launchLiveAvatar } from "../../components/Interview";
import { usePageTitle } from "../../lib/meta";
import { chime, type Feed, type Guest, num, plain, STAGE_TITLE, time, unlockAudio } from "../../ideas/live/api";

const sidOf = (email?: string | null) => (email && email.includes("+") ? email.split("+")[1].split("@")[0] : null);

export default function LivePitch() {
  usePageTitle(
    "Живой зал на питче — Демо для жюри",
    "Отсканируйте QR телефоном: экспресс-тест на 3 минуты без регистрации → распределение уровней и сигналы античита на большом экране в реальном времени."
  );
  const demoAccess = useDemoAccess();
  const { me, signIn, signOut, loading } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ n: number; until: number } | null>(null);
  const [open, setOpen] = useState<"ok" | "locked" | "unknown">("unknown");
  const [copied, setCopied] = useState(false);
  const [sound, setSound] = useState(false);
  const state = useRef<{ rev: number | null; since: string | null; invited: number }>({ rev: null, since: null, invited: -1 });
  const [ready, setReady] = useState(false);
  const [going, setGoing] = useState<string | null>(null);
  const [simBusy, setSimBusy] = useState(false);

  useEffect(() => {
    if (loading || !demoAccess) return;
    const hash = new URLSearchParams(loc.hash.replace(/^#/, "")).get("s");
    if (hash && /^[a-z0-9]{10}$/.test(hash) && hash !== scenario.get()) scenario.set(hash);
    const want = scenario.get();
    const ok = personaOf(me?.email) === "employer" && sidOf(me?.email) && (!want || sidOf(me?.email) === want);
    if (ok) { setReady(true); return; }
    setReady(false);
    juryLogin("employer", signIn, "/demo/live")
      .then((to) => (to === "/demo/live" || to === "/jury/live" ? setReady(true) : navigate(to)))
      .catch((e) => setError(errText(e)));
  }, [loading, me?.email, demoAccess]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!ready) return;
    let stop = false;
    const tick = async () => {
      const s = state.current;
      const q = s.rev !== null && s.since ? `?rev=${s.rev}&since=${encodeURIComponent(s.since)}` : "";
      try {
        const o = `origin=${encodeURIComponent(window.location.origin)}`;
        const r = await api<Feed | { changed: false; rev: number; now: string }>(`/jury/live/room/feed${q ? `${q}&${o}` : `?${o}`}`);
        if (stop) return;
        if (r.changed) {
          setFeed(r);
          if (s.invited >= 0 && r.counters.invited > s.invited && sound) chime("Приглашение отправлено");
          s.invited = r.counters.invited;
        }
        s.rev = r.rev; s.since = r.now; setError(null);
      } catch (e) {
        if (stop) return;
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setReady(false);
          juryLogin("employer", signIn, "/demo/live")
            .then((to) => { if (to !== "/demo/live" && to !== "/jury/live") { navigate(to); return; } s.rev = null; setReady(true); })
            .catch((x) => setError(errText(x)));
          return;
        }
        setError(errText(e));
      }
    };
    void tick();
    const t = setInterval(tick, 1500);
    return () => { stop = true; clearInterval(t); };
  }, [ready, sound]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!feed?.code) return;
    const asset = document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src;
    Promise.all([
      fetch(`/j/${feed.code}`, { credentials: "omit", cache: "no-store" }),
      asset ? fetch(asset, { credentials: "omit", cache: "no-store" }) : Promise.resolve(null),
    ])
      .then(([a, b]) => setOpen(a.status === 401 || b?.status === 401 ? "locked" : a.ok ? "ok" : "unknown"))
      .catch(() => setOpen("unknown"));
  }, [feed?.code]);

  if (!demoAccess) {
    return (
      <main id="main" className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-6xl font-extrabold text-brand">404</p>
        <h1 className="text-xl font-bold text-brand-night">Страница не найдена</h1>
        <Link to="/" className="btn-primary">На главную</Link>
      </main>
    );
  }

  const guests = feed?.guests ?? [];
  const focused = pickFocus(guests, feed?.events ?? [], focus);
  const shareLink = typeof window !== "undefined" && scenario.get() ? `${window.location.origin}/demo/live#s=${scenario.get()}` : null;

  async function clear() {
    if (!confirm("Удалить всех гостей этого зала вместе с их приглашениями? Остальное демо и чужие залы не изменятся.")) return;
    try { await api("/jury/live/room/clear", { method: "POST" }); state.current.rev = null; setFocus(null); }
    catch (e) { setError(errText(e)); }
  }

  async function simulateGuestInHall() {
    if (!feed?.code) return;
    setSimBusy(true); setError(null);
    try {
      const code = feed.code.toLowerCase();
      const startRes = await fetch(`/api/jury/live/j/${code}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ direction: "backend" }),
      });
      const started = await startRes.json();
      if (!startRes.ok) throw new Error(started?.detail?.message ?? "Не удалось запустить гостя");
      const token: string = started.token;
      let g: Guest = started.guest;
      while (g.stage === "testing" && g.item) {
        const opt = g.item.options?.[0]?.id ?? "A";
        const ansRes = await fetch(`/api/jury/live/j/${code}/answer`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json", "X-Guest-Token": token },
          body: JSON.stringify({ token: g.item.token, answer: opt }),
        });
        if (!ansRes.ok) break;
        g = await ansRes.json();
      }
      state.current.rev = null;
    } catch (e) {
      setError(errText(e));
    } finally {
      setSimBusy(false);
    }
  }

  function back() { if (window.history.length > 2) navigate(-1); else navigate("/demo"); }
  function exit() { signOut(); navigate("/"); }
  async function enterAs(key: string, persona: Persona, path: string) {
    setGoing(key); setError(null);
    try { navigate(await juryLogin(persona, signIn, path)); }
    catch (e) { setError(errText(e)); setGoing(null); }
  }
  async function liveAvatar() {
    setGoing("avatar"); setError(null);
    try {
      if (typeof navigator !== "undefined" && navigator.webdriver) { navigate(await juryLogin("candidate", signIn, "/candidate/category?defense=open#defense")); return; }
      await launchLiveAvatar(signIn, navigate, me?.role);
    } catch (e) { setError(errText(e)); setGoing(null); }
  }
  function fullscreen() {
    unlockAudio(); setSound(true);
    const el = document.documentElement;
    if (document.fullscreenElement) void document.exitFullscreen(); else void el.requestFullscreen?.().catch(() => undefined);
  }

  // Агрегаты зала без персональных данных: распределение уровней и сигналы самостоятельности
  const gradeCounts: Record<string, number> = { intern: 0, junior: 0, middle: 0, senior: 0, none: 0 };
  let fastAnswersCount = 0;
  let normalPacedCount = 0;
  for (const g of guests) {
    if (g.stage === "testing") continue;
    const gr = (g.result?.grade ?? "none").toLowerCase();
    if (gr in gradeCounts) gradeCounts[gr] += 1;
    else gradeCounts.none += 1;
    if (g.result) {
      if (g.result.time_s < g.result.answered * 4) fastAnswersCount += 1;
      else normalPacedCount += 1;
    }
  }

  return (
    <div className="min-h-screen bg-[#FBF8FC] text-brand-ink">
      <header className="bg-brand-night text-white">
        <nav aria-label="Навигация экрана зала" className="border-b border-white/10">
          <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-2 px-6 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={back} className="btn bg-white px-3.5 py-2 text-sm font-bold text-brand-night hover:bg-brand-blush">
                <span aria-hidden="true">←</span> Назад в Демо-хаб
              </button>
              <Link to="/" className="btn bg-white/10 px-3.5 py-2 text-sm text-white hover:bg-white/20">На главную</Link>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" disabled={!!going} onClick={() => void enterAs("candidate", "candidate", "/candidate")}
                className="btn bg-white/10 px-3.5 py-2 text-sm text-white hover:bg-white/20">
                {going === "candidate" ? "Вход…" : "Кабинет кандидата"}
              </button>
              <Link to="/employer/invitations" className="btn bg-white px-3.5 py-2 text-sm text-brand-night hover:bg-brand-blush">Кабинет работодателя</Link>
              <Link to="/demo" className="btn bg-white/10 px-3.5 py-2 text-sm text-white hover:bg-white/20">Демо для жюри</Link>
              <button type="button" onClick={exit}
                className="btn border border-white/40 bg-transparent px-3.5 py-2 text-sm font-bold text-white hover:bg-white hover:text-brand-night">
                Выйти
              </button>
            </div>
          </div>
        </nav>
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-blush/80">Драфт · Живой зал для питч-сессии (без персональных данных)</p>
            <h1 className="mt-1 text-xl font-extrabold tracking-tight md:text-2xl">Отсканируйте QR с телефона: мини-тест за 3 минуты → уровень и радар античита на экране</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={simBusy || !feed}
              onClick={simulateGuestInHall}
              className="btn bg-brand-strong px-4 py-2.5 text-sm font-bold text-white hover:bg-brand-deep disabled:opacity-50"
              data-testid="live-simulate-guest"
            >
              {simBusy ? "Проходит мини-тест…" : "+ Смоделировать участника зала"}
            </button>
            <button className="btn bg-white/10 px-4 py-2.5 text-white hover:bg-white/20" onClick={fullscreen}>Полный экран и звук</button>
            {feed && <a className="btn bg-white/10 px-4 py-2.5 text-white hover:bg-white/20" href={`${feed.qr_png}?download=1&origin=${encodeURIComponent(window.location.origin)}`}>Скачать QR для слайда</a>}
            {shareLink && (
              <button className="btn bg-white/10 px-4 py-2.5 text-white hover:bg-white/20"
                onClick={() => navigator.clipboard?.writeText(shareLink).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2500); })}>
                {copied ? "Ссылка скопирована" : "Ссылка на этот зал"}
              </button>
            )}
            <button className="btn bg-white/10 px-4 py-2.5 text-white hover:bg-white/20" onClick={clear} disabled={!guests.length}>Очистить зал</button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[1500px] px-6 py-6">
        {error && <div className="mb-4"><Alert>{error}</Alert></div>}
        {!feed ? <p className="text-sm text-brand-ink/65">Готовим зал: автоматический вход работодателем демо-песочницы…</p> : (
          <div className="grid gap-6 lg:grid-cols-[minmax(280px,360px)_1fr] xl:grid-cols-[minmax(300px,380px)_1fr_minmax(300px,360px)]">
            <aside className="space-y-4">
              <div className="card p-5 text-center">
                <img src={`${feed.qr_svg}?origin=${encodeURIComponent(window.location.origin)}`} alt={`QR-код: ${feed.url}`} className="mx-auto aspect-square w-full max-w-[300px] rounded-xl" />
                <p className="mt-3 break-all font-mono text-lg font-bold text-brand-night">{feed.url.replace(/^https?:\/\//, "")}</p>
                <p className="mt-1 text-sm text-brand-ink/70">Камера телефона → адаптивный мини-тест без регистрации</p>
                {open === "ok" && <p className="mt-2 text-xs font-semibold text-emerald-700">✓ Адрес открывается с телефона сразу без пароля</p>}
              </div>
              <div className="grid grid-cols-3 gap-2" data-testid="live-counters">
                <Counter label="В зале" value={feed.counters.joined} />
                <Counter label="Решают" value={feed.counters.testing} />
                <Counter label="С уровнем" value={feed.counters.with_category} />
                <Counter label="В подборке" value={feed.counters.selected} />
                <Counter label="Офферов" value={feed.counters.invited} accent />
                <Counter label="Приняли" value={feed.counters.accepted} />
              </div>

              {/* Распределение уровней и сигналы античита зала в реальном времени */}
              <div className="card space-y-3 p-4" data-testid="live-distribution-anticheat">
                <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand-plum">Распределение уровней зала</p>
                <div className="space-y-1.5 text-xs">
                  {([
                    ["middle", "Middle (потолок мини-теста)", gradeCounts.middle],
                    ["junior", "Junior", gradeCounts.junior],
                    ["intern", "Стажёр", gradeCounts.intern],
                    ["none", "Ниже порога / в процессе", gradeCounts.none + feed.counters.testing],
                  ] as [string, string, number][]).map(([k, label, count]) => (
                    <div key={k} className="flex items-center justify-between gap-2 rounded-lg bg-[#F3F2FB] px-3 py-1.5">
                      <span className="font-medium text-brand-night">{label}</span>
                      <span className="font-mono font-bold text-brand">{count}</span>
                    </div>
                  ))}
                </div>
                <div className="border-t border-brand-night/10 pt-3">
                  <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-brand-plum">Радар античита зала (без ПДн)</p>
                  <ul className="mt-2 space-y-1.5 text-xs text-brand-ink/80">
                    <li className="flex justify-between"><span>Ключи заданий на клиенте:</span><b className="text-emerald-700">0 (только сервер)</b></li>
                    <li className="flex justify-between"><span>Естественный темп ответа:</span><b className="font-mono">{normalPacedCount} уч.</b></li>
                    <li className="flex justify-between"><span>Сверхбыстрые клики (&lt;4 с/зад.):</span><b className="font-mono text-brand-plum">{fastAnswersCount} уч.</b></li>
                    <li className="flex justify-between"><span>Защита верхних грейдов:</span><b>потолок Middle</b></li>
                  </ul>
                </div>
              </div>
              <p className="text-xs leading-relaxed text-brand-ink/65">{feed.rule}</p>
            </aside>

            <section className="min-w-0 space-y-4">
              <GuestStrip guests={guests} focused={focused?.number ?? null} onPick={(n) => setFocus({ n, until: Date.now() + 60_000 })} />
              {focused ? <Focus g={focused} /> : (
                <div className="card flex min-h-[320px] flex-col items-center justify-center px-6 py-8 text-center">
                  <p className="text-lg font-bold text-brand-night">Зал готов к приёму участников с телефонов</p>
                  <p className="mt-2 max-w-xl text-sm leading-relaxed text-brand-ink/70">
                    Отсканируйте QR-код камерой телефона или нажмите «Смоделировать участника зала» в шапке. Здесь в реальном времени появится калибровка уровня (θ ± SE), место в подборке работодателя, объяснение «почему он здесь» и отправка приглашения с зарплатной вилкой.
                  </p>
                  <div className="mt-6 flex w-full max-w-xl flex-col gap-3">
                    <a href={`/j/${feed.code}`} target="_blank" rel="noopener"
                      className="btn-primary w-full px-5 py-4 text-base">
                      Открыть мобильный мини-тест в новой вкладке (/j/{feed.code})
                    </a>
                    <button
                      type="button"
                      disabled={simBusy}
                      onClick={simulateGuestInHall}
                      className="btn w-full border-2 border-brand-night bg-white px-5 py-3.5 text-sm font-bold text-brand-night hover:bg-brand-blush/50"
                    >
                      {simBusy ? "Моделируем прохождение…" : "Быстрая демонстрация: смоделировать участника зала в 1 клик"}
                    </button>
                    <button type="button" disabled={!!going} onClick={() => void liveAvatar()} className="text-xs font-semibold text-brand hover:underline disabled:opacity-60">
                      {going === "avatar" ? "Запускаем…" : "Перейти к живой устной защите с ИИ-аватаром →"}
                    </button>
                  </div>
                </div>
              )}
            </section>

            <aside className="min-w-0 lg:col-span-2 xl:col-span-1">
              <div className="card p-5">
                <p className="text-sm font-bold text-brand-night">Живая лента событий зала</p>
                {!feed.events.length ? <p className="mt-2 text-sm text-brand-ink/65">Событий пока нет</p> : (
                  <ol className="mt-3 max-h-[70vh] space-y-2.5 overflow-y-auto pr-1">
                    {feed.events.map((e, i) => (
                      <li key={`${e.at}-${e.kind}-${e.guest}-${i}`} className="flex gap-3 text-sm">
                        <span className="w-16 shrink-0 font-mono text-xs text-brand-ink/65">{time(e.at)}</span>
                        <span className={`min-w-0 ${["invited", "accepted", "push"].includes(e.kind) ? "font-semibold text-brand-night" : "text-brand-ink/80"}`}>
                          <b>{e.label}</b> {e.text}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

function plural(n: number, one: string, few: string, many: string) {
  const d = n % 10, h = n % 100;
  return d === 1 && h !== 11 ? one : d >= 2 && d <= 4 && (h < 12 || h > 14) ? few : many;
}

function pickFocus(guests: Guest[], events: Feed["events"], focus: { n: number; until: number } | null): Guest | null {
  if (focus && focus.until > Date.now()) { const g = guests.find((x) => x.number === focus.n); if (g) return g; }
  const started = guests.filter((g) => g.stage !== "testing");
  const lastEv = events.find((e) => started.some((g) => g.number === e.guest));
  return (lastEv && guests.find((g) => g.number === lastEv.guest)) || started[started.length - 1] || guests[guests.length - 1] || null;
}

function Counter({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className={`rounded-2xl px-3 py-3 text-center ${accent ? "bg-brand-strong text-white" : "border border-brand-night/10 bg-white"}`}>
      <p className={`text-2xl font-extrabold ${accent ? "" : "text-brand-night"}`}>{value}</p>
      <p className={`text-[11px] font-semibold ${accent ? "text-white/85" : "text-brand-ink/65"}`}>{label}</p>
    </div>
  );
}

function GuestStrip({ guests, focused, onPick }: { guests: Guest[]; focused: number | null; onPick: (n: number) => void }) {
  if (!guests.length) return null;
  return (
    <div className="flex flex-wrap gap-2" aria-label="Участники зала">
      {guests.map((g) => (
        <button key={g.number} onClick={() => onPick(g.number)} aria-pressed={focused === g.number}
          className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${focused === g.number ? "border-brand-strong bg-brand-strong text-white" : "border-brand-night/15 bg-white text-brand-night hover:border-brand/40"}`}>
          {g.label} · {g.direction_title} · {g.stage === "testing" ? `${g.answered}/${g.total}` : STAGE_TITLE[g.stage]}
        </button>
      ))}
    </div>
  );
}

function Focus({ g }: { g: Guest }) {
  const r = g.result, sel = g.selection, inv = g.invite;
  return (
    <div className="space-y-4">
      <div className="card space-y-3 p-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{g.label} · {g.ref} · {g.direction_title}</p>
          {g.stage === "testing" ? (
            <p className="mt-1 text-xl font-extrabold text-brand-night">Проходит мини-тест: отвечено {g.answered} из {g.total}</p>
          ) : r?.grade ? (
            <p className="mt-1 text-xl font-extrabold text-brand-night">Экспресс-категория {r.category_title ?? catTitle(r.category_id)}</p>
          ) : (
            <p className="mt-1 text-xl font-extrabold text-brand-night">Категория не присвоена — в подборку не попадает</p>
          )}
          {r && <p className="mt-1 text-sm text-brand-ink/70">{r.correct} из {r.answered} верно · уровень = {num(r.theta)} ± {plain(r.se)} · {Math.round(r.time_s)} с</p>}
        </div>
      </div>

      {sel && (
        <div className="card p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-bold text-brand-night">Подборка работодателя: {sel.need_title.replace("Живая демонстрация: ", "")}</p>
            <p className="text-xs text-brand-ink/65">версия {sel.version} · {sel.total} {plural(sel.total, "кандидат", "кандидата", "кандидатов")}{sel.rank != null && ` · ${g.label} — место ${sel.rank}`}</p>
          </div>
          <table className="mt-3 w-full text-sm">
            <thead className="text-left text-xs text-brand-ink/65">
              <tr><th className="w-10 py-1.5 font-semibold">№</th><th className="py-1.5 font-semibold">Кандидат</th><th className="py-1.5 font-semibold">Категория</th><th className="w-40 py-1.5 font-semibold">Совпадение</th></tr>
            </thead>
            <tbody>
              {(sel.top ?? []).map((t) => (
                <tr key={t.ref} className={`border-t border-brand-night/5 ${t.is_self ? "bg-brand-blush/50 font-semibold" : ""}`}>
                  <td className="py-2 pl-1 font-mono text-xs">{t.rank}</td>
                  <td className="py-2">
                    <span className="text-brand-night">{t.label ?? t.ref}</span>
                    {t.label && <span className="ml-2 font-mono text-[11px] text-brand-ink/65">{t.ref}</span>}
                    {t.mini && <span className="ml-2 rounded bg-brand-blush px-1.5 py-0.5 text-[10px] font-bold text-brand-plum">мини-тест</span>}
                    {t.fsp && <span className="ml-2 rounded bg-[#ECEAF8] px-1.5 py-0.5 text-[10px] font-bold text-brand-night">ФСП</span>}
                  </td>
                  <td className="py-2 text-brand-ink/75">{catTitle(t.category_id)}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-brand-blush/50"><div className={`h-full ${t.is_self ? "bg-brand" : "bg-brand-lavender"}`} style={{ width: `${Math.round(t.score * 100)}%` }} /></div>
                      <span className="w-9 text-right font-mono text-xs">{Math.round(t.score * 100)}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {sel.rank != null && (
            <>
              <p className="mt-4 text-sm font-bold text-brand-night">Почему {g.label} на {sel.rank}-м месте</p>
              <ul className="mt-2 grid gap-2 md:grid-cols-2">
                {sel.reasons.map((x, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs leading-relaxed text-brand-ink/80"><Level level={x.level} /><span><b>{x.requirement}.</b> {ruText(x.text)}</span></li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {inv && (
        <div className="rounded-2xl bg-brand-night p-5 text-white">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-blush/80">Приглашение отправлено в {time(inv.sent_at)}</p>
          </div>
          <p className="mt-2 text-lg font-bold">{inv.position_title}</p>
          <p className="mt-1 text-3xl font-extrabold tracking-tight">{range(inv.salary_from, inv.salary_to)}</p>
          {inv.market && <p className="mt-1 text-xs text-white/70">Вилка по рынку категории: {range(inv.market.from, inv.market.to)}</p>}
          {g.stage === "accepted" && <p className="mt-3 rounded-xl bg-emerald-500/20 px-3 py-2 text-sm font-semibold">Принято в {time(inv.responded_at)} — контакты открыты работодателю, профиль передан в ATS</p>}
          {g.stage === "declined" && <p className="mt-3 rounded-xl bg-white/10 px-3 py-2 text-sm">Отклонено в {time(inv.responded_at)} — контакты остались скрытыми</p>}
        </div>
      )}
    </div>
  );
}
