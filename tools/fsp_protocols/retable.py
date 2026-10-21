"""Повторный разбор командных протоколов: блоки команд (модель) + число участников в блоке (линии таблицы).

  python3 retable.py <events.json> <pdf_dir> <out_dir> [--only <файл.pdf>] [--pages a-b]
Для каждой страницы протокола командного соревнования (по page_map из events.json):
  1) рендер 160 dpi; 2) team_geometry.block_row_counts — сколько строк в каждом блоке «Место»;
  3) extract_team_blocks — места, названия, субъекты, баллы и упорядоченный список участников;
  4) сверка: число блоков и сумма строк должны совпасть (допускается строка шапки таблицы сверху);
     совпало — участники раскладываются по блокам геометрии (status=geometry); нет — берётся разбивка модели
     с пометкой place_uncertain=true (status=model_only).
Продолжение команды с прошлой страницы получает её место. Результат — постраничные JSON в формате кэша
распознавания (rows: fio, birth_date, place, team, region, score, role) — с ПДн, только в data_local.
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
from tools.fsp_protocols.extract_team_blocks import ask  # noqa: E402
from tools.fsp_protocols.team_geometry import block_row_counts  # noqa: E402

DOC_IDS = {"tb1vnqokiid4fiwdb40evznavplvmysg.pdf": "chr_2025_prod_final", "8ma6l935b05m4q88wi5n24ne23p7qbya.pdf": "kr_2025_prod_final",
           "5hs99w6a2n362vlqnonn51110vlhkvc5.pdf": "kr_2025_ib_final", "us9qvdfvm0kwathyo67wjuvje8c9v1ra.pdf": "kr_2026_robo_otbor",
           "f8mtqy9398owua73i24f999rly5fovnf.pdf": "kr_2026_prod_otbor", "15a3exjee1npp1vux0sl5qborm4n6q3r.pdf": "kf_2026_final",
           "xqhh07qp40z3mfi8lraxt53842qlw772.pdf": "pfo_2026_prod", "u4g6723ljtd8cxp3fa1kfhbs01f7cfbs.pdf": "cfo_2026_prod"}


def page_job(pdf: Path, page: int, key: str, tmp: Path) -> dict:
    img = tmp / f"{pdf.stem[:6]}-{page:03d}.jpg"
    if not img.exists():
        subprocess.run(["pdftoppm", "-r", "160", "-jpeg", "-f", str(page), "-l", str(page), "-singlefile", str(pdf), str(img)[:-4]], check=True)
    geo = block_row_counts(img)
    try:
        ocr = ask(img, key)
    except Exception as e:  # noqa: BLE001
        ocr = {"teams": [], "error": str(e)[:200]}
    return {"page": page, "geo": geo["counts"], "teams": ocr.get("teams", []), "error": ocr.get("error")}


def reconcile(job: dict) -> tuple[list[list[dict]], list[dict], str]:
    """Разложить участников по блокам геометрии. Возвращает (участники по блокам, реквизиты блоков, статус)."""
    teams = job["teams"]
    members = [m for t in teams for m in (t.get("members") or [])]
    g = list(job["geo"])
    if g and g[0] == 1 and sum(g) == len(members) + 1:
        g = g[1:]  # строка шапки таблицы («Место | Команда | Состав …»)
    if not g or sum(g) != len(members) or any(n <= 0 for n in g):
        return [t.get("members") or [] for t in teams], teams, "model_only"
    if len(g) == len(teams):
        metas = teams
    elif len(g) == len(teams) + 1 and not (teams and (teams[0].get("continues_from_previous_page") or teams[0].get("place") is None)):
        # модель приклеила продолжение команды с прошлой страницы к первой команде страницы
        metas = [{"continues_from_previous_page": True, "place": None, "team": None}] + teams
    else:
        return [t.get("members") or [] for t in teams], teams, "model_only"
    out, i = [], 0
    for n in g:
        out.append(members[i:i + n])
        i += n
    return out, metas, "geometry"


def main() -> None:
    ev_path, pdf_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    prange = sys.argv[sys.argv.index("--pages") + 1] if "--pages" in sys.argv else None
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    key = os.environ["OPENROUTER_API_KEY"]
    summary = {}
    for fn, segs in ev["page_map"].items():
        if fn not in DOC_IDS or (only and fn != only):
            continue
        doc_id = DOC_IDS[fn]
        pages = []
        for s in segs:
            if s["page_type"] == "protocol" and ev["events"][s["event_id"]].get("team_event"):
                pages += [(p, s["event_id"]) for p in range(s["pages"][0], s["pages"][1] + 1)]
        if prange:
            a, b = (int(x) for x in prange.split("-"))
            pages = [(p, e) for p, e in pages if a <= p <= b]
        with tempfile.TemporaryDirectory() as td, ThreadPoolExecutor(6) as ex:
            jobs = list(ex.map(lambda pe: {**page_job(pdf_dir / fn, pe[0], key, Path(td)), "event_id": pe[1]}, pages))
        jobs.sort(key=lambda j: j["page"])
        prev = None
        stat = {"geometry": 0, "model_only": 0, "pages": len(jobs), "rows": 0}
        (out_dir / doc_id / "pages_json").mkdir(parents=True, exist_ok=True)
        for j in jobs:
            blocks, metas, status = reconcile(j)
            stat[status] += 1
            rows = []
            if prev and prev["event_id"] != j["event_id"]:
                prev = None
            for bi, (mem, meta) in enumerate(zip(blocks, metas)):
                cont = bi == 0 and (meta.get("continues_from_previous_page") or (meta.get("place") is None and not meta.get("team")))
                if cont and prev:
                    place, team, region, score = prev["place"], prev["team"], prev["region"], prev["score"]
                else:
                    place, team, region, score = meta.get("place"), meta.get("team"), meta.get("region"), meta.get("score")
                for m in mem:
                    rows.append({"fio": m.get("fio"), "birth_date": m.get("birth_date"), "place": place, "rank": None, "role": "Спортсмен",
                                 "team": team, "region": m.get("region") or region, "score": score,
                                 "place_uncertain": status != "geometry" or place is None})
                prev = {"place": place, "team": team, "region": region, "score": score, "event_id": j["event_id"]}
            stat["rows"] += len(rows)
            (out_dir / doc_id / "pages_json" / f"page_{j['page']:03d}.json").write_text(json.dumps({
                "rows": rows, "status": status, "geometry_counts": j["geo"], "ocr_blocks": [len(t.get("members") or []) for t in j["teams"]],
                "error": j.get("error"),
                "method": "блоки команд (google/gemini-2.5-pro) + число участников по линиям таблицы (team_geometry.py)"}, ensure_ascii=False, indent=1), encoding="utf-8")
        summary[doc_id] = stat
        print(doc_id, stat, flush=True)
    (out_dir / "retable_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
