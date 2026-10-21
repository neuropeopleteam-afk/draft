// Телефон эксперта жюри: QR → мини-тест из 3 заданий → экспресс-категория → место в подборке → приглашение.
// Без регистрации и без входа на стенд. Push — если браузер позволяет (на iPhone — после «На экран Домой»);
// запасной путь — живое обновление страницы со звуком, вибрацией и заголовком вкладки.
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, Level, catTitle, errText, range, rub, ruText } from "../../components/ui";
import { isStandalone, platform, pushSupported, subscribePush } from "../../integrations/pwa";
import { usePageTitle } from "../../lib/meta";
import { Rich } from "../../pages/candidate/Assessment";
import { chime, FORMAT_TITLE, type Guest, guestApi, guestToken, type LiveItem, num, plain, type RoomPublic, time, unlockAudio } from "./api";

const FINAL = new Set(["accepted", "declined", "no_category"]);

/** Манифест зала: «На экран Домой» на iPhone открывает сразу этот мини-тест (иначе — главную стенда). */
function useRoomManifest(code: string) {
  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="manifest"]');
    if (!link) return;
    const prev = link.href;
    link.href = `/api/jury/live/j/${code}/manifest.webmanifest`;
    const title = document.querySelector<HTMLMetaElement>('meta[name="apple-mobile-web-app-title"]');
    const prevTitle = title?.content;
    if (title) title.content = "Мини-тест";
    return () => { link.href = prev; if (title && prevTitle) title.content = prevTitle; };
  }, [code]);
}

