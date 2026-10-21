"""ЕДИНСТВЕННЫЙ прогон на отложенных частях открытого формата Эвектио — после FREEZE (docs/realdata/djinni/evectio/FREEZE.json).
Проверяет хэши (данные, наши скрипты, протокол, деревья кода продукта в git), отказывается, если результат уже есть,
и пишет docs/realdata/djinni/evectio/external_evectio.json.
Запуск (из корня репозитория):  python tools/realdata/djinni/evectio/final_evectio.py --src <клон @85bbc78> --their-python <python их окружения>
"""
import argparse, hashlib, json, os, subprocess, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "../../../.."))
DOCS = os.path.join(REPO, "docs/realdata/djinni/evectio")
OUT = os.path.join(DOCS, "external_evectio.json")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--their-python", required=True)
    a = ap.parse_args()
    if os.path.exists(OUT):
        sys.exit("external_evectio.json уже есть — повторный прогон на отложенной части запрещён протоколом")
    fr = json.load(open(os.path.join(DOCS, "FREEZE.json"), encoding="utf-8"))
    bad = []
    for rel, h in fr["files_ours"].items():
        if sha(os.path.join(REPO, rel)) != h:
            bad.append(rel)
    for rel, h in fr["files_source"].items():
        if sha(os.path.join(a.src, rel)) != h:
            bad.append("src:" + rel)
    for rel, h in fr["product_trees"].items():
        cur = subprocess.run(["git", "rev-parse", f"HEAD:{rel}"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        if cur != h:
            bad.append("tree:" + rel)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "backend"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    if dirty:
        bad.append("незакоммиченные правки в backend/: " + dirty.replace("\n", "; ")[:300])
    if bad:
        sys.exit(f"хэши не совпадают с FREEZE: {bad}")
    sys.path.insert(0, HERE)
    import run_matching, run_resume  # noqa: E402

    m_out, r_out = "/tmp/a17_ev_hold_matching.json", "/tmp/a17_ev_hold_resume.json"
    run_matching.main(["--part", "holdout", "--src", a.src, "--their-python", a.their_python, "--out", m_out])
    run_resume.main(["--part", "holdout", "--src", a.src, "--out", r_out])
    their_res = subprocess.run([a.their_python, "-c", "import json;from app.validation.resume_eval import evaluate_all;"
                                "r=evaluate_all();print(json.dumps({'holdout':{k:v for k,v in r['holdout'].items() if k!='errors'},"
                                "'holdout_first_run':r['holdout_first_run']},ensure_ascii=False))"],
                               cwd=os.path.join(a.src, "backend"), capture_output=True, text=True, check=True).stdout
    res = {
        "what": "Наш продукт «один в один» на открытом формате внешней оценки соседней команды (MIT): подбор и разбор резюме",
        "run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "freeze_commit": fr.get("freeze_commit_note"), "headline": fr["headline"],
        "labels_note": "Метки пар (0–3) — их, созданы их генератором синтетических данных по скрытой истине их модели; это посредники, не люди. "
                       "Разметка резюме — их ручная.",
        "matching": json.load(open(m_out, encoding="utf-8")),
        "resume": {"ours": json.load(open(r_out, encoding="utf-8")), "their": json.loads(their_res)},
        "command": "python tools/realdata/djinni/evectio/final_evectio.py --src <клон github.com/archebaldo777/sporthackathon @85bbc78> --their-python <python их backend>",
    }
    os.makedirs(DOCS, exist_ok=True)
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("записано", OUT)


if __name__ == "__main__":
    main()
