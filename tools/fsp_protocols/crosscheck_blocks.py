"""Сверка мест в командных протоколах вторым поставщиком распознавания (для страниц без подтверждения геометрией).

  python3 crosscheck_blocks.py <events.json> <pdf_dir> <retable_out_dir>   (OPENROUTER_API_KEY)
Для страниц retable.py со status=model_only та же страница отдаётся модели другого поставщика
(FSP_CROSSCHECK_MODEL, по умолчанию anthropic/claude-sonnet-5.5) с тем же заданием «блоки команд». Строка получает
place_uncertain=false и place_check="two_providers", только если второй поставщик независимо отнёс этого участника
(фамилия + имя) к тому же месту. Остальные строки остаются «место требует сверки». Результат пишется в те же JSON
(ПДн — только в data_local). Сводка без ПДн — crosscheck_summary.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("FSP_OCR_MODEL", os.environ.get("FSP_CROSSCHECK_MODEL", "anthropic/claude-sonnet-5.5"))
from tools.fsp_protocols import extract_team_blocks as etb  # noqa: E402
from tools.fsp_protocols.retable import DOC_IDS  # noqa: E402

etb.MODEL = os.environ.get("FSP_CROSSCHECK_MODEL", "anthropic/claude-sonnet-5.5")


def person_key(fio: str | None) -> str:
    w = (fio or "").lower().replace("ё", "е").split()
    return " ".join(w[:2])


def main() -> None:
    ev_path, pdf_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    key = os.environ["OPENROUTER_API_KEY"]
    file_by_doc = {v: k for k, v in DOC_IDS.items()}
    jobs = []
    for f in sorted(out_dir.glob("*/pages_json/page_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("status") == "model_only" and f.parts[-3] in file_by_doc:
            jobs.append((f, file_by_doc[f.parts[-3]], int(f.stem.split("_")[-1])))

    def run(job):
        f, fn, page = job
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "p.jpg"
            subprocess.run(["pdftoppm", "-r", "160", "-jpeg", "-f", str(page), "-l", str(page), "-singlefile",
                            str(pdf_dir / fn), str(img)[:-4]], check=True)
            for _ in range(2):
                try:
                    return job, etb.ask(img, key)
                except Exception as e:  # noqa: BLE001
                    err = str(e)[:200]
            return job, {"teams": [], "error": err}

    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(run, jobs))
    summary: dict[str, dict] = {}
    for (f, fn, page), res in results:
        d = json.loads(f.read_text(encoding="utf-8"))
        other: dict[str, object] = {}
        prev_place = None
        for i, t in enumerate(res.get("teams") or []):
            place = t.get("place")
            if place is None and i == 0:
                place = "continuation"
            for m in t.get("members") or []:
                other[person_key(m.get("fio"))] = place
            prev_place = place
        # продолжение команды с прошлой страницы: место берём из уже размеченной строки нашего разбора
        cont_place = next((r.get("place") for r in d["rows"] if r.get("place") is not None), None) if d["rows"] else None
        agree = 0
        for r in d["rows"]:
            o = other.get(person_key(r.get("fio")))
            if o == "continuation":
                o = r.get("place") if d["rows"] and r.get("place") == cont_place else None
            if r.get("place") is not None and o is not None and str(o) == str(r.get("place")):
                r["place_uncertain"] = False
                r["place_check"] = "two_providers"
                agree += 1
        d["crosscheck"] = {"model": etb.MODEL, "rows": len(d["rows"]), "agree": agree, "error": res.get("error")}
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        s = summary.setdefault(f.parts[-3], {"pages": 0, "rows": 0, "agree": 0})
        s["pages"] += 1
        s["rows"] += len(d["rows"])
        s["agree"] += agree
        print(f.parts[-3], page, len(d["rows"]), agree, res.get("error") or "", flush=True)
    (out_dir / "crosscheck_summary.json").write_text(json.dumps({"model": etb.MODEL, "docs": summary}, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")


if __name__ == "__main__":
    main()
