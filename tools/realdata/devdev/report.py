"""Отчёт по прогону «один в один» на генераторе Dev_dev: docs/realdata/devdev_1to1.json → DEVDEV_1TO1.md и блок для
docs/NUMBERS.json (docs/realdata/numbers_devdev.json). Все числа — из JSON прогона.

  python3 tools/realdata/devdev/report.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "docs/realdata/devdev_1to1.json"
MD = ROOT / "docs/realdata/DEVDEV_1TO1.md"
NUM = ROOT / "docs/realdata/numbers_devdev.json"
NAMES = {"p5": "P@5", "p10": "P@10", "ndcg10": "nDCG@10", "rr": "MRR", "overrated10": "переоценённых в топ-10"}


def f(x: float, pct: bool) -> str:
    return (f"{x * 100:.1f} %" if pct else f"{x:.3f}").replace(".", ",")


def ci(v: list[float], pct: bool) -> str:
    return f"[{f(v[0], pct)}; {f(v[1], pct)}]"


def dpp(x: float, pct: bool) -> str:
    return (f"{x * 100:+.1f} п.п." if pct else f"{x:+.3f}").replace(".", ",", 1).replace("п,п.", "п.п.")


def cipp(v: list[float], pct: bool) -> str:
    return f"[{dpp(v[0], pct)}; {dpp(v[1], pct)}]"


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    pool, s26 = d["pooled"], d["per_seed"]["2026"]
    cond = (f"синтетика (модель, не люди): открытый генератор Dev_dev (MIT, коммит {d['their_commit'][:8]}), "
            f"{len(d['seeds'])} отложенных зёрен × 40 вакансий × 1000 кандидатов ({d['n_vacancies']} вакансий), их тест и "
            f"их метки; наш подбор — четвёртой выдачей в их процедуре; один прогон {d['run_at'][:10]}, код "
            f"{d['git_head'][:9]}, FREEZE {d['freeze_sha256'][:8]}")
    L = ["# «Один в один» на открытом генераторе Dev_dev — итог прогона", "",
         f"Условия: {cond}. Протокол — `docs/realdata/DEVDEV_PROTOCOL.md`; команда — `{d['recompute']}`.", "",
         "## Главная строка (main): конфигурация финального стенда, выбор работодателя по умолчанию", "",
         "| метрика | наш подбор | 95 % ДИ | IT Match | разность (парная) | 95 % ДИ |", "|---|---|---|---|---|---|"]

    def rows(row: str) -> list[str]:
        out = []
        for m, nm in NAMES.items():
            x = pool[row][m]
            pct = m != "ndcg10"
            out.append(f"| {nm} | {f(x['ours'], pct)} | {ci(x['ours_ci'], pct)} | {f(x['it_match'], pct)} | "
                       f"{dpp(x['diff'], pct)} | {cipp(x['diff_ci'], pct)} |")
        return out

    L += rows("main")
    L += ["", "MRR у их отчёта нет — посчитан нами той же процедурой для обеих выдач (справочно).", "",
          "## При выборе работодателем «строго запрошенный грейд» (exact) — рядом с main, с ценой", "",
          "Опция и её вариант (C — порядок по вероятности «уровень именно запрошенный») созданы и выбраны на зёрнах "
          "разработки 1–3 этого же генератора. Цена — больше кандидатов с истинным грейдом ниже вакансии в топ-10. "
          "Сейчас это опция API подборки (`filters.grade_exact`), переключателя на экране подборки нет.", "",
          "| метрика | наш подбор | 95 % ДИ | IT Match | разность (парная) | 95 % ДИ |", "|---|---|---|---|---|---|"]
    L += rows("exact")
    L += ["", "## Зерно 2026 (их опубликованный отчёт) — отдельно", "",
          "| выдача | P@5 | P@10 | nDCG@10 | переоценённых |", "|---|---|---|---|---|"]
    t = s26["their"]
    for name, x in t.items():
        L.append(f"| {name} (их код) | {f(x['p5'], 1)} | {f(x['p10'], 1)} | {f(x['ndcg10'], 0)} | {f(x['overrated10'], 1)} |")
    for row, nm in (("main", "наш подбор, main"), ("exact", "наш подбор, «строго запрошенный грейд»"),
                    ("base", "наш подбор без расширения каталога")):
        x = s26[row]["ours"]
        L.append(f"| {nm} | {f(x['p5'], 1)} | {f(x['p10'], 1)} | {f(x['ndcg10'], 0)} | {f(x['overrated10'], 1)} |")
    L += ["", "## По зёрнам (nDCG@10)", "", "| зерно | IT Match | main | exact | base |", "|---|---|---|---|---|"]
    for s, v in d["per_seed"].items():
        L.append(f"| {s} | {f(v['their']['IT Match']['ndcg10'], 0)} | {f(v['main']['ours']['ndcg10'], 0)} | "
                 f"{f(v['exact']['ours']['ndcg10'], 0)} | {f(v['base']['ours']['ndcg10'], 0)} |")
    L += ["", "## Как читать", "",
          "* На их генераторе их метка считает кандидата на грейд выше «частично подходящим» (1); наша основная метка — "
          "«подходит» (работодатель не теряет). Поэтому в выборе по умолчанию наш подбор чаще ставит в топ сильнее "
          "запроса и уступает по их метрике; при выборе «строго запрошенный грейд» — выше их по P@5, P@10, nDCG@10 и "
          "MRR, но с большей долей кандидатов ниже запроса в топ-10.",
          "* base — без расширения каталога (нет направлений «мобильная разработка», DevOps и грейда Lead): их вакансии "
          "этих направлений наш базовый каталог не различает — справочно.", ""]
    MD.write_text("\n".join(L), encoding="utf-8")
    num = {"devdev_1to1": {
        "condition": cond, "recompute": d["recompute"], "source": "docs/realdata/devdev_1to1.json",
        "main": {m: {k: pool["main"][m][k] for k in ("ours", "ours_ci", "it_match", "diff", "diff_ci")} for m in NAMES},
        "exact_option_api": {m: {k: pool["exact"][m][k] for k in ("ours", "ours_ci", "it_match", "diff", "diff_ci")}
                             for m in NAMES},
        "seed_2026": {"it_match": t["IT Match"], "main": s26["main"]["ours"], "exact": s26["exact"]["ours"]},
        "note": "exact — только при выборе работодателем «строго запрошенный грейд» (опция API, создана и выбрана на "
                "зёрнах разработки 1–3 этого генератора); главная строка — main"}}
    NUM.write_text(json.dumps(num, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(MD.relative_to(ROOT), NUM.relative_to(ROOT))


if __name__ == "__main__":
    main()
