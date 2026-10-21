"""Восстановление мест в командных протоколах там, где в index_v4 место отсутствует (place = None) или не подтверждено.

  python3 place_recover.py <cache_v2_dir> <pdf_dir> <out_cache_v3_dir>      (OPENROUTER_API_KEY)

Разбор глазами (21.10, переезд 16) показал три причины пропуска:
  1) в колонке «Место» стоит не число: «б/м» (без места, 0 баллов — КФ-2026 стр. 60–70), «DSQ» (дисквалификация,
     ПФО-2026 стр. 11), диапазон «14-24» / «9-10» (поделённые места — КР-2026 робототехника, ЧР-2025 продуктовое).
     Прежний разбор просил «place: число или null» — такие ячейки превращались в null (а диапазон иногда — в нижнюю
     границу: «9-10» → 9);
  2) линии таблицы не находились: серые линии сканов (порог 140), наклон листа 0,3–0,6°, таблица короче нижних 2/3
     страницы → геометрия [] и статус model_only;
  3) лишние «блоки» в начале геометрии (0 — линия над шапкой, 1 — шапка) мешали сверке сумм.

Здесь для каждой такой страницы:
  * геометрия — team_geometry.block_row_counts_v2 (выравнивание наклона, порог Оцу, границы таблицы по линиям);
    в сверке сумм отбрасываются ведущие блоки 0/1 (шапка), пока сумма больше числа участников;
  * текст ячейки «Место» дословно (place_text) — два поставщика: FSP_OCR_MODEL (google/gemini-2.5-pro) и
    FSP_CROSSCHECK_MODEL (anthropic/claude-sonnet-5.5). Третий поставщик (OpenAI) зарезервирован для аудита
    ocr_audit_v4 и здесь НЕ используется;
  * место записи подтверждено, если (а) блоки сошлись с геометрией и оба поставщика дали одинаковый place_text
    для этого участника (фамилия + имя), или (б) без геометрии — оба поставщика независимо отнесли участника
    к блоку с одинаковым place_text. Иначе — place_uncertain (в индексе — статус place_unverified).
Разбор place_text: число → place; «a-b» → place_range [a, b] (place = None: место поделено, по ЕВСК не засчитываем);
«б/м» → place_status no_place («без места» по протоколу); «DSQ», «дискв.» → disqualified; «н/я» → did_not_start.
Результат — постраничные JSON в формате cache_v2 (+ place_text, place_range, place_status, place_check) — с ПДн,
только в data_local. Сводка без ПДн — <out>/place_recover_summary.json.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.fsp_protocols.retable import DOC_IDS  # noqa: E402
from tools.fsp_protocols.team_geometry import block_row_counts, block_row_counts_v2  # noqa: E402

MODEL_A = os.environ.get("FSP_OCR_MODEL", "google/gemini-2.5-pro")
MODEL_B = os.environ.get("FSP_CROSSCHECK_MODEL", "anthropic/claude-sonnet-5.5")
PROMPT = """Это страница итогового протокола командного соревнования ФСП России. В таблице колонки: Место, Название команды,
ФИО участников (несколько строк на одну команду — место и название в объединённых ячейках), Дата рождения,
Субъект РФ, Баллы (могут быть и другие колонки). Верни СТРОГО JSON:
{"teams": [{"place_text": "текст ячейки «Место» ДОСЛОВНО, как напечатано: например \\"7\\", \\"9-10\\", \\"б/м\\", \\"DSQ\\"; пустая строка, если ячейка пуста",
  "team": "название", "region": "субъект РФ", "score": "баллы как в документе",
  "members": [{"fio": "Фамилия Имя Отчество полностью", "birth_date": "ДД.ММ.ГГГГ"}],
  "continues_from_previous_page": true/false}]}
