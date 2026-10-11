"""Слайд для презентации из backend/app/modules/validation/data/strongest.json — таблица «функция × модель: качество [интервал], отказы,
p50/p95, $ за 1000», рекомендация (основная, резерв, открытая, правила) и график «качество против цены».

Запуск (нужен matplotlib):
    python3 tools/llm/strongest_slide.py --out /tmp/strongest_slide
→ strongest_slide.md и strongest_slide.png. Числа — только из JSON; подпись — «оценка моделью по эталону из трёх моделей —
модель, не люди».
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend/app/modules/validation/data/strongest.json"
FUNC_RU = {"parse_need": "Разбор потребности", "resume": "Разбор резюме", "grade": "Оценка развёрнутых ответов"}
CAPTION = "Оценка моделью по эталону из трёх моделей — модель, не люди. Интервал — бутстреп 90 % по входам."


def n(x, d=3):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def label(d: dict, key: str) -> str:
    if key == "rules":
        return "Правила (без LLM)"
    meta = d["models"].get(key) or d["models"].get(key.split("@")[0]) or {}
    name = (meta.get("name") or key).split(": ", 1)[-1]
    return name + (f" ({key.split('@', 1)[1]})" if "@" in key else "")


SHORT = {"anthropic/claude-sonnet-5.5": "Sonnet 5.5", "anthropic/claude-opus-5.5": "Opus 5.5",
         "anthropic/claude-fable-5.1": "Fable 5.1", "openai/gpt-6.1-sol-pro": "Sol Pro", "openai/gpt-6-astra-pro": "Astra Pro",
         "x-ai/grok-4.7": "Grok 4.7", "google/gemini-3.1-pro-preview": "Gemini 3.1", "moonshotai/kimi-k3": "Kimi K3",
         "z-ai/glm-5.3": "GLM 5.3", "qwen/qwen3.8-27b": "Qwen-27B", "qwen/qwen3.8-2.4t-a95b": "Qwen-2.4T",
         "deepseek/deepseek-v4-pro-0813": "DeepSeek V4"}


def short(d: dict, key: str) -> str:
    return SHORT.get(key.split("@")[0]) or label(d, key)


def fails(r: dict) -> str:
    bad = r["calls"] - round((r["ok_share"]["value"] or 0) * r["calls"])
    return f"{bad} из {r['calls']}" + (f" (тайм-аутов {r['timeouts']})" if r.get("timeouts") else "")


def md(d: dict, png_name: str = "strongest_slide.png") -> str:
    out = [f"# Сильнейшие модели по функциям — замер {d['date']} (код {d['code_sha']})", "",
           f"_{CAPTION}_", "",
           "| Функция | Модель | Качество [90 %] | Отказы | p50 / p95, с | $ за 1000 | В бюджете стенда |",
           "|---|---|---|---|---|---|---|"]
    for f, cells in d["functions"].items():
        ch = d["choice"].get(f, {})
        for m, c in sorted(cells.items(), key=lambda kv: -(kv[1]["quality"]["index"]["value"] or 0)):
            q, r = c["quality"]["index"], c["reliability"]
            mark = " **(выбор)**" if m == ch.get("strongest_within_latency") else ""
            out.append(f"| {FUNC_RU.get(f, f)} | {label(d, m)}{mark} | {n(q['value'])} "
                       f"[{n((q.get('ci90') or [None])[0])}–{n((q.get('ci90') or [None, None])[1])}] | {fails(r)} | "
                       f"{n(r['p50_s'], 1)} / {n(r['p95_s'], 1)} | {n(c['usd_per_1k'], 2)} | "
                       f"{'да' if c['within_budget'] else 'нет'} |")
        rq = (d.get("functions_rules") or {}).get(f)
        if rq:
            q = rq["quality"]["index"]
            out.append(f"| {FUNC_RU.get(f, f)} | Правила (без LLM) | {n(q['value'])} [{n(q['ci90'][0])}–{n(q['ci90'][1])}] | "
                       f"0 | < 0,1 | 0 | да |")
    out += ["", "## Рекомендация (модель стенда меняется отдельным решением, не этим замером)", "",
            "| Функция | Основная (сильнейшая в пределах задержки) | В пределах шума | Резерв другой семьи | Лучшая открытая | Затем |",
            "|---|---|---|---|---|---|"]
    for f, ch in d["choice"].items():
        out.append(f"| {FUNC_RU.get(f, f)} | {label(d, ch['strongest_within_latency'])} | "
                   f"{', '.join(label(d, m) for m in ch['within_noise']) or '—'} | "
                   f"{label(d, ch['reserve_other_family']) if ch['reserve_other_family'] else '—'} | "
                   f"{label(d, ch['best_open']) if ch['best_open'] else '—'} | {ch['then']} |")
    for f, ch in d["choice"].items():
        if ch.get("full_run_rejected"):
            out += ["", f"**Полный прогон ({FUNC_RU.get(f, f)}, все входы) исключил:** " + "; ".join(
                f"{label(d, x['model'])} — {x['why']}" for x in ch["full_run_rejected"]) +
                f" (лидер малой выборки — {label(d, ch['small_sample_leader'])}); основная в полном прогоне: "
                f"{ch.get('main_full_run') or '—'}."]
    out += ["", "Сводная оценка: качество 0,5 · надёжность 0,25 · задержка 0,15 · цена 0,1. «В бюджете» — p95 не больше "
            "тайм-аута стенда (разбор и резюме 25 с, оценка 50 с) и успешных ответов не меньше 90 %.", "",
            "Условия: " + " ".join(d.get("conditions") or []), ""]
    if d.get("pending"):
        out += ["Ещё не замерено: " + d["pending"], ""]
    out += [f"![Качество против цены]({png_name})", ""]
    return "\n".join(out)


def png(d: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.transforms  # noqa: F401

    funcs = [f for f in ("parse_need", "resume", "grade") if f in d["functions"]]
    fig, axes = plt.subplots(1, len(funcs), figsize=(5.6 * len(funcs), 5.2), dpi=160)
    axes = [axes] if len(funcs) == 1 else list(axes)
    fam_color = {}
    palette = ["#4B3FD1", "#D14B3F", "#1F9D6B", "#C98A00", "#7A4FA0", "#2C7FB8", "#B84F7A", "#5E6B2C", "#444444"]
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    for ax, f in zip(axes, funcs):
        cells = d["functions"][f]
        ch = d["choice"].get(f, {})
        pts = []
        for m, c in cells.items():
            q = c["quality"]["index"]
            x = c["usd_per_1k"]
            if q["value"] is None or not x:
                continue
            fam = (d["models"].get(m) or d["models"].get(m.split("@")[0]) or {}).get("family", "?")
            col = fam_color.setdefault(fam, palette[len(fam_color) % len(palette)])
            lo, hi = (q.get("ci90") or [q["value"], q["value"]])
            ax.errorbar([x], [q["value"]], yerr=[[q["value"] - lo], [hi - q["value"]]], fmt="o", color=col,
                        mfc=col if c["within_budget"] else "white", ms=7, capsize=2, lw=1)
            pts.append((m, x, q["value"]))
        ys = [p[2] for p in pts] + [lo for m in cells for lo in ((cells[m]["quality"]["index"].get("ci90") or [None])[:1])
                                     if lo is not None]
        rq = (d.get("functions_rules") or {}).get(f)
        rv = rq["quality"]["index"]["value"] if rq else None
        if ys:
            y0 = min(ys) - 0.006
            if rv is not None and rv >= y0 - 0.012:
                y0 = min(y0, rv - 0.004)
            his = [hi for m in cells for hi in ((cells[m]["quality"]["index"].get("ci90") or [None, None])[1:])
                   if hi is not None] + [p[2] for p in pts]
            ax.set_ylim(y0, min(1.003, max(his) + 0.005))
        if rv is not None:
            if rv >= ax.get_ylim()[0]:
                ax.axhline(rv, color="#888888", ls="--", lw=1)
                ax.text(0.99, rv, "правила (без LLM)", fontsize=7, color="#666666", va="bottom", ha="right",
                        transform=ax.get_yaxis_transform())
            else:
                ax.text(0.99, 0.02, f"правила (без LLM): {rv:.3f}".replace(".", ",") + " — ниже шкалы", fontsize=7,
                        color="#666666", ha="right", transform=ax.transAxes)
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2f}".replace(".", ",")))
        xs = [p[1] for p in pts]
        if xs:
            ax.set_xlim(min(xs) / 1.6, max(xs) * 2.6)
        # подписи без наложения: сверху вниз по качеству, сдвиг вниз, пока рамка пересекается с уже поставленными
        fig.canvas.draw()
        rend = fig.canvas.get_renderer()
        axbb = ax.get_window_extent(rend)
        placed = []
        for _, x, y in pts:  # маркеры — тоже препятствия для подписей
            px, py = ax.transData.transform((x, y))
            placed.append(matplotlib.transforms.Bbox([[px - 5, py - 5], [px + 5, py + 5]]))
        cands = [(5, 3, "left"), (-5, 3, "right"), (5, -11, "left"), (-5, -11, "right"), (5, 14, "left"),
                 (-5, 14, "right"), (5, -22, "left"), (-5, -22, "right"), (5, 25, "left"), (-5, 25, "right"),
                 (5, -33, "left"), (-5, -33, "right"), (5, 36, "left"), (-5, 36, "right")]
        unplaced: list[str] = []
        for m, x, y in sorted(pts, key=lambda p: -p[2]):
            star = m == ch.get("strongest_within_latency")
            best = None
            for dx, dy, ha in cands:
                t = ax.annotate(short(d, m) + (" ★" if star else ""), (x, y), xytext=(dx, dy), textcoords="offset points",
                                ha=ha, fontsize=7, fontweight="bold" if star else "normal", color="#222222",
                                arrowprops=None if abs(dy) <= 3 else dict(arrowstyle="-", color="#aaaaaa", lw=0.5))
                bb = t.get_window_extent(rend).expanded(1.02, 1.08)
                inside = axbb.x0 <= bb.x0 and bb.x1 <= axbb.x1 and axbb.y0 <= bb.y0 and bb.y1 <= axbb.y1
                if inside and not any(bb.overlaps(o) for o in placed):
                    best = bb
                    break
                t.remove()
            if best is None:  # места нет — номер у точки, имя — в сноске внутри графика
                unplaced.append(short(d, m) + (" ★" if star else ""))
                t = ax.annotate(str(len(unplaced)), (x, y), xytext=(4, 2), textcoords="offset points", fontsize=7,
                                color="#222222")
                best = t.get_window_extent(rend)
            placed.append(best)
        if unplaced:
            ax.text(0.02, 0.02, "\n".join(f"{i}. {n}" for i, n in enumerate(unplaced, 1)), fontsize=6.5,
                    color="#333333", transform=ax.transAxes, va="bottom",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#dddddd", alpha=0.9))
        ax.set_title(FUNC_RU.get(f, f), fontsize=11)
        ax.set_xlabel("$ за 1000 вызовов (лог. шкала)", fontsize=9)
        ax.grid(alpha=0.25)
        ax.tick_params(labelsize=8)
    axes[0].set_ylabel("Индекс качества [90 %]", fontsize=9)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=fam) for fam, c in fam_color.items()]
    handles.append(plt.Line2D([], [], marker="o", ls="", color="#444444", mfc="white", label="вне бюджета стенда"))
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, 0.045))
    fig.suptitle(f"Качество против цены по функциям — замер {d['date']}", fontsize=13)
    fig.text(0.5, 0.012, CAPTION + " ★ — сильнейшая в пределах задержки.", ha="center", fontsize=8, color="#444444")
    fig.tight_layout(rect=(0, 0.1, 1, 0.95))
    fig.savefig(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", required=True, help="путь без расширения: <out>.md и <out>.png")
    a = ap.parse_args()
    d = json.loads(Path(a.src).read_text(encoding="utf-8"))
    out = Path(a.out)
    out.with_suffix(".md").write_text(md(d, out.with_suffix(".png").name), encoding="utf-8")
    png(d, out.with_suffix(".png"))
    print("→", out.with_suffix(".md"), out.with_suffix(".png"))


if __name__ == "__main__":
    main()
