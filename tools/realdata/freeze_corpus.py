"""Freeze exactly 50 source-backed texts. Gold fields are independent silver annotations."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/realdata"


def read(name):
    return [json.loads(line) for line in (OUT / name).read_text().splitlines() if line]


def main():
    pages = {p["url"]: p for p in read("fetched_pages.jsonl") + read("additional_pages.jsonl")}
    rows = read("annotated_excerpts.jsonl") + read("annotated_excerpts_extra.jsonl")[:25]
    # One exact game-development source completes the five out-of-MVP role types.
    url = "https://novosibirsk.hh.ru/vacancy/137859362"
    body = pages[url]["content"]
    text = body[body.index("# Unity-разработчик"):body.index("## Задайте вопрос")]
    rows.append({"title": "Unity-разработчик", "excerpt": text, "source_url": url,
                 "direction": "frontend", "grade": "junior", "unsupported_role": "gamedev",
                 "experience_years_min": 0, "work_format": "office", "salary_from": None, "salary_to": None,
                 "stack": ["csharp", "git"], "annotation": "manual: explicit internship, no experience required"})
    assert len(rows) == 50
    frozen = []
    for i, row in enumerate(rows, 1):
        source = pages[row["source_url"]]["content"]
        text = row["excerpt"]
        # Include the vacancy's own scalar metadata, not the site's market estimates or navigation.
        header = source[source.find("\n# ") + 1:] if "\n# " in source else source
        header = re.split(r"## (?:Компания|Описание вакансии)|Сейчас эту вакансию|Напишите телефон",
                          header)[0][:1200]
        title_line = next((s for s in header.splitlines() if s.startswith("# ")), "")
        metadata = []
        for line in header.splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if (re.fullmatch(r"Junior|Middle|Senior|Lead|Гибрид|Удалённо|Можно удалённо", stripped, re.I)
                    or re.match(r"Опыт работы:|Формат работы:", stripped)
                    or ("₽" in stripped or "RUB" in stripped) and
                    not re.search(r"Похожие специалисты|Медиана|Рынок", stripped, re.I)):
                metadata.append(line)
        prefix = "\n".join([title_line] + metadata).strip()
        if prefix:
            text = prefix + "\n\n" + text
        elif row["title"] not in text[:400] and row["title"] in source:
            text = row["title"] + "\n" + text
        # No generated prose enters text; each line is a source quote.
        assert re.sub(r"\s+", " ", row["excerpt"]).strip() in re.sub(r"\s+", " ", source)
        assert not re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
        expected = {k: row.get(k) for k in
                    ("direction", "grade", "experience_years_min", "work_format", "salary_from", "salary_to")}
        if row.get("unsupported_role"):
            expected["direction"] = {"devops": "backend", "mobile": "frontend", "analytics": "data_ml",
                                     "1c": "backend", "gamedev": "frontend"}[row["unsupported_role"]]
        # QA on Android is QA, not an unsupported mobile developer.
        if "QA Java mobile" in row["title"]:
            row["unsupported_role"] = None
            expected["direction"] = "qa"
        # Manual audit corrections against excerpts (not against parser outputs).
        corrections = {
            1: {"salary_from": 258600, "salary_to": 347400},
            3: {"work_format": "remote"},
            4: {"work_format": "remote"},
            5: {"salary_from": 256000, "salary_to": 280000},
            6: {"work_format": "remote"},
            7: {"grade": "junior"},
            8: {"work_format": "remote"},
            11: {"work_format": "remote"},
            14: {"work_format": None},
            19: {"work_format": "hybrid"},
            20: {"experience_years_min": 6},  # explicit listing metadata "более 6 лет"
            23: {"experience_years_min": 1},  # listing metadata 1-3 years
            29: {"grade": "senior", "work_format": "remote"},
            37: {"grade": "junior", "work_format": "hybrid"},
            39: {"grade": "junior"},
            42: {"grade": "senior", "work_format": "remote"},
            48: {"grade": "senior", "experience_years_min": 5},
        }
        expected.update(corrections.get(i, {}))
        acceptable = {4: ["remote", "hybrid", "office"], 6: ["remote", "hybrid"],
                      8: ["remote", "office"], 11: ["remote", "office"],
                      29: ["remote", "office", "hybrid"], 37: ["office", "hybrid"],
                      40: ["remote", "hybrid"], 48: ["remote", "hybrid"]}
        frozen.append({
            "id": f"vac-{i:03d}", "title": row["title"], "text": text,
            "source_url": row["source_url"], "collected_at": "2026-10-07",
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "expected": expected, "expected_stack": [t for t in row["stack"] if t != "ansible"],
            "unsupported_role": row.get("unsupported_role"),
            "acceptable": {"work_format": acceptable[i]} if i in acceptable else {},
            "annotation": "independent silver + manual scalar/source-span audit; not expert labels",
        })
        if i == 3:
            frozen[-1]["acceptable"]["experience_years_min"] = [2, 3]  # body vs listing metadata
    (OUT / "vacancies_50.json").write_text(json.dumps({
        "schema_version": 1, "purpose": "Regression texts only; never a vacancy import",
        "annotation_method": "Independent offline silver extraction, verified source spans; not expert labels. "
                             "Explicit fields only. Inferred grades are reported separately.",
        "vacancies": frozen}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{OUT / 'vacancies_50.json'}\n50 texts, sources and hashes frozen")


if __name__ == "__main__":
    main()
