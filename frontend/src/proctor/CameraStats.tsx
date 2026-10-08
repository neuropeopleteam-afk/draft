/** Кабинет ФСП: обезличенные агрегаты по камере во время теста (группы меньше 5 скрыты). */
import { useApi } from "../components/ui";
import { useMeta } from "../lib/meta";

interface Stats {
  period_days: number | null; k_min: number; tests_finished: number; enabled: boolean;
  modes: Record<string, number | null>; without_record: number | null; camera_share: number | null;
  camera_with_remarks: number | null; camera_remarks_share: number | null; remark_kinds: Record<string, number | null>;
  observed_min_median: number | null; note: string;
}

const n = (v: number | null | undefined, k: number) => (v == null ? `меньше ${k}` : v.toLocaleString("ru-RU"));
const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)} %`);

export function CameraStats({ days }: { days: number | null }) {
  const meta = useMeta();
  const st = useApi<Stats>(meta?.proctor_camera === false ? null : `/proctor/stats${days ? `?days=${days}` : ""}`, [days]);
  if (meta?.proctor_camera === false || !st.data) return null;
  const s = st.data, m = s.modes;
  const noKeys = ["declined", "unsupported", "denied"];
  const noSum = noKeys.reduce((a, k) => a + (m[k] ?? 0), 0);
  const noCamera = noKeys.some((k) => m[k] === null) ? (noSum ? `${noSum} и ещё меньше ${s.k_min}` : `меньше ${s.k_min}`) : noSum.toLocaleString("ru-RU");
  return (
    <section className="card min-w-0 space-y-3" data-testid="camera-stats">
      <div>
        <h2 className="text-lg font-bold text-brand-night">Камера во время теста</h2>
        <p className="mt-1 text-sm text-brand-ink/65">По согласию кандидата; на оценку не влияет. Завершённых тестов за период: {s.tests_finished.toLocaleString("ru-RU")}.</p>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-brand-ink/65">С камерой</dt><dd className="font-bold tabular-nums text-brand-night">{n(m.camera, s.k_min)}{s.camera_share != null ? ` (${pct(s.camera_share)})` : ""}</dd></div>
        <div><dt className="text-xs text-brand-ink/65">Без камеры</dt><dd className="font-bold tabular-nums text-brand-night">{noCamera}</dd></div>
        <div><dt className="text-xs text-brand-ink/65">С камерой, есть замечания</dt><dd className="font-bold tabular-nums text-brand-night">{n(s.camera_with_remarks, s.k_min)}{s.camera_remarks_share != null ? ` (${pct(s.camera_remarks_share)})` : ""}</dd></div>
        <div><dt className="text-xs text-brand-ink/65">Медиана наблюдения</dt><dd className="font-bold tabular-nums text-brand-night">{s.observed_min_median != null ? `${s.observed_min_median.toLocaleString("ru-RU")} мин` : "—"}</dd></div>
      </dl>
      <p className="text-xs text-brand-ink/65">{s.note}</p>
    </section>
  );
}
