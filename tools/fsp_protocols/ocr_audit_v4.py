"""Независимый аудит индекса протоколов ФСП (v4 — по итоговому index_v5.json, который идёт на стенд).

Отличия от прежнего аудита (ocr_audit.py, v2 — история):
  * новая выборка: зерно = первые 8 hex-знаков SHA-256 файла индекса (не выбирается человеком), не меньше 120 записей,
    стратификация по документам (протоколам): n_h = max(4, round(N·N_h/ΣN)), не больше N_h;
  * проверяющая модель — третьего поставщика (по умолчанию openai/gpt-5.4): в построении индекса участвовали
    google/gemini-2.5-pro (распознавание) и anthropic/claude-sonnet-5.5 (перекрёстная проверка мест);
  * БЕЗ подсказки ФИО: модель переписывает ВСЕ строки участников страницы (ФИО, дата рождения, место), а
    сопоставление с записью индекса делает код после ответа. Для командных протоколов первой картинкой даётся
    предыдущая страница — чтобы место продолжения команды было видно;
  * все расхождения разбираются глазами по изображению страницы (adjudication.json); итог — по разбору.

  plan   <index.json> <out_dir> [--n 150]                  — на сервере: выборка (с ПДн) остаётся в out_dir (600),
         печатаются зерно, распределение по документам и SHA-256 выборки — коммит в git ДО сверки.
  check  <sample.json> <pdf_dir> <out_check.json>          — в песочнице: один прогон проверяющей модели.
  report <sample.json> <check.json> <adjudication.json> <ocr_audit_v4.json> — доли ошибок ФИО / места / даты рождения
         (95 % интервал Уилсона) и «место отсутствует» отдельно, с причинами.
"""
from __future__ import annotations

import base64
import collections
import difflib
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

MODEL = os.environ.get("FSP_AUDIT_MODEL", "openai/gpt-5.4")
BUILD_MODELS = ["google/gemini-2.5-pro", "anthropic/claude-sonnet-5.5"]
NO_PLACE_DOCS = {"e5miei2aikivxs93d6qz2iqfnfaf0xp1.pdf"}  # список кандидатов в сборную — мест нет по построению


def _file(r: dict) -> str:
    return r["pdf_url"].rsplit("/", 1)[-1]


def norm_fio(s: str | None) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[^а-яa-z0-9\- ]", " ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_date(s: str | None) -> str | None:
    """«ДД.ММ.ГГГГ» или «ГГГГ-ММ-ДД» → «ГГГГ-ММ-ДД»."""
    if not s:
        return None
    s = str(s).strip()
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    return s if m else None


