import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { getCheatBots, type CheatRow } from "../../lib/numbers";

/** «Обмани тест» (А4, 21.10): боты-стратегии проходят НАСТОЯЩИЙ тест — тот же движок, реальные варианты заданий,
 *  реальная проверка ответа, второй этап у границы. Таблица — отчётный прогон (docs/NUMBERS.json → cheat_bots),
 *  кнопка — живая попытка бота прямо сейчас на сервере (/api/validation/cheat-challenge/attempt). Чисел в коде нет. */

const LABELS: Record<string, { title: string; desc: string }> = {
  control: { title: "Контроль: честный, но слабее заявки", desc: "отвечает по своим знаниям, уровень на три четверти ступени ниже порога заявленного грейда" },
  random: { title: "Случайные ответы", desc: "случайный вариант, случайная строка кода, пустой вывод" },
  position_A: { title: "Всегда первый вариант", desc: "проверка, нет ли перекоса в позиции правильного ответа" },
  position_B: { title: "Всегда второй вариант", desc: "то же для позиции B" },
  position_C: { title: "Всегда третий вариант", desc: "то же для позиции C" },
  position_D: { title: "Всегда четвёртый вариант", desc: "то же для позиции D" },
  longest: { title: "Самый длинный вариант", desc: "«решатель без знаний»: правильный ответ часто подробнее" },
  median_number: { title: "Середина числового ряда", desc: "«решатель без знаний»: в задачах с числами берёт средний вариант" },
  overlap: { title: "Больше всего общих слов с условием", desc: "«решатель без знаний»: ищет вариант, похожий на текст задачи" },
  leak_10: { title: "Утечка: 10 вариантов каждого задания", desc: "знает ключи 10 вариантов каждого семейства, остальное — своими силами (как контроль)" },
  leak_100: { title: "Утечка: 100 вариантов каждого задания", desc: "знает ключи 100 вариантов каждого семейства, остальное — своими силами" },
};

const LIVE = ["random", "longest", "median_number", "overlap", "position_A", "leak_10", "control"];

interface LiveAttempt {
  at: string;
  strategy: string;
  claim: string;
  direction: string;
  verdict_main: string | null;
  grade_final: string;
  refined: boolean;
  false_confirmed: boolean;
  items: number;
  elapsed_s: number;
}

const pc = (v: number | null | undefined) => (v == null ? "—" : `${(Number(v) * 100).toFixed(1).replace(".", ",")} %`);
const GRADE: Record<string, string> = { none: "ниже Intern", intern: "Intern", junior: "Junior", middle: "Middle", senior: "Senior", lead: "Lead", principal: "Principal" };

export default function CheatChallenge({ compact = false }: { compact?: boolean }) {
  const cb = getCheatBots();
  const [live, setLive] = useState<LiveAttempt[]>([]);
  const [strategy, setStrategy] = useState("longest");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<{ attempts: LiveAttempt[] }>("/validation/cheat-challenge").then((r) => setLive(r?.attempts ?? [])).catch(() => setLive([]));
  }, []);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ latest: LiveAttempt; attempts: LiveAttempt[] }>("/validation/cheat-challenge/attempt", {
        method: "POST",
        body: { strategy },
      });
      setLive(r?.attempts ?? []);
    } catch (e: any) {
      setErr(e?.message || "Не удалось запустить попытку — попробуйте позже");
    } finally {
      setBusy(false);
    }
  };

  const rows: [string, CheatRow][] = cb ? Object.entries(cb.table) : [];
  return (
    <section id="v-cheat-challenge" className="mt-8 rounded-2xl bg-white p-5 ring-1 ring-brand-night/10" data-testid="v-cheat-challenge">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-extrabold text-brand-night">«Обмани тест»: боты проходят настоящий тест</h2>
        <span className="chip-lime">боты, не люди</span>
      </div>
      <p className="mt-2 text-sm text-brand-ink/70">
        Каждый бот проходит тот же тест, что и кандидат: реальные варианты заданий, реальная проверка ответа, второй этап у
        границы. Считаем, как часто продукт подтвердил боту заявленный грейд (Junior, Middle или Senior). Время ответа бот
        держит «как у человека», чтобы детектор скорости не помогал.
      </p>
      {rows.length > 0 ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs" data-testid="v-cheat-table">
            <thead>
              <tr className="text-left text-brand-ink/70">
                <th className="py-1 pr-3">Стратегия</th>
                <th className="pr-3">Попыток</th>
                <th className="pr-3">Грейд подтверждён</th>
                <th>95 % ДИ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([k, r]) => (
                <tr key={k} className="border-t border-black/5  align-top">
                  <td className="py-1 pr-3">
                    <div className="font-semibold text-brand-night">{LABELS[k]?.title || k}</div>
                    {!compact && <div className="text-brand-ink/70">{LABELS[k]?.desc}</div>}
                  </td>
                  <td className="pr-3">{r.n}</td>
                  <td className="pr-3 font-semibold text-brand-night">{pc(r.false_confirmed.value)} ({r.false_confirmed.k})</td>
                  <td>{r.false_confirmed.ci95 ? `${pc(r.false_confirmed.ci95[0])}–${pc(r.false_confirmed.ci95[1])}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {cb?.claim_ru && <p className="mt-2 text-xs text-brand-ink/70">{cb.claim_ru}</p>}
          <details className="mt-2 text-xs text-brand-ink/70">
            <summary className="cursor-pointer font-semibold text-brand-night">Условия и пересчёт</summary>
            <p className="mt-1">{cb?.meta?.text_answers}. Уровень бота с утечкой и контроля: {cb?.meta?.bot_theta}.</p>
            <p className="mt-1">Пересчёт: <code className="break-all">{cb?.recompute}</code>; код — <code>{cb?.code_ref}</code>.</p>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-sm text-brand-ink/70">Отчётный прогон ботов ещё не опубликован.</p>
      )}
      {!compact && (
        <div className="mt-4 rounded-xl border border-black/10 p-3 " data-testid="v-cheat-live">
          <div className="text-sm font-semibold text-brand-night">Запустить бота сейчас</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select className="input text-sm" value={strategy} onChange={(e) => setStrategy(e.target.value)} aria-label="Стратегия бота">
              {LIVE.map((s) => (
                <option key={s} value={s}>{LABELS[s]?.title || s}</option>
              ))}
            </select>
            <button className="btn-primary" onClick={run} disabled={busy} data-testid="v-cheat-run">
              {busy ? "Бот проходит тест…" : "Запустить попытку"}
            </button>
          </div>
          {err && <p className="mt-2 text-xs text-red-600">{err}</p>}
          {live.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-brand-ink/70">
              {live.slice(0, 8).map((a, i) => (
                <li key={i}>
                  <b className="text-brand-night">{LABELS[a.strategy]?.title || a.strategy}</b>, заявка {GRADE[a.claim] || a.claim}:{" "}
                  {a.false_confirmed ? "грейд подтверждён" : `не подтверждён (итог — ${GRADE[a.grade_final] || a.grade_final})`}
                  {a.refined ? ", был второй этап" : ""} · заданий {a.items} · {Math.round(a.elapsed_s)} с
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
