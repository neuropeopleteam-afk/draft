"""Качество оценщика открытых ответов на наборах замера «сильнейших моделей» одной командой — MAE, κw,
смещение, завышение/занижение, точная корзина, атаки, устойчивость (3 оценки) против эталона из моделей замера
(среднее Claude Opus 5.5 / Claude Fable 5.1 / GPT-6 Astra Pro без самой модели; пока их меньше двух — среднее всех
остальных моделей замера). Эталон — модели, не люди. Сеть не нужна: только сохранённые ответы.

    cd backend
    python ../tools/llm/grade_vs_reference.py /tmp/y13/openrouter_anthropic_claude_sonnet_5.5 --ref /tmp/strong [--json out.json]

<каталог> — то, что пишет strongest_bench.py run --funcs grade,grade_stab (g/v2_1_out.jsonl, g/stab_out.jsonl).
Входы те же, что у всех моделей замера (50 ответов: 5 на группу, 15 честных + 25 атак …; стабильность — 10 честных × 2).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics as st
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "llm"))

import strongest_quality as Q  # noqa: E402
import strongest_summary as S  # noqa: E402


def _model_of(d: Path) -> str | None:
    for f in ("grade", "grade_stab", "resume", "needs_delta"):
        j = S._load(d / f"{f}.json")
        if j and j.get("spec"):
            return j["spec"].split("=", 1)[1]
    return None


def reference(ref_dir: Path, exclude: str | None, exclude_dir: Path | None = None) -> tuple[dict, str]:
    """Эталон на входах выборки: среднее моделей эталона (без exclude), иначе — всех остальных моделей замера."""
    scores = {}
    for d in sorted(ref_dir.glob("openrouter_*")):
        if exclude_dir and d.resolve() == exclude_dir.resolve():
            continue
        m = _model_of(d)
        out = d / "g" / "v2_1_out.jsonl"
        if m == "anthropic/claude-sonnet-5.5" and (S.SONNET_DIR / "g" / "_sample_out.jsonl").exists():
            out = S.SONNET_DIR / "g" / "_sample_out.jsonl"  # Sonnet — тот же срез из полного прогона 09.10
        if m and out.exists():
            scores[m] = S._grade_scores(out)[0]
    pool = [j for j in S.JUDGES if j in scores and j != exclude]
    if len(pool) < 2:
        pool = [m for m in scores if m != exclude]
        note = "среднее всех остальных моделей замера: " + ", ".join(pool)
    else:
        note = "среднее " + ", ".join(pool) + " (без самой модели)"
    ref = {}
    for rid in set().union(*[set(scores[m]) for m in pool]) if pool else set():
        v = [scores[m][rid]["score"] for m in pool if rid in scores[m]]
        if v:
            ref[rid] = st.mean(v)
    return ref, note


def evaluate(run_dir: Path, ref_dir: Path) -> dict:
    model = _model_of(run_dir)
    out = run_dir / "g" / "v2_1_out.jsonl"
    if not out.exists():
        sys.exit(f"нет {out}: сначала strongest_bench.py run --funcs grade,grade_stab")
    sc, _ = S._grade_scores(out)
    _, calls = S._grade_raw(out)
    stab_p = run_dir / "g" / "stab_out.jsonl"
    stab = {}
    if stab_p.exists():
        st_sc, st_calls = S._grade_raw(stab_p, strip_rep=True)
        stab = {rid: [sc[rid]["score"]] + v for rid, v in st_sc.items() if rid in sc}
        calls += st_calls
    ref, note = reference(ref_dir, model, run_dir)
    q = Q.grade_quality(sc, ref, stab, None)
    return {"model": model, "dir": str(run_dir), "reference": note, "quality": q,
            "reliability": Q.reliability(calls, Q.BUDGET_S["grade"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--ref", default="/tmp/strong", help="каталог замера с моделями эталона")
    ap.add_argument("--json", default="", help="куда записать полный результат")
    a = ap.parse_args()
    r = evaluate(Path(a.run_dir), Path(a.ref))
    q, rel = r["quality"], r["reliability"]

    def f(m, d=3):
        return S._mv(m, d, ci=True)

    print(f"{r['model']}: эталон — {r['reference']}")
    print(f"  MAE {f(q['mae'])}; κw {f(q['kappa_w'])}; смещение {S._mv(q['bias'], sign=True)}; завышение "
          f"{S._mv(q['over_share'], pct=True)}, занижение {S._mv(q['under_share'], pct=True)}; точная корзина "
          f"{f(q['exact_bin'], 2)}")
    print(f"  атаки отбиты {S._mv(q['attacks_resisted'], pct=True)} из {q['attacks_n']} (помечены как манипуляция "
          f"{S._mv(q['attacks_flagged'], pct=True)}); размах 3 оценок {f(q['stability_range'], 2)}")
    print(f"  успешно {S._mv(rel['ok_share'], pct=True)} из {rel['calls']}; p50/p95 {rel['p50_s']}/{rel['p95_s']} с; "
          f"тайм-аутов при 50 с — {rel['timeouts']}; индекс качества (без судьи) {f(q['index'])}")
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print("→", a.json)


if __name__ == "__main__":
    main()