def plan(index_path: Path, out_dir: Path, n: int) -> None:
    raw = index_path.read_bytes()
    index_sha = hashlib.sha256(raw).hexdigest()
    seed = int(index_sha[:8], 16)
    recs = json.loads(raw)["records"]
    pop = [(i, r) for i, r in enumerate(recs) if r.get("person")]
    strata: dict[str, list] = collections.defaultdict(list)
    for i, r in pop:
        strata[_file(r)].append((i, r))
    total = len(pop)
    alloc = {f: min(len(v), max(4, round(n * len(v) / total))) for f, v in sorted(strata.items())}
    rnd = random.Random(seed)
    rows = []
    for f in sorted(strata):
        items = sorted(strata[f], key=lambda x: (x[1].get("page") or 0, x[1].get("key_hash") or "", x[0]))
        for i, r in rnd.sample(items, alloc[f]):
            rows.append({"idx": i, "file": f, "doc_id": r.get("doc_id"), "event_id": r.get("event_id"),
                         "page": r.get("page"), "team_protocol": bool(r.get("team")), "fio_norm": r.get("fio_norm"),
                         "birth_date": r.get("birth_date"), "place": r.get("place"), "place_range": r.get("place_range"),
                         "place_text": r.get("place_text"), "place_status": r.get("place_status"),
                         "place_uncertain": bool(r.get("place_uncertain")), "team": r.get("team"), "key_hash": r.get("key_hash")})
    commit = hashlib.sha256("\n".join(f"{x['idx']}|{x['key_hash']}|{x['event_id']}|{x['page']}" for x in rows).encode()).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"index": index_path.name, "index_sha256": index_sha, "seed": seed, "seed_rule": "int(sha256(index)[:8], 16)",
            "population": total, "n": len(rows), "allocation": {f: {"population": len(strata[f]), "n": alloc[f]} for f in sorted(strata)},
            "sample_sha256": commit}
    p = out_dir / "sample.json"
    p.write_text(json.dumps({**meta, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(p, 0o600)
    print(json.dumps(meta, ensure_ascii=False))


PROMPT = """{ctx}Перепиши ВСЕ строки участников (спортсменов) из таблицы на {which} — сверху вниз, ничего не пропуская.
Верни СТРОГО JSON: {{"rows": [{{"place_text": "текст ячейки «Место» для этой строки ДОСЛОВНО (\\"5\\", \\"9-10\\", \\"б/м\\", \\"DSQ\\"…); в командных таблицах место — в объединённой ячейке команды, повтори его для каждого участника; пустая строка, если колонки «Место» нет",
 "fio": "ФИО ровно как напечатано", "birth_date": "дата рождения как напечатана или null", "team": "команда или null"}}]}}
Строки судей, тренеров, подписи и шапку не включай. Никакого текста кроме JSON."""
CTX_TEAM = ("Даны две страницы протокола командного соревнования ФСП России: первая — предыдущая (только для справки), "
            "вторая — проверяемая. Если в начале проверяемой страницы идут участники без места и названия команды — это "
            "продолжение команды с предыдущей страницы: укажи для них место и название этой команды с предыдущей страницы.\n")


def _render(pdf: Path, page: int, out: Path) -> None:
    subprocess.run(["pdftoppm", "-r", "150", "-jpeg", "-f", str(page), "-l", str(page), "-singlefile", str(pdf), str(out)[:-4]],
                   check=True)


def _ask(images: list[Path], text: str, key: str) -> dict:
    content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()}}
               for p in images]
    content.append({"type": "text", "text": text})
    body = {"model": MODEL, "temperature": 0, "max_tokens": 12000, "reasoning": {"effort": "low"},
            "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    err = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                resp = json.loads(r.read())
            txt = resp["choices"][0]["message"]["content"]
            out = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
            out["_usage"] = resp.get("usage", {})
            return out
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
    return {"rows": [], "error": err}


def check(sample_path: Path, pdf_dir: Path, out_path: Path) -> None:
    key = os.environ["OPENROUTER_API_KEY"]
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    pages = sorted({(r["file"], r["page"], r["team_protocol"]) for r in sample["rows"]})

    def run(t):
        f, page, team = t
        with tempfile.TemporaryDirectory() as td:
            cur = Path(td) / "cur.jpg"
            _render(pdf_dir / f, page, cur)
            imgs = [cur]
            if team and page > 1:
                prev = Path(td) / "prev.jpg"
                _render(pdf_dir / f, page - 1, prev)
                imgs = [prev, cur]
            text = PROMPT.format(ctx=CTX_TEAM if len(imgs) == 2 else "Это страница официального протокола (или списка) ФСП России.\n",
                                 which="проверяемой (второй) странице" if len(imgs) == 2 else "этой странице")
            return f"{f}|{page}", _ask(imgs, text, key)

    with ThreadPoolExecutor(4) as ex:
        res = dict(ex.map(run, pages))
    usage = collections.Counter()
    for v in res.values():
        for k in ("prompt_tokens", "completion_tokens"):
            usage[k] += int((v.get("_usage") or {}).get(k) or 0)
        usage["cost"] += float((v.get("_usage") or {}).get("cost") or 0)
    out = {"model": MODEL, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "sample_sha256": sample["sample_sha256"], "pages": len(pages), "usage": dict(usage), "results": res}
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(out_path, 0o600)
    print(json.dumps({"pages": len(pages), "errors": sum(1 for v in res.values() if v.get("error")), "usage": dict(usage)}))


def _parse_place(t: str | None) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.fsp_protocols.place_recover import parse_place
    return parse_place(t)


def compare(sample: dict, chk: dict) -> list[dict]:
    """Сопоставление записи выборки со строками, переписанными проверяющей моделью (по сходству ФИО — ПОСЛЕ ответа)."""
    out = []
    for r in sample["rows"]:
        rows = (chk["results"].get(f"{r['file']}|{r['page']}") or {}).get("rows") or []
        fio = norm_fio(r["fio_norm"])
        best, score = None, 0.0
        for v in rows:
            s = difflib.SequenceMatcher(None, fio, norm_fio(v.get("fio"))).ratio()
            if s > score:
                best, score = v, s
        item = {"idx": r["idx"], "file": r["file"], "page": r["page"], "match_score": round(score, 3)}
        if best is None or score < 0.6:
            item.update(found=False, fio_ok=None, birth_ok=None, place_ok=None)
            out.append(item)
            continue
        item["found"] = True
        item["fio_ok"] = norm_fio(best.get("fio")) == fio
        vb, ib = norm_date(best.get("birth_date")), r.get("birth_date")
        item["birth_ok"] = None if (vb is None and ib is None) else (vb == ib)
        vp = _parse_place(best.get("place_text"))
        if r["file"] in NO_PLACE_DOCS:
            item["place_ok"] = None  # мест нет по построению
        elif r.get("place") is not None:
            item["place_ok"] = vp["place"] == r["place"]
        elif r.get("place_range"):
            item["place_ok"] = vp["place_range"] == r["place_range"]
        else:
            item["place_ok"] = vp["place_status"] == r.get("place_status")
        item["verifier"] = {"fio": best.get("fio"), "birth_date": best.get("birth_date"), "place_text": best.get("place_text")}
        out.append(item)
    return out


def wilson(k: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def report(sample_path: Path, check_path: Path, adj_path: Path, out_path: Path) -> None:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    chk = json.loads(check_path.read_text(encoding="utf-8"))
    adj = json.loads(adj_path.read_text(encoding="utf-8")) if adj_path.exists() else {"items": {}}
    cmp_ = compare(sample, chk)
    by_idx = {r["idx"]: r for r in sample["rows"]}
    res = {"fio": [0, 0], "birth_date": [0, 0], "place": [0, 0]}
    verifier_disagree = collections.Counter()
    missing = collections.Counter()
    adjudicated = collections.Counter()
    not_athlete = 0  # найдено при разборе: строка не спортсмена (тренер/специалист), ошибочно записанная спортсменом
    for c in cmp_:
        r = by_idx[c["idx"]]
        a = adj["items"].get(str(c["idx"]), {})
        not_athlete += a.get("record") == "not_athlete"
        for fld, ok_key in (("fio", "fio_ok"), ("birth_date", "birth_ok"), ("place", "place_ok")):
            ok = c.get(ok_key)
            if ok is False or (not c["found"]):
                verifier_disagree[fld] += 1
            # итог — по разбору глазами: «index_error» / «index_ok» / «not_applicable»
            verdict = a.get(fld)
            if verdict is None:
                if ok is None and c["found"]:
                    verdict = "not_applicable"
                elif ok:
                    verdict = "index_ok"
                else:
                    verdict = "not_adjudicated"
            adjudicated[f"{fld}:{verdict}"] += 1
            if verdict in ("index_ok", "index_error"):
                res[fld][1] += 1
                res[fld][0] += verdict == "index_error"
        if r.get("place") is None and not r.get("place_range"):
            reason = r.get("place_status") or "unknown"
            missing[reason] += 1
        elif r.get("place") is None:
            missing["shared_range"] += 1
    by_cause = {
        "not_a_protocol": "нет мест по построению: список кандидатов в сборную",
        "no_place": "нет мест по построению: «б/м» (без места) в протоколе",
        "disqualified": "нет мест по построению: дисквалификация (DSQ)",
        "shared_range": "место поделено — диапазон «a-b» (place_range), не одно число",
        "not_recognized": "не распознана таблица",
    }
    out = {
        "what": "Независимый аудит распознавания протоколов ФСП (v4): новая стратифицированная выборка, проверяющая модель "
                "третьего поставщика без подсказки ФИО, все расхождения разобраны глазами по изображению страницы",
        "registered_plan": "docs/realdata/fsp_protocols/ocr_audit_v4_plan.json (коммит до сверки)",
        "index": sample["index"], "index_sha256": sample["index_sha256"], "seed": sample["seed"],
        "sample_sha256": sample["sample_sha256"], "population": sample["population"], "n": sample["n"],
        "strata": len(sample["allocation"]), "verifier_model": chk["model"], "build_models": BUILD_MODELS,
        "checked_at": chk["checked_at"], "pages_checked": chk["pages"], "usage": chk.get("usage"),
        "errors": {k: {"errors": v[0], "checked": v[1], "rate": round(v[0] / v[1], 4) if v[1] else None, "ci95": wilson(v[0], v[1])}
                   for k, v in res.items()},
        "record_not_athlete": {"errors": not_athlete, "checked": len(cmp_), "rate": round(not_athlete / len(cmp_), 4),
                               "ci95": wilson(not_athlete, len(cmp_)),
                               "what": "запись тренера/специалиста, ошибочно записанная спортсменом (найдено при разборе глазами)"},
        "verifier_disagreements_before_adjudication": dict(verifier_disagree),
        "adjudication_counts": dict(sorted(adjudicated.items())),
        "place_absent": {"total": sum(missing.values()), "by_reason": {k: {"count": v, "reason": by_cause.get(k, k)} for k, v in sorted(missing.items())}},
        "adjudication_notes": adj.get("notes", []),
        "recompute": "python3 tools/fsp_protocols/ocr_audit_v4.py report <sample.json> <check.json> <adjudication.json> docs/realdata/fsp_protocols/ocr_audit_v5.json",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["errors"], ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "plan":
        n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 150
        plan(Path(sys.argv[2]), Path(sys.argv[3]), n)
    elif cmd == "check":
        check(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    elif cmd == "compare":  # промежуточная таблица расхождений для разбора глазами (с ПДн — только локально / data_local)
        s = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        c = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        Path(sys.argv[4]).write_text(json.dumps(compare(s, c), ensure_ascii=False, indent=1), encoding="utf-8")
    elif cmd == "report":
        report(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