Не превращай диапазон или буквы в число — переписывай ячейку «Место» как есть. Внимательно отнеси каждого участника
к своей команде по горизонтальным линиям таблицы. Если в начале страницы идут строки без места и названия — это
продолжение команды с прошлой страницы: place_text="", team=null, continues_from_previous_page=true. Никакого текста кроме JSON."""


def ask(img: Path, key: str, model: str) -> dict:
    b64 = base64.b64encode(img.read_bytes()).decode()
    body = {"model": model, "temperature": 0, "max_tokens": 16000, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT},
                                                      {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read())
    txt = resp["choices"][0]["message"]["content"]
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    out = json.loads(txt)
    out["_usage"] = resp.get("usage", {})
    return out


def parse_place(text: str | None) -> dict:
    """Текст ячейки «Место» → {place, place_range, place_status}."""
    t = norm_pt(text)
    if re.fullmatch(r"\d{1,4}", t):
        return {"place": int(t), "place_range": None, "place_status": "placed"}
    m = re.fullmatch(r"(\d{1,4})-(\d{1,4})", t)
    if m and int(m.group(1)) < int(m.group(2)):
        return {"place": None, "place_range": [int(m.group(1)), int(m.group(2))], "place_status": "shared_range"}
    if t in {"б/м", "бм", "б/м.", "безместа"}:
        return {"place": None, "place_range": None, "place_status": "no_place"}
    if t.startswith("dsq") or t.startswith("дискв") or t == "дск":
        return {"place": None, "place_range": None, "place_status": "disqualified"}
    if t in {"н/я", "ня"}:
        return {"place": None, "place_range": None, "place_status": "did_not_start"}
    return {"place": None, "place_range": None, "place_status": "unparsed" if t else "empty"}


def person_key(fio: str | None) -> str:
    w = (fio or "").lower().replace("ё", "е").split()
    return " ".join(w[:2])


def team_key(t: str | None) -> str:
    return re.sub(r"[^0-9a-zа-я]", "", (t or "").lower().replace("ё", "е"))


def norm_pt(t: str | None) -> str:
    """Текст ячейки «Место» без пробелов и оформления: «1.» → «1», «14 – 24» → «14-24», «Б\\М» → «б/м»."""
    t = (t or "").strip().lower().replace(" ", "").replace("–", "-").replace("—", "-").replace("\\", "/")
    return t[:-1] if re.fullmatch(r"\d{1,4}\.", t) else t


def fit_geometry(geo: list[int], n_members: int) -> list[int] | None:
    """Отбросить ведущие блоки 0/1 (линия над шапкой, шапка), пока сумма больше числа участников."""
    g = list(geo)
    while g and g[0] <= 1 and sum(g) > n_members:
        g = g[1:]
    if g and sum(g) == n_members and all(n > 0 for n in g):
        return g
    return None


def blocks_with_place(teams: list[dict], prev_text: str | None) -> list[tuple[str, dict]]:
    """[(place_text, team_meta)] с переносом места на продолжение команды с прошлой страницы."""
    out = []
    for i, t in enumerate(teams):
        pt = norm_pt(t.get("place_text"))
        if i == 0 and not pt and (t.get("continues_from_previous_page") or not t.get("team")):
            pt = prev_text or ""
        out.append((pt, t))
    return out


def infer_sequence(out_dir: Path) -> None:
    """Пустая ячейка «Место» у отдельной команды (не продолжения) между местами k и k+2 → место k+1.

    Пример: ЧР-2025 продуктовое, стр. 4 — цифра места команды под печатью не читается ни одним поставщиком,
    до неё 7, после неё «9-10». Места в протоколе идут подряд, поэтому 8 восстанавливается однозначно
    (place_check = "sequence"). Применяется только к соседним страницам одного документа."""
    for doc_dir in sorted(p for p in out_dir.iterdir() if (p / "pages_json").is_dir()):
        files = sorted((doc_dir / "pages_json").glob("page_*.json"))
        pages = [(int(f.stem.split("_")[-1]), f, json.loads(f.read_text(encoding="utf-8"))) for f in files]
        blocks: list[dict] = []  # подряд идущие строки одной команды
        for pno, f, d in pages:
            for r in d["rows"]:
                if blocks and blocks[-1]["team"] == r.get("team") and blocks[-1]["text"] in (r["place_text"], "") \
                        and pno - blocks[-1]["last_page"] <= 1:
                    blocks[-1]["rows"].append(r)
                    blocks[-1]["last_page"] = pno
                    blocks[-1]["text"] = blocks[-1]["text"] or r["place_text"]
                else:
                    if blocks and pno - blocks[-1]["last_page"] > 1:
                        blocks.append({"team": None, "text": "?", "rows": [], "last_page": pno})  # разрыв страниц
                    blocks.append({"team": r.get("team"), "text": r["place_text"], "rows": [r], "last_page": pno})

        def bounds(t: str) -> tuple[int, int] | None:
            p = parse_place(t)
            if p["place"] is not None:
                return p["place"], p["place"]
            if p["place_range"]:
                return tuple(p["place_range"])
            return None
        changed = False
        for i, b in enumerate(blocks):
            if not b["team"] or i == 0 or i + 1 >= len(blocks) or not any(r["place_uncertain"] for r in b["rows"]):
                continue
            pv, nx = blocks[i - 1], blocks[i + 1]
            if any(r["place_uncertain"] for r in pv["rows"] + nx["rows"]) or not pv["rows"] or not nx["rows"]:
                continue  # соседние места сами должны быть подтверждены
            pb, nb = bounds(pv["text"]), bounds(nx["text"])
            if pb and nb and nb[0] == pb[1] + 2 and b["text"] in ("", str(pb[1] + 1)):
                for r in b["rows"]:
                    r.update(place=pb[1] + 1, place_status="placed", place_range=None,
                             place_uncertain=False, place_check="sequence")
                changed = True
        if changed:
            for _, f, d in pages:
                f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    v2_dir, pdf_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    key = os.environ["OPENROUTER_API_KEY"]
    file_by_doc = {v: k for k, v in DOC_IDS.items()}
    file_by_doc.setdefault("kr_2026_sib_otbor", None)
    targets = []
    for f in sorted(v2_dir.glob("*/pages_json/page_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        # страницы, где у кого-то нет места или место не подтверждено (place_uncertain)
        if any(r.get("place") is None or r.get("place_uncertain") for r in d["rows"]) and file_by_doc.get(f.parts[-3]):
            targets.append((f.parts[-3], int(f.stem.split("_")[-1]), d))
    only = os.environ.get("FSP_PR_ONLY")  # «doc:page,doc:page» — пробный запуск
    if only:
        sel = {tuple(x.split(":")) for x in only.split(",")}
        targets = [t for t in targets if (t[0], str(t[1])) in sel]

    def run(t):
        doc, page, d = t
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "p.jpg"
            subprocess.run(["pdftoppm", "-r", "160", "-jpeg", "-f", str(page), "-l", str(page), "-singlefile",
                            str(pdf_dir / file_by_doc[doc]), str(img)[:-4]], check=True)
            geo1 = block_row_counts(img)["counts"]
            g2 = block_row_counts_v2(img)
            res = {}
            raw = out_dir / "raw" / f"{doc}_{page:03d}.json"
            if raw.exists():  # ответы моделей уже получены — не платим повторно
                res = json.loads(raw.read_text(encoding="utf-8"))
            for tag, model in (("a", MODEL_A), ("b", MODEL_B)):
                if tag in res and not res[tag].get("error"):
                    continue
                err = None
                for _ in range(2):
                    try:
                        res[tag] = ask(img, key, model)
                        break
                    except Exception as e:  # noqa: BLE001
                        err = str(e)[:200]
                else:
                    res[tag] = {"teams": [], "error": err}
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return doc, page, d, geo1, g2, res

    with ThreadPoolExecutor(4) as ex:
        results = sorted(ex.map(run, targets), key=lambda x: (x[0], x[1]))

    # место последнего блока предыдущей страницы (для продолжения команды): из cache_v2 или из нового разбора
    def prev_page_text(doc: str, page: int, done: dict) -> tuple[str | None, bool, str | None]:
        """(место последнего блока прошлой страницы, подтверждено ли оно, команда)."""
        if (doc, page - 1) in done:
            return done[(doc, page - 1)]
        f = v2_dir / doc / "pages_json" / f"page_{page - 1:03d}.json"
        if f.exists():
            rows = json.loads(f.read_text(encoding="utf-8"))["rows"]
            if rows and rows[-1].get("place") is not None:
                return str(rows[-1]["place"]), not rows[-1].get("place_uncertain"), rows[-1].get("team")
        return None, False, None

    summary: dict[str, dict] = {}
    last_text: dict[tuple[str, int], str] = {}
    usage = {"a": 0, "b": 0}
    for doc, page, d, geo1, g2, res in results:
        for tag in ("a", "b"):
            usage[tag] += int((res[tag].get("_usage") or {}).get("total_tokens") or 0)
        prev, prev_ok, prev_team = prev_page_text(doc, page, last_text)
        ba = blocks_with_place(res["a"].get("teams") or [], prev)
        bb = blocks_with_place(res["b"].get("teams") or [], prev)
        # основной разбор — тот поставщик, чьи блоки поблочно совпали с линиями таблицы (сначала A, затем B);
        # второй — проверяющий. Без совпадения с геометрией основной — A.
        geom, primary = None, "a"
        for tag, bl in (("a", ba), ("b", bb)):
            sizes = [len(t.get("members") or []) for _, t in bl]
            for g in (g2["counts"], geo1):
                fg = fit_geometry(g, sum(sizes))
                if fg and fg == sizes:
                    geom, primary = fg, tag
                    break
            if geom:
                break
        if primary == "b":
            ba, bb = bb, ba
        other, other_team = {}, {}
        for pt, t in bb:
            other_team[team_key(t.get("team"))] = pt
            for m in t.get("members") or []:
                other[person_key(m.get("fio"))] = pt
        members_a = [(pt, t, m) for pt, t in ba for m in (t.get("members") or [])]
        status = "geometry" if geom else "model_only"
        old = {person_key(r.get("fio")): r for r in d["rows"]}
        rows, st = [], {"rows": 0, "confirmed": 0, "unverified": 0}
        prev_meta = {"team": prev_team} if prev_team else None  # продолжение команды — её название с прошлой страницы
        cont_ids = {id(t) for i, (pt, t) in enumerate(ba) if i == 0 and not norm_pt(t.get("place_text"))
                    and (t.get("continues_from_previous_page") or not t.get("team"))}
        last_ok = True
        for pt, t, m in members_a:
            pk = person_key(m.get("fio"))
            p = parse_place(pt)
            agree_b = pt != "" and (other.get(pk) == pt or (status == "geometry" and t.get("team")
                                                          and other_team.get(team_key(t.get("team"))) == pt))
            confirmed = agree_b and p["place_status"] not in ("unparsed", "empty")
            if id(t) in cont_ids:
                # продолжение команды: место взято с прошлой страницы, второй поставщик тут не независим —
                # подтверждено, только если подтверждено место на прошлой странице
                confirmed = confirmed and prev_ok
            last_ok = confirmed
            o = old.get(pk) or {}
            rows.append({"fio": m.get("fio"), "birth_date": m.get("birth_date"), "place": p["place"], "rank": None,
                         "role": "Спортсмен", "team": t.get("team") or (prev_meta or {}).get("team"),
                         "region": m.get("region") or t.get("region") or o.get("region"), "score": t.get("score") or o.get("score"),
                         "place_text": pt, "place_range": p["place_range"], "place_status": p["place_status"],
                         "place_uncertain": not confirmed,
                         "place_check": ("geometry+two_providers" if status == "geometry" else "two_providers") if confirmed else None})
            prev_meta = t if t.get("team") else prev_meta
            st["rows"] += 1
            st["confirmed" if confirmed else "unverified"] += 1
        if ba:
            last_text[(doc, page)] = (ba[-1][0], last_ok, rows[-1]["team"] if rows else None)
        (out_dir / doc / "pages_json").mkdir(parents=True, exist_ok=True)
        (out_dir / doc / "pages_json" / f"page_{page:03d}.json").write_text(json.dumps({
            "rows": rows, "status": status, "geometry_counts": g2["counts"], "geometry_counts_v1": geo1,
            "geometry_angle": g2.get("angle"), "primary": MODEL_A if primary == "a" else MODEL_B, "ocr_blocks": [len(t.get("members") or []) for _, t in ba],
            "ocr_blocks_b": [len(t.get("members") or []) for _, t in bb], "rows_v2": len(d["rows"]),
            "error": res["a"].get("error") or res["b"].get("error"),
            "method": f"place_recover.py: текст ячейки «Место» дословно, {MODEL_A} + {MODEL_B}; геометрия block_row_counts_v2"},
            ensure_ascii=False, indent=1), encoding="utf-8")
        s = summary.setdefault(doc, {"pages": 0, "rows": 0, "rows_v2": 0, "confirmed": 0, "unverified": 0, "geometry_pages": 0,
                                     "place_status": {}})
        s["pages"] += 1
        s["rows"] += st["rows"]
        s["rows_v2"] += len(d["rows"])
        s["confirmed"] += st["confirmed"]
        s["unverified"] += st["unverified"]
        s["geometry_pages"] += status == "geometry"
        for r in rows:
            s["place_status"][r["place_status"]] = s["place_status"].get(r["place_status"], 0) + 1
        print(doc, page, status, len(d["rows"]), "→", st, res["a"].get("error") or "", res["b"].get("error") or "", flush=True)
    infer_sequence(out_dir)
    summary = {}
    for f in sorted(out_dir.glob("*/pages_json/page_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        s = summary.setdefault(f.parts[-3], {"pages": 0, "rows": 0, "rows_v2": 0, "confirmed": 0, "unverified": 0,
                                             "geometry_pages": 0, "place_status": {}, "place_check": {}})
        s["pages"] += 1
        s["rows"] += len(d["rows"])
        s["rows_v2"] += d.get("rows_v2", 0)
        s["geometry_pages"] += d["status"] == "geometry"
        for r in d["rows"]:
            s["unverified" if r["place_uncertain"] else "confirmed"] += 1
            s["place_status"][r["place_status"]] = s["place_status"].get(r["place_status"], 0) + 1
            s["place_check"][str(r.get("place_check"))] = s["place_check"].get(str(r.get("place_check")), 0) + 1
    (out_dir / "place_recover_summary.json").write_text(json.dumps(
        {"models": [MODEL_A, MODEL_B], "tokens": usage, "docs": summary}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
