"""П1 п. 7: вырезание ПДн без регрессий разбора — 50 реальных вакансий (docs/realdata/vacancies_50.json) и
синтетические резюме (tests/test_pii_llm_bodies.py, jury/seed.NEW_RESUME).

Сравнение «до» (pii.py из integ 4cfc9fa) и «после» (текущая ветка) для текста, который уходит в модель:
- сколько и чего вырезано (по типам) и полный список НОВЫХ вырезаний — для ручной проверки ложных срабатываний;
- разбор правилами (parse_rules) по тексту для модели: стек P/R против silver-разметки, опыт, направление, формат,
  вилка. Разбор правилами в продукте идёт по исходному тексту (redact на путь без LLM не влияет) — его цифры
  одинаковы до и после по построению и приведены строкой «исходный текст».

Запуск: cd backend && ../../../.venv/bin/python ../tools/realdata/pii_check.py  →  docs/realdata/pii_check.json
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
BASE = "4cfc9fa"

from app.modules.matching.need_parser import parse_rules  # noqa: E402
from app.modules.resume import pii as new_pii  # noqa: E402
from app.modules.resume.extract import experience_years, extract_rules  # noqa: E402


def old_pii() -> types.ModuleType:
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{BASE}:backend/app/modules/resume/pii.py"], text=True)
    mod = types.ModuleType("pii_base")
    sys.modules["pii_base"] = mod  # dataclass ищет модуль класса в sys.modules
    exec(compile(src, "pii_base", "exec"), mod.__dict__)
    return mod


PH = re.compile(r"\[(?:почта|ссылка|телефон|ник|дата рождения|снилс|паспорт|инн|адрес|дата|возраст|пол|ФИО|имя)\]")


def stack_pr(rows, texts):
    tp = fp = fn = 0
    for row, t in zip(rows, texts):
        r = parse_rules(t)
        got = {i["tag"] for i in r["stack_required"] + r["stack_desired"]}
        exp = set(row["expected_stack"])
        tp, fp, fn = tp + len(got & exp), fp + len(got - exp), fn + len(exp - got)
    return round(tp / max(1, tp + fp), 3), round(tp / max(1, tp + fn), 3)


def fields(rows, texts):
    c = Counter()
    for row, t in zip(rows, texts):
        r = parse_rules(t)
        for k in ("direction", "experience_years_min", "work_format", "salary_from", "salary_to"):
            c[k] += int(r.get(k) == row["expected"].get(k))
        c["city_same_as_original"] += int(r.get("city") == parse_rules(row["text"]).get("city"))
    return dict(c)


def vac(mod, text):
    kw = dict(use_ner=True, ner_min_tokens=2, contact_cues=True)
    if "header" in mod.redact.__code__.co_varnames:
        kw["header"] = False
    return mod.redact(text, **kw)


def main():
    rows = json.load(open(ROOT / "docs/realdata/vacancies_50.json"))["vacancies"]
    old = old_pii()
    red_old = [vac(old, r["text"]) for r in rows]
    red_new = [vac(new_pii, r["text"]) for r in rows]
    by_type_old, by_type_new = Counter(), Counter()
    for a, b in zip(red_old, red_new):
        by_type_old.update(a.summary)
        by_type_new.update(b.summary)
    new_cuts = []
    for row, a, b in zip(rows, red_old, red_new):
        if a.text != b.text:
            pa, pb = Counter(PH.findall(a.text)), Counter(PH.findall(b.text))
            diff = {k: pb[k] - pa[k] for k in pb | pa if pb[k] != pa[k]}
            vals = {k: v for k, v in b.found.items() if a.found.get(k) != v}
            new_cuts.append({"id": row["id"], "placeholders": diff, "values": vals})
    texts = {"исходный текст (путь без LLM)": [r["text"] for r in rows],
             "текст для модели — до (integ 4cfc9fa)": [x.text for x in red_old],
             "текст для модели — после (fix/pii-mask)": [x.text for x in red_new]}
    table = {}
    for name, ts in texts.items():
        p, r = stack_pr(rows, ts)
        table[name] = {"stack_P": p, "stack_R": r, **fields(rows, ts)}

    from app.modules.jury.seed import NEW_RESUME
    from test_pii_llm_bodies import RESUMES
    from test_pii_mask import RESUMES as RESUMES2

    resumes = ["\n".join(lines) for lines, _, _ in RESUMES] + list(RESUMES2) + [NEW_RESUME]
    res_rows = []
    for t in resumes:
        o, n = old.redact(t).text, new_pii.redact(t).text
        eo, en = extract_rules(o), extract_rules(n)
        res_rows.append({"head": t.split("\n")[0][:40], "exp_original": experience_years(t), "exp_before": experience_years(o),
                         "exp_after": experience_years(n),
                         "stack_before": [s["tag"] for s in eo["stack"]], "stack_after": [s["tag"] for s in en["stack"]],
                         "direction_before": eo["direction_hint"], "direction_after": en["direction_hint"],
                         "leaks_after": sorted(PH.findall(n))})
    # Ложные срабатывания в тексте задач и коде: все семейства банка (условия + код), как ответ кандидата с цитатой кода;
    # NER выключен у обоих (он одинаков до и после), сравниваются регулярные выражения и словари
    bank_old, bank_new, bank_chars = Counter(), Counter(), 0
    for f in sorted((ROOT / "backend/assessment_bank/families").rglob("*.py")):
        t = f.read_text(encoding="utf-8")
        bank_chars += len(t)
        bank_old.update(PH.findall(old.redact(t, use_ner=False).text))
        bank_new.update(PH.findall(new_pii.redact(t, use_ner=False, header=False).text))
    out = {"bank_tasks_code": {"chars": bank_chars, "placeholders_before": dict(bank_old),
                               "placeholders_after": dict(bank_new)},
           "vacancies": {"n": len(rows), "redacted_by_type_before": dict(by_type_old),
                         "redacted_by_type_after": dict(by_type_new), "texts_changed": len(new_cuts),
                         "new_cuts": new_cuts, "parse_rules": table},
           "resumes_synthetic": res_rows}
    path = ROOT / "docs/realdata/pii_check.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["bank_tasks_code"], ensure_ascii=False))
    print(json.dumps({k: v for k, v in out["vacancies"].items() if k != "new_cuts"}, ensure_ascii=False, indent=1))
    for c in new_cuts:
        print(c["id"], c["placeholders"], c["values"])
    for r in res_rows:
        print(r["head"], r["exp_original"], r["exp_before"], r["exp_after"], r["direction_before"], r["direction_after"],
              r["stack_before"] == r["stack_after"] or (r["stack_before"], r["stack_after"]))


if __name__ == "__main__":
    main()
