#!/usr/bin/env python3
"""Генератор волны 20.10-S (замена потерянного tools/w2010_scale1500.py).

Пересобирает 1 049 семейств волны (s15_*.yaml и s15_*.py) из каталогов базовых моделей
``backend/assessment_bank/families/_w2010_scale_cat_*.py`` и описаний ``_w2010_scale_defs.py``:
* 5 вариантов ответа (A–E), стратифицированное равномерное положение правильного ответа
  по величине (0..4 — ровно по 20 %) и по букве (A..E — ровно по 20 %);
* дистракторы из типовых ошибок модели (пропуск/удвоение/инверсия фактора, неверное округление,
  путаница двоичных и десятичных приставок, ошибка на границе сетки);
* в обратных задачах лимит B строго отделён от ответа и от значения модели при ответе;
* расчётные задачи размечены по содержанию максимум до Senior (Стажёр, Junior, Middle, Senior);
* честные априорные IRT-параметры (a = 1,0, b от порога грейда по собственному ключу потока).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from assessment_bank.families import _w2010_scale_defs as sd  # noqa: E402

FAM_DIR = ROOT / "backend" / "assessment_bank" / "families"

PY_TMPL = '''"""{fid} — mcq_concept ({grade_ru}). {title}.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«{arch_key}» в families/_w2010_scale_cat_{direction}.py, ступень {k} из 5, {mode_ru};
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = {fid!r}
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
'''

YAML_HEADER = (
    "# Волна 20.10-S (пересобрано tools/w2010_regen.py из families/_w2010_scale_cat_*.py): "
    "5 вариантов ответа, честные априорные параметры, грейды до Senior.\n"
)


def regen_all(*, only_existing: bool = True, verify_seeds: int = 2) -> int:
    count = 0
    for fid, info in sorted(sd.FAMILIES.items()):
        a = info["arch"]
        mod = info["mod"]
        d_dir = FAM_DIR / a.d
        yaml_path = d_dir / f"{mod}.yaml"
        py_path = d_dir / f"{mod}.py"
        if only_existing and not yaml_path.exists():
            continue
        meta = sd.family_meta(fid)
        yaml_doc = {
            "family_id": meta["family_id"],
            "title": meta["title"],
            "direction": meta["direction"],
            "skills": meta["skills"],
            "target_grades": [meta["grade"]],
            "format": "mcq_concept",
            "language": "text",
            "invariants": {
                "n_options": meta["n_options"],
                "extra": {
                    "traps": meta["traps"],
                    "construct": meta["construct"],
                    "wave": "20.10-S",
                },
            },
            "time_limit_s": meta["time"],
            "canary": False,
            "prior_difficulty": {
                "b": meta["b"],
                "a": meta["a"],
                "sigma_variant": 0.3,
                "basis": meta["basis"],
            },
            "generator": f"assessment_bank.families.{a.d}.{mod}",
            "version": 2,
            "description": meta["desc"],
        }
        yaml_text = YAML_HEADER + yaml.safe_dump(yaml_doc, allow_unicode=True, sort_keys=False, width=110)
        yaml_path.write_text(yaml_text, encoding="utf-8")

        mode_ru = "прямой расчёт" if info["mode"] == "fwd" else "обратная задача"
        py_text = PY_TMPL.format(
            fid=fid,
            grade_ru=sd.GRADE_RU[meta["grade"]],
            title=meta["title"],
            arch_key=a.key,
            direction=a.d,
            k=info["k"],
            mode_ru=mode_ru,
        )
        py_path.write_text(py_text, encoding="utf-8")
        count += 1

    if verify_seeds > 0:
        from assessment_bank.registry import generate, reload_registry

        reload_registry()
        for fid, info in sorted(sd.FAMILIES.items()):
            a = info["arch"]
            mod = info["mod"]
            if only_existing and not (FAM_DIR / a.d / f"{mod}.yaml").exists():
                continue
            for s in range(1, verify_seeds + 1):
                v = generate(fid, s)
                assert len(v.options or []) == 5, f"{fid}: len(options) != 5"
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description="Перегенерация 1 049 семейств волны 20.10-S")
    ap.add_argument("--verify-seeds", type=int, default=2, help="Сколько seed проверить после генерации")
    args = ap.parse_args()
    n = regen_all(only_existing=True, verify_seeds=args.verify_seeds)
    print(f"Перегенерировано и проверено семейств волны 20.10-S: {n}")


if __name__ == "__main__":
    main()