export default function LiveGuest() {
  const { code = "" } = useParams();
  const c = code.toLowerCase();
  const [room, setRoom] = useState<RoomPublic | null>(null);
  const [g, setG] = useState<Guest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [push, setPush] = useState<{ on: boolean; note: string | null }>({ on: false, note: null });
  const prevStage = useRef<string | null>(null);
  useRoomManifest(c);

  usePageTitle("Мини-тест");
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await guestApi<RoomPublic>(c, "");
        if (!alive) return;
        setRoom(r);
        if (guestToken.get(c)) {
          try { const me = await guestApi<Guest>(c, "/me"); if (alive) { prevStage.current = me.stage; setG(me); } }
          catch { guestToken.clear(c); }
        }
      } catch (e) { if (alive) setError(errText(e)); } finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [c]);

  // Живое обновление после теста: подборка и приглашение появляются сами, push не обязателен
  useEffect(() => {
    if (!g || g.stage === "testing" || FINAL.has(g.stage)) return;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      try {
        const me = await guestApi<Guest>(c, `/me?visible=${document.visibilityState === "visible" ? 1 : 0}`);
        if (!stop) setG(me);
      } catch { /* сеть в зале нестабильна — следующий опрос */ }
    };
    const t = setInterval(tick, document.visibilityState === "visible" ? 1500 : 4000);
    const onVis = () => { if (document.visibilityState === "visible") void tick(); };
    const onFocus = () => { void tick(); };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", onFocus);
    window.addEventListener("pageshow", onFocus);
    return () => {
      stop = true;
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pageshow", onFocus);
    };
  }, [c, g?.stage]); // eslint-disable-line react-hooks/exhaustive-deps

  // Момент приглашения: звук, вибрация, заголовок вкладки; без push — ещё и системное уведомление со страницы
  useEffect(() => {
    if (!g) return;
    if (g.stage === "invited" && prevStage.current && prevStage.current !== "invited") {
      chime();
      if (!g.invite?.push?.delivered && "Notification" in window && Notification.permission === "granted") {
        navigator.serviceWorker?.getRegistration("/").then((reg) => reg?.showNotification(`Приглашение: ${g.invite?.company?.name ?? "демо-работодатель"}`, {
          body: `«${g.invite?.position_title}», ${range(g.invite?.salary_from, g.invite?.salary_to)}`, tag: `live-${c}`, icon: "/icons/icon-192.png",
        })).catch(() => undefined);
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    prevStage.current = g.stage;
  }, [g?.stage]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start(direction: string, wantPush: boolean) {
    unlockAudio();
    setError(null);
    // Разрешение — прямо в обработчике нажатия, но без блокировки старта теста на телефоне
    const perm = wantPush && pushSupported() && typeof Notification !== "undefined" && Notification.permission === "default"
      ? Notification.requestPermission().catch(() => "default" as NotificationPermission)
      : null;
    try {
      const r = await guestApi<{ token: string; guest: Guest }>(c, "/start", { direction });
      guestToken.set(c, r.token);
      prevStage.current = r.guest.stage;
      setG(r.guest);
      window.scrollTo({ top: 0 });
      if (wantPush && room?.push.enabled) {
        void (async () => {
          try {
            if (perm) await Promise.race([perm, new Promise((res) => setTimeout(res, 4000))]);
            const res = await subscribePush((j) => guestApi(c, "/push", j));
            setPush({ on: res.ok, note: res.ok ? null : res.reason ?? null });
          } catch {
            setPush({ on: false, note: "Уведомление в фоне недоступно — приглашение появится на этой странице" });
          }
        })();
      }
    } catch (e) { setError(errText(e)); }
  }

  function again() { guestToken.clear(c); setG(null); prevStage.current = null; window.scrollTo({ top: 0 }); }

  return (
    <div className="min-h-screen bg-[#FBF8FC] pb-10">
      <header className="bg-brand-night px-4 pb-4 pt-[max(0.75rem,env(safe-area-inset-top))] text-white">
        {/* Полоска навигации: вернуться к большому экрану зала или на главную — без кнопки «назад» браузера */}
        <nav aria-label="Навигация мини-теста" className="-mx-4 mb-3 flex items-center justify-between gap-2 border-b border-white/10 px-4 pb-2.5">
          <Link to="/jury/live" className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-white px-3.5 py-2 text-xs font-bold text-brand-night hover:bg-brand-blush">
            <span aria-hidden="true">←</span> Назад в зал
          </Link>
          <Link to="/" className="inline-flex min-h-[44px] items-center rounded-xl bg-white/10 px-3.5 py-2 text-xs font-semibold text-white hover:bg-white/20">На главную</Link>
        </nav>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-blush/80">Драфт · живая демонстрация</p>
        <p className="mt-1 text-base font-bold">{room?.company ?? "Демо жюри"}</p>
      </header>
      <main id="main" className="mx-auto max-w-lg px-4 pt-4">
        {loading ? <p className="text-sm text-brand-ink/65">Загрузка…</p>
          : !room ? <Alert>{error ?? "Зал не найден"}</Alert>
          : !g ? <Intro room={room} onStart={start} error={error} />
          : g.stage === "testing" && g.item ? <Item code={c} g={g} item={g.item} onNext={setG} />
          : <Outcome code={c} g={g} push={push} onUpdate={setG} onAgain={again} />}
      </main>
    </div>
  );
}

function IosHint() {
  if (platform() !== "ios" || isStandalone()) return null;
  return (
    <p className="mt-3 rounded-xl bg-[#F3F2FB] px-3 py-2.5 text-xs leading-relaxed text-brand-night">
      iPhone присылает push только приложению с главного экрана: «Поделиться» → «На экран Домой», затем откройте
      мини-тест с иконки. Без этого приглашение появится на этой странице со звуком.
    </p>
  );
}

function Intro({ room, onStart, error }: { room: RoomPublic; onStart: (d: string, push: boolean) => Promise<void>; error: string | null }) {
  const [dir, setDir] = useState<string | null>(room.directions[0]?.id ?? "backend");
  const canPush = room.push.enabled && pushSupported();
  const [wantPush, setWantPush] = useState(true);
  const [busy, setBusy] = useState(false);
  if (!room.open) return <Alert kind="info">Демонстрация сейчас перезапускается. Отсканируйте QR ещё раз через минуту.</Alert>;
  return (
    <>
      <h1 className="text-2xl font-extrabold leading-tight tracking-tight text-brand-night">Мини-тест: {room.items} задания, около трёх минут</h1>
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/75">
        Без регистрации. Задания — из настоящего банка теста, у каждого свой вариант, следующее подбирается по ответам.
        После третьего — экспресс-категория, место в подборке работодателя и, если категория присвоена, приглашение с вилкой
        на этот телефон. На большом экране зал видит, как это происходит.
      </p>
      <fieldset className="mt-5">
        <legend className="label">Направление</legend>
        <div className="grid grid-cols-2 gap-2">
          {room.directions.map((d) => (
            <button key={d.id} type="button" aria-pressed={dir === d.id} onClick={() => setDir(d.id)}
              className={`min-h-[56px] touch-manipulation rounded-xl border px-3 py-3 text-left transition-colors ${dir === d.id ? "border-brand bg-brand-blush/40" : "border-brand-night/10 bg-white"}`}>
              <span className="block text-sm font-bold text-brand-night">{d.title}</span>
              <span className="mt-0.5 block text-[11px] leading-snug text-brand-ink/65">{d.need}</span>
            </button>
          ))}
        </div>
      </fieldset>
      {canPush && (
        <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm text-brand-ink/80">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand" checked={wantPush} onChange={(e) => setWantPush(e.target.checked)} />
          <span>Прислать push-уведомление, когда придёт приглашение</span>
        </label>
      )}
      <IosHint />
      <div className="mt-4"><Alert>{error}</Alert></div>
      <button className="btn-primary mt-5 w-full py-4 text-base" disabled={!dir || busy}
        onClick={async () => { setBusy(true); await onStart(dir!, canPush && wantPush); setBusy(false); }}>
        {busy ? "Готовим задание…" : dir ? "Начать мини-тест" : "Выберите направление"}
      </button>
      <p className="mt-4 text-xs leading-relaxed text-brand-ink/65">{room.rule} Правильность ответов видна только в итоге; ключи заданий не покидают сервер.</p>
    </>
  );
}

function Item({ code, g, item, onNext }: { code: string; g: Guest; item: LiveItem; onNext: (g: Guest) => void }) {
  const [value, setValue] = useState<string | number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setValue(null); setError(null); }, [item.token]);
  const lines = item.code ? item.code.split("\n") : [];
  const isLine = item.answer_kind === "line";

  async function send() {
    if (value === null) return;
    setBusy(true); setError(null);
    try { onNext(await guestApi<Guest>(code, "/answer", { token: item.token, value })); window.scrollTo({ top: 0, behavior: "smooth" }); }
    catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }
  return (
    <div>
      <div className="flex items-center justify-between text-xs font-semibold text-brand-ink/65">
        <span>{g.direction_title} · {FORMAT_TITLE[item.format] ?? "Задание"}</span>
        <span>Задание {item.position} из {item.total}</span>
      </div>
      <div className="mt-2 flex gap-1.5" aria-hidden="true">
        {Array.from({ length: item.total }, (_, i) => (
          <span key={i} className={`h-1.5 flex-1 rounded-full ${i < item.position - 1 ? "bg-brand" : i === item.position - 1 ? "bg-brand/50" : "bg-brand-blush/70"}`} />
        ))}
      </div>
      <div className="card mt-3 min-w-0 p-4">
        <p className="whitespace-pre-line text-[15px] font-semibold leading-relaxed text-brand-night [overflow-wrap:anywhere]"><Rich text={item.stem} /></p>
        {item.code && (
          <div className="mt-3 overflow-x-auto rounded-xl bg-brand-ink py-2 text-[#FFD6E4]" role={isLine ? "listbox" : undefined}
            aria-label={isLine ? "Строки кода: выберите строку с дефектом" : undefined}>
            {lines.map((ln, i) => {
              const n = i + 1;
              const sel = isLine && value === n;
              const cls = `flex w-full min-w-max items-center gap-2.5 px-3 ${isLine ? "min-h-[40px] py-1.5 touch-manipulation" : "py-0.5"} text-left font-mono text-[12.5px] leading-relaxed ${sel ? "bg-brand/55 font-bold text-white" : ""}`;
              const body = (<><span className="w-6 shrink-0 select-none text-right text-[#FFD6E4]/60">{n}</span><span className="whitespace-pre">{ln || " "}</span></>);
              return isLine
                ? <button key={i} type="button" role="option" aria-selected={sel} className={cls} onClick={() => setValue(n)}>{body}</button>
                : <div key={i} className={cls}>{body}</div>;
            })}
          </div>
        )}
        {isLine && <p className="mt-2 text-xs text-brand-ink/65">{value ? `Выбрана строка ${value}.` : "Нажмите на строку, в которой дефект. Код прокручивается вбок."}</p>}
        {item.answer_kind === "option" && item.options && (
          <fieldset className="mt-4 min-w-0 space-y-2">
            <legend className="sr-only">Варианты ответа</legend>
            {item.options.map((o) => (
              <label key={o.id} className={`flex min-h-[48px] touch-manipulation cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 text-sm transition-colors ${value === o.id ? "border-brand bg-brand-blush/30" : "border-brand-night/10"}`}>
                <input type="radio" name="opt" className="mt-1 h-4 w-4 shrink-0 accent-brand" checked={value === o.id} onChange={() => setValue(o.id)} />
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                  <b className="mr-1.5 text-brand-lavender">{o.id}</b>
                  <span className={o.code ? "" : "font-mono text-[13px]"}>{o.code ? <Rich text={o.text} /> : o.text}</span>
                  {o.code && <pre className="mt-2 max-w-full overflow-x-auto rounded-lg bg-brand-ink p-2.5 text-[11.5px] leading-relaxed text-[#FFD6E4]"><code>{o.code}</code></pre>}
                </span>
              </label>
            ))}
          </fieldset>
        )}
        <div className="mt-3"><Alert>{error}</Alert></div>
      </div>
      <div className="sticky bottom-0 -mx-4 mt-3 bg-gradient-to-t from-[#FBF8FC] via-[#FBF8FC] to-transparent px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-4">
        <button className="btn-primary min-h-[48px] touch-manipulation w-full py-4 text-base" disabled={value === null || busy} onClick={send}>
          {busy ? (item.position === item.total ? "Считаем результат…" : "Отправляем…") : item.position === item.total ? "Ответить и узнать результат" : "Ответить"}
        </button>
      </div>
    </div>
  );
}

