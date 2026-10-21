"""docs/realdata/numbers_matching.json — цифры подбора для docs/NUMBERS.json (забирает tools/publish/gen_numbers.py, А4).

Только из JSON-артефактов прогонов, без констант:
  * matching  — docs/realdata/bench_holdout.json (бенчмарк на ОТЛОЖЕННЫХ синтетических мирах, bench_holdout.py run);
  * hh_match  — backend/app/modules/validation/data/hh_match_holdout.json (ОТЛОЖЕННЫЙ набор вакансий hh.ru, один
                прогон hh_holdout.py run) + docs/realdata/hh_holdout_adjudication.json (проверка спорных меток);
  * hh_match.dev — docs/realdata/hh_dev_parse.json (набор разработки, 414; оптимистично — на нём настраивались).
Нет артефакта — нет блока (и нет карточки на сайте).

  python tools/realdata/numbers_matching.py
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "docs/realdata/bench_holdout.json"
HOLD = ROOT / "backend/app/modules/validation/data/hh_match_holdout.json"
ADJ = ROOT / "docs/realdata/hh_holdout_adjudication.json"
DEV = ROOT / "docs/realdata/hh_dev_parse.json"
OUT = ROOT / "docs/realdata/numbers_matching.json"


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _vkn(x: dict | None) -> dict | None:
    if not x:
        return None
    return {"value": x.get("share", x.get("value")), "k": x["k"], "n": x["n"]}


def matching_block(b: dict) -> dict:
    w = b["worlds"][0]
    m = w["metrics"]["platform"]
    paired = w["paired_platform_minus"]
    return {
        "p5": {k: m["p@5"][k] for k in ("mean", "lo", "hi")},
        "mrr": {k: m["mrr"][k] for k in ("mean", "lo", "hi")},
        "ndcg10": {k: m["ndcg@10"][k] for k in ("mean", "lo", "hi")} if "ndcg@10" in m else None,
        "p10": {k: m["p@10"][k] for k in ("mean", "lo", "hi")} if "p@10" in m else None,
        "n_needs": w["n_needs"], "n_candidates": w["n_candidates"], "seed": w["seed"],
        "replication": [{"seed": x["seed"], "p5": x["metrics"]["platform"]["p@5"]["mean"],
                         "mrr": x["metrics"]["platform"]["mrr"]["mean"]} for x in b["worlds"][1:]],
        "baselines": {k: {"p5": v["p@5"]["mean"], "mrr": v["mrr"]["mean"]} for k, v in w["metrics"].items()
                      if k != "platform"},
        "platform_minus_bm25_p5": paired.get("bm25", {}).get("p@5"),
        "generated_at": b["generated_at"], "algorithm": b["algorithm"], "code_ref": b["code"],
        "set": f"отложенные синтетические миры (seed {', '.join(str(x['seed']) for x in b['worlds'])}; заморожены до прогона "
               f"{b['freeze']['frozen_at'][:10]}, веса выбирались на других мирах)",
        "what": b["what"],
        "recompute": b["recompute"],
    }


def hh_block(h: dict, adj: dict | None, dev: dict | None) -> dict:
    ov = h["overall"]
    fz = h["holdout"]["freeze"]
    out = {
        "n": ov["n"],
        "direction_ok": _vkn(ov["direction_ok"]),
        "grade_ok": _vkn(ov["grade_ok"]),
        "key_skills_recall": _vkn(ov.get("key_skills_recall")),
        "set": f"отложенный набор: {fz['n']} свежих вакансий hh.ru (SHA-256 {fz['manifest_sha256'][:12]}…, заморожен "
               f"{fz['frozen_at'][:10]}, прогон один)",
        "what": {
            "direction_ok": "Доля вакансий, где направление из разбора текста совпало с меткой hh.ru (роль hh.ru + слова "
                            "направления в названии); знаменатель — все вакансии направлений каталога.",
            "grade_ok": "Доля вакансий со словом грейда в названии, где грейд из разбора текста совпал с этим словом. Это "
                        "точность РАЗБОРА грейда вакансии, не точность теста кандидата.",
            "key_skills_recall": "Доля «Ключевых навыков» hh.ru (из справочника платформы), найденных разбором текста.",
            "confirmed_exact": "Доля вакансий, где в подборке есть кандидат с подтверждённым тестом грейдом точной категории "
                               "— на МОДЕЛЬНОМ пуле демо-мира (модели, не люди); проверка механики, не рынка.",
            "no_fsp_top5": "Доля кандидатов без учтённых достижений ФСП в первых пятёрках подборок против их доли в пуле: "
                           "отсутствие ФСП — штраф 0.",
        },
        "selection_model_pool": {
            "confirmed_exact": _vkn(ov.get("confirmed_exact")),
            "selection_nonempty": _vkn(ov.get("selection_nonempty")),
            "pool_note": "модельный пул демо-мира (2 660 модельных кандидатов, из них 2 160 со связками навыков hh.ru)",
        },
        "no_fsp_top5_share": (h.get("no_fsp") or {}).get("top5"),
        "no_fsp_pool_share": (h.get("no_fsp") or {}).get("pool"),
        "generated_at": h["holdout"]["run_started_at"], "code_ref": h["holdout"]["code"],
        "recompute": "cd backend && python ../tools/realdata/hh_holdout.py run (один раз; новый прогон — новый отложенный "
                     "набор: collect → freeze → run)",
    }
    if adj:
        out["direction_ok_adjudicated"] = {k: adj["direction"][k] for k in ("value", "k", "n")}
        out["grade_ok_adjudicated"] = {k: adj["grade"][k] for k in ("value", "k", "n")}
        out["noisy_labels"] = {"direction": adj["direction"]["noisy_labels"], "grade": adj["grade"]["noisy_labels"]}
        out["what"]["direction_ok_adjudicated"] = (
            "То же после независимой проверки спорных меток: где разбор и метка hh.ru расходятся, два арбитра — модели "
            "разных компаний, не видевшие ни метку, ни ответ разбора, — определяют направление; итог только при их "
            "согласии, иначе метка hh.ru. Модели, не люди (протокол — docs/realdata/hh_holdout_PROTOCOL.md).")
        out["what"]["grade_ok_adjudicated"] = out["what"]["direction_ok_adjudicated"].replace("направление", "грейд")
        out["adjudication_ref"] = "docs/realdata/hh_holdout_adjudication.json"
        # дополнительно, ВНЕ протокола (выведено после прогона — не главная величина): вакансии, которые оба арбитра
        # признали не IT (метка hh.ru по роли ошибочна); разбор на них чаще честно не называет направление
        rows = [r for r in adj["rows"] if r["field"] == "direction"]
        not_it = [r for r in rows if r["final"] == "not_it"]
        d = adj["direction"]
        n_it = d["n"] - len(not_it)
        out["supplementary_outside_protocol"] = {
            "not_it_by_arbiters": len(not_it),
            "parser_none_on_not_it": sum(1 for r in not_it if r.get("parser") is None),
            "direction_ok_it_only": {"value": round(d["k"] / n_it, 4) if n_it else None, "k": d["k"], "n": n_it},
            "what": "Дополнительно, вне протокола (посчитано после прогона): доля верного направления среди вакансий, "
                    "которые оба арбитра признали IT-вакансиями; на не-IT вакансиях разбор не называет направление "
                    "(parser_none_on_not_it) — это верное поведение, но по протоколу засчитано как ошибка."}
    if dev:
        out["dev"] = {"set": dev["set"], "direction_ok": dev["direction_ok"], "grade_ok": dev["grade_ok"],
                      "generated_at": dev["generated_at"], "recompute": dev["recompute"]}
    return out


def main() -> None:
    b, h, adj, dev = _load(BENCH), _load(HOLD), _load(ADJ), _load(DEV)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "source": "tools/realdata/numbers_matching.py (только из артефактов прогонов)"}
    if b:
        out["matching"] = matching_block(b)
    if h:
        out["hh_match"] = hh_block(h, adj, dev)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("записано:", OUT.relative_to(ROOT), "блоки:", [k for k in out if k in ("matching", "hh_match")])


if __name__ == "__main__":
    main()
