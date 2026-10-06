// Сводка прогона Playwright в Markdown (для $GITHUB_STEP_SUMMARY и отчётов):
//   node scripts/summary.mjs reports/results.json "стенд https://…"
import { existsSync, readFileSync } from "node:fs";

const [file = "reports/results.json", target = ""] = process.argv.slice(2);
const out = [`### Сквозные сценарии${target ? ` · ${target}` : ""}`, ""];
if (!existsSync(file)) {
  out.push(`Файл ${file} не найден: прогон не дошёл до тестов (см. журнал шага).`);
} else {
  const r = JSON.parse(readFileSync(file, "utf8"));
  const rows = [];
  const walk = (suite, path) => {
    for (const spec of suite.specs ?? []) {
      for (const t of spec.tests) {
        const last = t.results.at(-1);
        const note = (t.annotations ?? []).filter((a) => a.type === "ответов").map((a) => `ответов: ${a.description}`);
        rows.push(`| ${last?.status === "passed" ? "прошёл" : last?.status ?? t.status} | ${path} › ${spec.title} | ` +
          `${((last?.duration ?? 0) / 1000).toFixed(1)} с | ${note.join("; ")} |`);
      }
    }
    for (const s of suite.suites ?? []) walk(s, path || s.title);
  };
  for (const s of r.suites) walk(s, s.title);
  const st = r.stats;
  out.push(`Итог: прошло **${st.expected}**, упало **${st.unexpected}**, нестабильных ${st.flaky}, пропущено ${st.skipped}; ` +
    `время ${(st.duration / 1000 / 60).toFixed(1)} мин.`, "", "| Статус | Сценарий | Время | Примечание |", "|---|---|---:|---|", ...rows);
}
console.log(out.join("\n") + "\n");
