"""Вывести из выдачи семейства, у которых ключ узнаётся по форме варианта (решение оркестратора 21.10).

Правило (фиксировано до применения): семейство с выбором варианта выводится, если на прогоне
tools/bank_position_attack.py (100 обучающих + 100 проверочных случайных зёрен выдачи) хотя бы одна «атака по форме»
угадывает ключ в ≥ 90 % проверочных вариантов:
  len_rank            — ранг длины варианта (правильное исправление всегда самое длинное / короткое);
  text                — текст варианта с цифрами, заменёнными на # (правильная формулировка одна и та же);
  letter_x_len_rank, text_x_letter, ctx_x_text — те же признаки в паре с буквой или сюжетом.
Канарейки не трогаем (они не оцениваются и опубликованы намеренно).

Что делает: переносит YAML и модуль генератора в families_retired/form_leak_2110/<направление>/ (реестр читает только
families/*/*.yaml — в тест, симуляцию и валидатор они больше не попадают), правит путь generator в YAML, пишет
README.md с таблицей и JSON со списком (для BANK_SYNC). Генераторы сохранены для переделки (несколько верных форм).

Запуск из корня репозитория:
    python3 tools/bank_retire_form_leak.py --attack pos_after.json [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FORM_ATTACKS = ("len_rank", "text", "letter_x_len_rank", "text_x_letter", "ctx_x_text")
ROOT = Path(__file__).resolve().parents[1]
FAM = ROOT / "backend" / "assessment_bank" / "families"
RET = ROOT / "backend" / "assessment_bank" / "families_retired" / "form_leak_2110"
RU = {"len_rank": "длина варианта", "text": "текст варианта", "letter_x_len_rank": "буква × длина",
      "text_x_letter": "текст × буква", "ctx_x_text": "сюжет × текст"}


def _yaml_of(fid: str) -> Path | None:
    for p in FAM.glob("*/*.yaml"):
        try:
            head = p.read_text(encoding="utf-8").split("\n", 1)[0]
        except OSError:
            continue
        if head.strip() == f"family_id: {fid}":
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attack", required=True, help="JSON tools/bank_position_attack.py")
    ap.add_argument("--threshold", type=float, default=0.90)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = json.loads(Path(a.attack).read_text(encoding="utf-8"))
    picked = []
    for r in d["families"]:
        hits = {k: v for k, v in r["by_attack"].items() if k in FORM_ATTACKS and v >= a.threshold}
        if not hits:
            continue
        y = _yaml_of(r["family_id"])
        if y is None:
            continue
        txt = y.read_text(encoding="utf-8")
        if re.search(r"^canary:\s*true", txt, re.M):
            continue
        fmt = re.search(r"^format:\s*(\S+)", txt, re.M).group(1)
        gen = re.search(r"^generator:\s*(\S+)", txt, re.M).group(1)
        best = max(hits, key=hits.get)
        picked.append({"family_id": r["family_id"], "format": fmt, "yaml": str(y.relative_to(ROOT)),
                       "generator": gen, "attack": best, "acc": hits[best], "chance": r["chance"],
                       "all_form_hits": hits})
    picked.sort(key=lambda x: (x["format"], x["family_id"]))
    # модуль, который импортируют другие семейства, переносить нельзя — сообщаем
    blockers, rewrites = [], []
    moving = {str(ROOT / "backend" / (p["generator"].replace(".", "/") + ".py")) for p in picked}
    for p in picked:
        mod = p["generator"]
        users = subprocess.run(["grep", "-rl", "--include=*.py", mod, str(FAM)], capture_output=True, text=True).stdout.split()
        own = str((ROOT / "backend" / (mod.replace(".", "/") + ".py")))
        users = [u for u in users if u != own]
        if any(u not in moving for u in users):
            blockers.append((p["family_id"], [u for u in users if u not in moving]))
        elif users:
            rewrites.append((mod, users))  # импортирует только другое выводимое семейство — путь поправим
    print(json.dumps({"n": len(picked), "by_format": {f: sum(1 for p in picked if p["format"] == f)
                                                     for f in sorted({p["format"] for p in picked})},
                      "blockers": blockers}, ensure_ascii=False, indent=1))
    for p in picked:
        print(f"{p['acc']:.3f} {RU[p['attack']]:16s} {p['format']:12s} {p['family_id']}")
    if not a.apply:
        return 0
    if blockers:
        print("есть импорты из переносимых модулей — сначала разберите", file=sys.stderr)
        return 1
    RET.mkdir(parents=True, exist_ok=True)
    (RET / "__init__.py").touch()
    for p in picked:
        y = ROOT / p["yaml"]
        direction = y.parent.name
        dst = RET / direction
        dst.mkdir(exist_ok=True)
        (dst / "__init__.py").touch()
        py = ROOT / "backend" / (p["generator"].replace(".", "/") + ".py")
        subprocess.run(["git", "-C", str(ROOT), "mv", str(y), str(dst / y.name)], check=True)
        subprocess.run(["git", "-C", str(ROOT), "mv", str(py), str(dst / py.name)], check=True)
        new_gen = f"assessment_bank.families_retired.form_leak_2110.{direction}.{py.stem}"
        t = (dst / y.name).read_text(encoding="utf-8")
        t = re.sub(r"^generator:\s*\S+", f"generator: {new_gen}", t, count=1, flags=re.M)
        (dst / y.name).write_text(t, encoding="utf-8")
        p["retired_to"] = str((dst / y.name).relative_to(ROOT))
    for mod, users in rewrites:  # импорты между выводимыми модулями — на новые пути
        new_mod = next(p for p in picked if p["generator"] == mod)
        direction = Path(new_mod["retired_to"]).parent.name
        target = f"assessment_bank.families_retired.form_leak_2110.{direction}.{mod.rsplit('.', 1)[1]}"
        for u in users:
            nu = RET / Path(u).parent.name / Path(u).name
            nu.write_text(nu.read_text(encoding="utf-8").replace(mod, target), encoding="utf-8")
    rows = "\n".join(f"| `{p['family_id']}` | {p['format']} | {RU[p['attack']]} | {p['acc'] * 100:.0f} % | "
                     f"{p['chance'] * 100:.0f} % |" for p in picked)
    (RET / "README.md").write_text(
        "# Семейства, выведенные из выдачи 21.10.2026: ключ узнаётся по форме варианта\n\n"
        "Решение оркестратора 21.10 (до заморозки банка для итоговых цифр). Причина — атака «решатель без знаний, "
        "изучивший открытый код или уже видевший семейство» (`tools/bank_position_attack.py`: обучение на 100 случайных "
        "зёрнах из диапазона выдачи, проверка на других 100): по длине или тексту варианта (цифры заменены на #), "
        "отдельно или в паре с буквой и сюжетом, ключ угадывается в ≥ 90 % вариантов. Обычно это choose_fix с одним "
        "и тем же правильным исправлением (меняются только числа и имена) и концептуальные mcq с постоянной "
        "формулировкой ключа. Универсальное правило без изучения семейства не работает («самый длинный» — 19,6 %, "
        "«самый короткий» — 18,6 % при шансе 25 % по всем choose_fix), поэтому это вопрос утечкоустойчивости, а не "
        "угадывания.\n\n"
        "Реестр читает только `families/*/*.yaml` — эти семейства не попадают ни в тест, ни в симуляцию, ни в "
        "валидатор. Генераторы сохранены без правок содержания (изменён только путь `generator:`). План — переделка: "
        "несколько верных форм исправления и формулировок на семейство, ранг длины ключа по зерну; затем возврат.\n\n"
        f"Правило отбора: `python3 tools/bank_retire_form_leak.py --attack <json> --threshold {a.threshold}` "
        f"(канарейки не трогаются). Выведено: {len(picked)}.\n\n"
        "| Семейство | Формат | Атака | Угадывание | Шанс |\n|---|---|---|---|---|\n" + rows + "\n",
        encoding="utf-8")
    (RET / "retired.json").write_text(json.dumps({"rule": f"form attack >= {a.threshold}", "attacks": FORM_ATTACKS,
                                                  "source": a.attack, "families": picked}, ensure_ascii=False,
                                                 indent=1), encoding="utf-8")
    print(f"перенесено: {len(picked)} → {RET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