function Step({ done, active, title, children }: { done: boolean; active: boolean; title: string; children?: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${done ? "bg-brand-strong text-white" : active ? "border-2 border-brand text-brand" : "border border-brand-night/20 text-brand-ink/65"}`} aria-hidden="true">
        {done ? <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M3.5 8.5l3 3 6-7" /></svg>
          : active ? <span className="h-2 w-2 animate-ping rounded-full bg-brand" /> : null}
      </span>
      <div className="min-w-0">
        <p className={`text-sm font-semibold ${done || active ? "text-brand-night" : "text-brand-ink/65"}`}>{title}</p>
        {children && <div className="mt-0.5 text-xs leading-relaxed text-brand-ink/70">{children}</div>}
      </div>
    </li>
  );
}

function Outcome({ code, g, push, onUpdate, onAgain }: { code: string; g: Guest; push: { on: boolean; note: string | null }; onUpdate: (g: Guest) => void; onAgain: () => void }) {
  const r = g.result;
  const sel = g.selection;
  const inv = g.invite;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [why, setWhy] = useState(false);
  const selected = ["selected", "invited", "accepted", "declined"].includes(g.stage);
  const invited = ["invited", "accepted", "declined"].includes(g.stage);

  async function respond(accept: boolean) {
    setBusy(accept ? "accept" : "decline"); setError(null);
    try { onUpdate(await guestApi<Guest>(code, "/respond", { accept })); } catch (e) { setError(errText(e)); } finally { setBusy(null); }
  }
  if (g.stage === "no_category") {
    return (
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">Категория не присвоена</h1>
        <div className="card mt-4 p-4 text-sm leading-relaxed text-brand-ink/80">
          <p><b>{r?.correct} из {r?.answered}</b> верно, θ = {num(r?.theta)} ± {plain(r?.se)} — ниже порога Стажёра (θ = −1,75).</p>
          <p className="mt-2">Так работает и полный тест: без подтверждённой категории кандидат в подборку не попадает и приглашений не получает.</p>
        </div>
        <button className="btn-primary mt-5 w-full py-4 text-base" onClick={onAgain}>Пройти ещё раз</button>
      </div>
    );
  }
  return (
    <div>
      {invited && inv ? (
        <section aria-live="polite" className="rounded-2xl bg-brand-night p-5 text-white shadow-lg">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-blush/80">Приглашение · {time(inv.sent_at)}</p>
          <p className="mt-2 text-lg font-bold leading-snug">{inv.company?.name ?? "Демо-работодатель"}</p>
          <p className="mt-1 text-sm text-white/80">{inv.position_title}</p>
          <p className="mt-3 text-2xl font-extrabold tracking-tight">{range(inv.salary_from, inv.salary_to)}</p>
          {inv.market && <p className="mt-1 text-xs text-white/70">Рынок категории: {rub(inv.market.from)} – {rub(inv.market.to)}</p>}
          {g.stage === "invited" ? (
            <div className="mt-4 grid grid-cols-2 gap-2">
              <button className="btn min-h-[48px] touch-manipulation bg-brand-strong py-3.5 text-white hover:bg-brand-deep" disabled={!!busy} onClick={() => respond(true)}>{busy === "accept" ? "Отправляем…" : "Принять"}</button>
              <button className="btn min-h-[48px] touch-manipulation bg-white/10 py-3.5 text-white hover:bg-white/20" disabled={!!busy} onClick={() => respond(false)}>{busy === "decline" ? "Отправляем…" : "Отклонить"}</button>
            </div>
          ) : (
            <p className="mt-4 rounded-xl bg-white/10 px-3 py-2.5 text-sm">
              {g.stage === "accepted" ? "Вы приняли приглашение: работодатель получил контакты, профиль передан в кадровую систему. На большом экране это видно." : "Вы отклонили приглашение. Работодатель увидит отказ, контакты останутся скрытыми."}
            </p>
          )}
          {error && <p className="mt-2 text-sm text-brand-blush">{error}</p>}
        </section>
      ) : (
        <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">Мини-тест завершён</h1>
      )}

      <div className="card mt-4 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Экспресс-категория</p>
        <p className="mt-1 text-xl font-extrabold text-brand-night">{r?.category_title ?? catTitle(r?.category_id)}</p>
        <p className="mt-1 text-sm text-brand-ink/75"><b>{r?.correct} из {r?.answered}</b> верно · θ = {num(r?.theta)} ± {plain(r?.se)}</p>
        {!!r?.skills?.length && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {r.skills.map((s) => <span key={s.tag} className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${s.score >= 0.5 ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500"}`}>{s.title}</span>)}
          </div>
        )}
        <p className="mt-2 text-xs leading-relaxed text-brand-ink/65">
          {r?.capped ? "Ответы сильные, но за 3 задания категория — не выше Middle: Senior подтверждает полный тест (8–16 заданий) или экспресс (8–12). " : "За 3 задания категория — не выше Middle. "}
          Погрешность велика — это предварительная оценка, полный тест уточняет грейд.
        </p>
      </div>

      <ol className="card mt-4 space-y-4 p-4" aria-label="Что происходит у работодателя">
        <Step done title="Категория присвоена, факты записаны в профиль (T1)" active={false} />
        <Step done={selected} active={!selected} title={selected && sel ? (sel.rank != null ? `В подборке работодателя: место ${sel.rank} из ${sel.total}` : `Подборка работодателя пересчитана, кандидатов: ${sel.total}`) : "Работодатель пересчитывает подборку…"}>
          {selected && sel ? <>Потребность «{sel.need_title.replace("Живая демонстрация: ", "")}», версия подборки {sel.version}</> : null}
        </Step>
        <Step done={invited} active={selected && !invited} title={invited ? "Приглашение отправлено" : selected && g.invite_failed ? "Приглашение не отправлено — скажите об этом докладчику" : selected ? "Работодатель отправляет приглашение…" : "Приглашение"}>
          {invited && inv ? (inv.push?.delivered ? "Push доставлен на этот телефон" : push.on ? "Push отправлен на этот телефон" : "Без push: страница обновилась сама") : null}
        </Step>
      </ol>

      {sel && selected && (
        <div className="card mt-4 p-4">
          <button className="flex min-h-[44px] w-full items-center justify-between text-left text-sm font-bold text-brand-night" onClick={() => setWhy(!why)} aria-expanded={why}>
            Почему вы в подборке <span className="text-brand">{why ? "Скрыть" : "Показать"}</span>
          </button>
          {why && (
            <ul className="mt-3 space-y-2">
              {sel.reasons.map((x, i) => (
                <li key={i} className="flex items-start gap-2 text-xs leading-relaxed text-brand-ink/80"><Level level={x.level} /><span><b>{x.requirement}.</b> {ruText(x.text)}</span></li>
              ))}
            </ul>
          )}
        </div>
      )}
      {invited && inv?.evidence && (
        <div className="card mt-4 p-4">
          <p className="text-sm font-bold text-brand-night">Доказательства в приглашении</p>
          <ul className="mt-2 space-y-1.5">
            {inv.evidence.map((e, i) => <li key={i} className="flex items-start gap-2 text-xs text-brand-ink/80"><Level level={e.level} /><span>{ruText(e.text)}</span></li>)}
          </ul>
          {inv.trust && (
            <p className="mt-3 text-xs leading-relaxed text-brand-ink/65">
              Индекс доверия работодателя — {inv.trust.score} из 100{inv.trust.preliminary ? ", предварительный" : ""} ({inv.trust.level_title.toLowerCase()}): {inv.trust.summary}.
              {inv.trust.offer_salary ? ` ${inv.trust.offer_salary.text.charAt(0).toUpperCase()}${inv.trust.offer_salary.text.slice(1)}.` : ""}
            </p>
          )}
        </div>
      )}
      {!invited && (push.note ? <p className="mt-3 text-xs text-brand-ink/65">{push.note}</p> : <IosHint />)}
      {FINAL.has(g.stage) && <button className="btn-ghost mt-5 w-full" onClick={onAgain}>Пройти ещё раз другим направлением</button>}
    </div>
  );
}
