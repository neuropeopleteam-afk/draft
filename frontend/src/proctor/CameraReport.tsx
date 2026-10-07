/**
 * Отчёт камеры для кандидата: итог так же, как его видит работодатель, плюс все свои события по заданиям
 * (работодателю события не показываются). На экране результата теста и в настройках (список попыток).
 */
import { useState } from "react";
import { Alert, DIRECTIONS, GRADES, Loading, dtt, errText, useApi } from "../components/ui";
import { api } from "../lib/api";
import { useMeta } from "../lib/meta";
import { ConsentBody, type ConsentState } from "./CameraConsent";

interface Summary { mode: "on" | "off"; title: string; remarks: string[]; notes: string[]; points?: number; totals?: Record<string, number> }
interface Ev { position: number; kind: string; title: string; duration_s: number; faces: number | null; counted: boolean; at: string | null }
interface Item { position: number; observed_s: number; time_s: number | null; no_face_s: number; multi_face_s: number; off_s: number }
interface View { mode: string | null; camera_active: boolean; windows: { from: number; to: number | null; mid?: boolean }[]; resumes: number; summary: Summary; events?: Ev[]; items?: Item[] }

const fmt = (s: number) => (s >= 60 ? `${Math.floor(s / 60)} мин ${Math.round(s % 60)} с` : `${s.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} с`);

/** Итог камеры по сессии теста — для экрана результата. */
export function CameraReport({ sessionId }: { sessionId: string }) {
  const meta = useMeta();
  const v = useApi<View>(meta?.proctor_camera === false ? null : `/proctor/sessions/${sessionId}`, [sessionId]);
  const [open, setOpen] = useState(false);
  if (meta?.proctor_camera === false) return null;
  if (v.loading) return <div className="mt-4"><Loading text="Итог камеры…" /></div>;
  if (!v.data) return null;
  const d = v.data, s = d.summary;
  const evs = d.events ?? [];
  return (
    <section className="card mt-4 text-sm" data-testid="camera-report">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-bold text-brand-night">{s.title}</p>
          <p className="mt-1 text-xs text-brand-ink/65">
            {s.mode === "on"
              ? `Так итог видит работодатель. Камера наблюдала ${d.summary.totals?.items_watched ?? 0} заданий, ${fmt(d.summary.totals?.observed_s ?? 0)}${d.resumes ? `, включалась снова после перезагрузки: ${d.resumes}` : ""}.`
              : "Так итог видит работодатель: нейтральная пометка, на оценку и грейд не влияет."}
          </p>
        </div>
        {s.mode === "on" && evs.length > 0 && (
          <button type="button" className="text-xs font-semibold text-brand hover:underline" onClick={() => setOpen((o) => !o)}>{open ? "Скрыть события" : `Мои события: ${evs.length}`}</button>
        )}
      </div>
      {s.remarks.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-brand-ink/85 marker:text-brand">{s.remarks.map((r, i) => <li key={i}>{r}</li>)}</ul>}
      {s.notes.length > 0 && <p className="mt-2 text-xs text-brand-ink/65">{s.notes.join(" · ")}</p>}
      {s.mode === "on" && evs.length === 0 && <p className="mt-2 text-xs text-brand-ink/65">Событий нет: на всех заданиях в кадре было одно лицо.</p>}
      {open && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-brand-ink/65"><th className="py-1 pr-3 font-medium">Задание</th><th className="py-1 pr-3 font-medium">Событие</th><th className="py-1 pr-3 font-medium">Длительность</th><th className="py-1 font-medium">Учтено</th></tr></thead>
            <tbody>
              {evs.map((e, i) => (
                <tr key={i} className="border-t border-brand-night/5">
                  <td className="py-1 pr-3 tabular-nums">{e.position}</td>
                  <td className="py-1 pr-3">{e.title}{e.kind === "multi_face" && e.faces ? ` (${e.faces})` : ""}</td>
                  <td className="py-1 pr-3 tabular-nums">{fmt(e.duration_s)}</td>
                  <td className="py-1 text-brand-ink/65">{e.counted ? "да" : "нет, короче порога"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-brand-ink/65">Работодателю события не показываются — только итог выше. Кадры не сохранялись.</p>
        </div>
      )}
    </section>
  );
}

/** Блок в настройках: согласие на камеру (текст, отзыв) и список попыток теста с режимом камеры. */
export function CameraSettings() {
  const meta = useMeta();
  const c = useApi<ConsentState>("/proctor/consent");
  const list = useApi<{ session_id: string; direction: string; claimed_grade: string; status: string; started_at: string | null; mode: string | null; events: number; summary: Summary }[]>("/proctor/me/sessions");
  const [text, setText] = useState(false);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  if (meta?.proctor_camera === false) return null;
  if (c.loading) return <Loading text="Согласие на камеру…" />;
  if (!c.data) return null;
  async function revoke() {
    setMsg(null);
    try {
      const r = await api<{ stopped_sessions: number }>("/proctor/consent", { method: "DELETE" });
      await c.reload();
      setMsg({ k: "ok", t: r.stopped_sessions ? "Согласие отозвано, камера в текущем тесте выключена — он продолжается без камеры." : "Согласие отозвано. Перед следующим тестом камеру можно будет включить снова, дав согласие заново." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  const d = c.data;
  return (
    <section className="card" data-testid="camera-settings">
      <h2 className="font-bold text-brand-night">Камера во время теста</h2>
      <p className="mt-1 text-sm text-brand-ink/65">По желанию, перед каждым тестом выбор заново. Кадры не сохраняются; работодатель видит только итог рядом с достоверностью результата.</p>
      {msg && <div className="mt-3"><Alert kind={msg.k}>{msg.t}</Alert></div>}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-night/10 p-4 text-sm">
        <div>
          <p className="font-semibold">{d.text.title}</p>
          <p className="text-brand-ink/65">
            {d.active ? `Дано ${dtt(d.granted_at)}, редакция ${d.version}${d.version !== d.current_version ? ` (текущая ${d.current_version})` : ""}` : "Не дано — спрашивается на экране перед тестом"}
            {" · "}<button type="button" className="font-semibold text-brand hover:underline" onClick={() => setText((t) => !t)}>{text ? "скрыть текст" : "текст"}</button>
          </p>
        </div>
        {d.active && <button className="btn-ghost" onClick={revoke}>Отозвать</button>}
      </div>
      {text && <div className="mt-3 rounded-xl bg-[#F3F2FB] p-4"><ConsentBody t={d.text} compact /></div>}
      {list.data && list.data.length > 0 && (
        <ul className="mt-4 space-y-2 text-sm">
          {list.data.map((s) => (
            <li key={s.session_id} className="flex flex-wrap items-center justify-between gap-2 border-t border-brand-night/5 pt-2">
              <span className="text-brand-ink/80">{s.started_at ? dtt(s.started_at) : "—"} · {DIRECTIONS[s.direction] ?? s.direction} · {GRADES[s.claimed_grade] ?? s.claimed_grade}</span>
              <span className="text-xs font-semibold text-brand-night">{s.summary.title}{s.summary.remarks.length ? `: ${s.summary.remarks.join("; ")}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
