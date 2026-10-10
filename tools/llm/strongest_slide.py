"""Я2: слайд для презентации из docs/llm/strongest.json — таблица «функция × модель: качество [интервал], отказы,
p50/p95, $ за 1000», рекомендация (основная, резерв, открытая, правила) и график «качество против цены».

Запуск (нужен matplotlib — системный python3 песочницы):
    python3 tools/llm/strongest_slide.py --out /home/user/workspace/spectrek/reports_0910/rullm_slide
→ rullm_slide.md и rullm_slide.png. Числа — только из JSON; подпись — «оценка моделью по эталону из трёх моделей —
модель, не люди».
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "llm" / "strongest.json"
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


def fails(r: dict) -> str:
    bad = r["calls"] - round((r["ok_share"]["value"] or 0) * r["calls"])
    return f"{bad} из {r['calls']}" + (f" (тайм-аутов {r['timeouts']})" if r.get("timeouts") else "")


def md(d: dict) -> str:
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
    out += ["", "## Рекомендация (модель стенда меняется только решением владельца, выкладка 5)", "",
            "| Функция | Основная (сильнейшая в пределах задержки) | В пределах шума | Резерв другой семьи | Лучшая открытая | Затем |",
            "|---|---|---|---|---|---|"]
    for f, ch in d["choice"].items():
        out.append(f"| {FUNC_RU.get(f, f)} | {label(d, ch['strongest_within_latency'])} | "
                   f"{', '.join(label(d, m) for m in ch['within_noise']) or '—'} | "
                   f"{label(d, ch['reserve_other_family']) if ch['reserve_other_family'] else '—'} | "
                   f"{label(d, ch['best_open']) if ch['best_open'] else '—'} | {ch['then']} |")
    out += ["", "Сводная оценка: качество 0,5 · надёжность 0,25 · задержка 0,15 · цена 0,1. «В бюджете» — p95 не больше "
            "тайм-аута стенда (разбор и резюме 25 с, оценка 50 с) и успешных ответов не меньше 90 %.", "",
            "Условия: " + " ".join(d.get("conditions") or []), ""]
    if d.get("pending"):
        out += ["Ещё не замерено: " + d["pending"], ""]
    out += ["![Качество против цены](rullm_slide.png)", ""]
    return "\n".join(out)


def png(d: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    funcs = [f for f in ("parse_need", "resume", "grade") if f in d["functions"]]
    fig, axes = plt.subplots(1, len(funcs), figsize=(5.2 * len(funcs), 4.8), dpi=160)
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
        rq = (d.get("functions_rules") or {}).get(f)
        if rq and rq["quality"]["index"]["value"] is not None:
            ax.axhline(rq["quality"]["index"]["value"], color="#888888", ls="--", lw=1)
            ax.text(0.99, rq["quality"]["index"]["value"], "правила (без LLM)", fontsize=7, color="#666666",
                    va="bottom", ha="right", transform=ax.get_yaxis_transform())
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
        placed = []
        for m, x, y in sorted(pts, key=lambda p: -p[2]):
            star = m == ch.get("strongest_within_latency")
            for dy in [3, -14, 14, -26, 26, -38, 38, -50, 50, -62]:
                t = ax.annotate(label(d, m) + (" ★" if star else ""), (x, y), xytext=(5, dy), textcoords="offset points",
                                fontsize=7, fontweight="bold" if star else "normal", color="#222222",
                                arrowprops=None if dy == 3 else dict(arrowstyle="-", color="#aaaaaa", lw=0.5))
                bb = t.get_window_extent(rend).expanded(1.02, 1.1)
                if not any(bb.overlaps(o) for o in placed):
                    placed.append(bb)
                    break
                t.remove()
            else:
                placed.append(bb)
                ax.add_artist(t)
        ax.set_title(FUNC_RU.get(f, f), fontsize=11)
        ax.set_xlabel("$ за 1000 вызовов (лог. шкала)", fontsize=9)
        ax.grid(alpha=0.25)
        ax.tick_params(labelsize=8)
    axes[0].set_ylabel("Индекс качества [90 %]", fontsize=9)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=fam) for fam, c in fam_color.items()]
    handles.append(plt.Line2D([], [], marker="o", ls="", color="#444444", mfc="white", label="вне бюджета стенда"))
    fig.legend(handles=handles, loc="lower center", ncol=min(6, len(handles)), fontsize=8, frameon=False)
    fig.suptitle(f"Качество против цены по функциям — замер {d['date']}", fontsize=13)
    fig.text(0.5, 0.075, CAPTION + " ★ — сильнейшая в пределах задержки.", ha="center", fontsize=8, color="#444444")
    fig.tight_layout(rect=(0, 0.11, 1, 0.95))
    fig.savefig(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", required=True, help="путь без расширения: <out>.md и <out>.png")
    a = ap.parse_args()
    d = json.loads(Path(a.src).read_text(encoding="utf-8"))
    out = Path(a.out)
    out.with_suffix(".md").write_text(md(d), encoding="utf-8")
    png(d, out.with_suffix(".png"))
    print("→", out.with_suffix(".md"), out.with_suffix(".png"))


if __name__ == "__main__":
    main()
