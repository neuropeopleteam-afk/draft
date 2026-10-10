#!/usr/bin/env python3
"""Синхронизация банка заданий в сборку бэкенда: копия пакета assessment_bank с фильтром качества.

Пакет банка ведут отдельные авторы в своём репозитории (по умолчанию ../../bank относительно этого файла,
или переменная BANK_SRC). Бэкенд импортирует его как обычный пакет из backend/assessment_bank —
копия лежит в репозитории платформы, поэтому сборка воспроизводима без доступа к репозиторию банка.

Что делает скрипт (запускается deploy_moscow.sh перед каждой выкладкой — новые семейства попадают сами):
1. копирует рабочее дерево пакета (включая ещё не закоммиченные авторами семейства) во временный каталог,
   без __pycache__ и *.pyc;
2. проверяет каждое YAML-описание отдельно, в чистом процессе: схема FamilySpec, импорт генератора,
   generate(seed) на нескольких seed, public_view() без ключа и рубрики. Семейство с ошибкой исключается
   из копии (YAML + модуль), остальные не страдают — одна недописанная задача не ломает весь тест;
3. запускает валидатор банка (python -m assessment_bank validate) на сокращённом числе seed и исключает
   семейства со статусом FAIL (нужны node, bash, git — как для обычной валидации банка);
4. проверяет, что реестр (load_specs) и адаптивный пул собираются;
5. заменяет backend/assessment_bank и пишет манифест BANK_SYNC.json (источник, коммит, включённые и
   исключённые семейства с причинами, сводка валидатора);
6. с --commit — коммитит изменения, если они есть.

Пакет банка скрипт не меняет: читает только рабочее дерево.

    python3 tools/sync_bank.py [--src ../bank] [--seeds 20] [--verify-seeds 3] [--no-validate] [--commit]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
DST = REPO / "backend" / "assessment_bank"
DEFAULT_SRC = REPO.parent / "bank"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.egg-info")

# Проверка одного семейства — в отдельном процессе (YAML с ошибкой не роняет проверку остальных).
CHECK_ONE = r'''
import importlib, json, sys, yaml
from assessment_bank.schema import FamilySpec, Variant
path = sys.argv[1]
out = {"path": path}
try:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    spec = FamilySpec(**data)
    out["family_id"] = spec.family_id
    out["direction"] = spec.direction
    out["format"] = spec.format
    out["generator"] = spec.generator
    if path.split("/")[-2] != spec.direction:
        raise ValueError(f"лежит в каталоге {path.split('/')[-2]}, а direction={spec.direction}")
    mod = importlib.import_module(spec.generator)
    if getattr(mod, "FAMILY_ID", None) != spec.family_id:
        raise ValueError("FAMILY_ID модуля не совпадает с YAML")
    seeds = [1, 2, 3] if spec.canary else [10_000_019, 123_456_791, 2_000_000_011]
    for seed in seeds:
        v = mod.generate(seed)
        if not isinstance(v, Variant):
            raise TypeError("generate вернул не Variant")
        if v.variant_id != f"{spec.family_id}:{seed}" or v.meta.format != spec.format:
            raise ValueError("variant_id/format не соответствуют YAML")
        pv = json.dumps(v.public_view(), ensure_ascii=False)
        if '"answer_key"' in pv or '"rubric"' in pv or '"checks"' in pv:
            raise ValueError("public_view раскрывает ключ/рубрику")
    out["ok"] = True
except Exception as e:  # noqa: BLE001
    out["ok"] = False
    out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
print(json.dumps(out, ensure_ascii=False))
'''

FINAL_CHECK = r'''
import json
from assessment_bank import load_specs
from assessment_bank.psychometrics import pool_from_specs
specs = load_specs()
pool = pool_from_specs(specs.values())
by = {}
for s in specs.values():
    d = by.setdefault(s.direction, {"families": 0, "canary": 0, "formats": {}})
    d["families"] += 1
    d["canary"] += int(s.canary)
    d["formats"][s.format] = d["formats"].get(s.format, 0) + 1
print(json.dumps({"n_families": len(specs), "pool": len(pool), "by_direction": by}, ensure_ascii=False))
'''


def run_py(code_or_args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(cwd), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, *code_or_args], cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=timeout)


def git_info(src: Path) -> dict:
    def g(*a: str) -> str:
        r = subprocess.run(["git", "-C", str(src), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    status = g("status", "--porcelain", "--", "assessment_bank")
    return {"commit": g("rev-parse", "--short", "HEAD") or None, "dirty_files": len(status.splitlines()) if status else 0}


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "BANK_SYNC.json" and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def remove_family(pkg_root: Path, yaml_path: Path, generator: str | None) -> None:
    yaml_path.unlink(missing_ok=True)
    if generator:
        mod_file = pkg_root.parent / (generator.replace(".", "/") + ".py")
        # Модуль удаляем, только если на него больше не ссылается ни одно оставшееся YAML
        still_used = any(generator in y.read_text(encoding="utf-8") for y in (pkg_root / "families").glob("*/*.yaml"))
        if mod_file.exists() and not still_used:
            mod_file.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=os.environ.get("BANK_SRC", str(DEFAULT_SRC)))
    ap.add_argument("--seeds", type=int, default=20, help="seed на семейство для валидатора банка")
    ap.add_argument("--verify-seeds", type=int, default=3, help="на скольких seed исполнять проверки ключа")
    ap.add_argument("--no-validate", action="store_true", help="без валидатора банка (только проверка генерации)")
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()

    src = Path(a.src).resolve()
    pkg_src = src / "assessment_bank"
    if not (pkg_src / "registry.py").exists():
        print(f"[sync_bank] нет пакета банка в {pkg_src}", file=sys.stderr)
        return 2
    stage = Path(tempfile.mkdtemp(prefix="bank_sync_"))
    pkg = stage / "assessment_bank"
    shutil.copytree(pkg_src, pkg, ignore=IGNORE)
    for extra in ("README.md", "LICENSE", "requirements.txt"):
        if (src / extra).exists():
            shutil.copy2(src / extra, pkg / f"BANK_{extra}")

    excluded: list[dict] = []
    checked: list[dict] = []
    for y in sorted((pkg / "families").glob("*/*.yaml")):
        rel = str(y.relative_to(pkg))
        r = run_py(["-c", CHECK_ONE, str(y)], cwd=stage, timeout=120)
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            res = {"path": str(y), "ok": False, "error": (r.stderr or "нет вывода")[-300:]}
        res["path"] = rel
        checked.append(res)
    seen: dict[str, str] = {}
    for res in checked:
        fid = res.get("family_id")
        if res["ok"] and fid in seen:
            res["ok"], res["error"] = False, f"повтор family_id (уже есть в {seen[fid]})"
        if res["ok"]:
            seen[fid] = res["path"]
    for res in checked:
        if not res["ok"]:
            excluded.append({"path": res["path"], "family_id": res.get("family_id"), "stage": "generate",
                             "reason": res["error"]})
            remove_family(pkg, pkg / res["path"], res.get("generator"))

    validation = None
    if not a.no_validate:
        out_dir = stage / "_validation"
        r = run_py(["-m", "assessment_bank", "validate", "--seeds", str(a.seeds), "--verify-seeds",
                    str(a.verify_seeds), "--out", str(out_dir)], cwd=stage, timeout=1800)
        rep = out_dir / "validation_report.json"
        if rep.exists():
            data = json.loads(rep.read_text(encoding="utf-8"))
            validation = {"summary": data.get("summary"), "seeds": a.seeds, "verify_seeds": a.verify_seeds}
            fams = data.get("families") or []
            if isinstance(fams, dict):
                fams = [{"family_id": k, **v} for k, v in fams.items()]
            for f in fams:
                if str(f.get("status")).upper() == "FAIL":
                    fid = f.get("family_id")
                    path = next((c["path"] for c in checked if c.get("family_id") == fid and c["ok"]), None)
                    gen = next((c.get("generator") for c in checked if c.get("family_id") == fid), None)
                    reasons = (f.get("errors") or []) + (f.get("check_failures") or [])
                    excluded.append({"path": path, "family_id": fid, "stage": "validator",
                                     "reason": "; ".join(map(str, reasons))[:300] or "FAIL"})
                    if path:
                        remove_family(pkg, pkg / path, gen)
        else:
            validation = {"error": "валидатор банка не выполнился", "stderr": (r.stderr or "")[-500:]}
            print("[sync_bank] ВНИМАНИЕ: валидатор банка не выполнился — оставлены семейства, прошедшие проверку "
                  "генерации", file=sys.stderr)

    r = run_py(["-c", FINAL_CHECK], cwd=stage)
    if r.returncode != 0:
        print("[sync_bank] реестр не собирается после фильтра:\n" + r.stderr[-2000:], file=sys.stderr)
        return 3
    final = json.loads(r.stdout.strip().splitlines()[-1])

    old_hash = tree_hash(DST) if DST.exists() else None
    new_hash = tree_hash(pkg)
    manifest = {
        # путь рабочего места в манифест не пишем: банк — соседний репозиторий
        "source": "../bank", **git_info(src), "content_hash": new_hash,
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_families": final["n_families"], "by_direction": final["by_direction"],
        "excluded": excluded, "validation": validation,
    }
    if old_hash == new_hash and (DST / "BANK_SYNC.json").exists():
        print(f"[sync_bank] без изменений: {final['n_families']} семейств, исключено {len(excluded)}")
        shutil.rmtree(stage, ignore_errors=True)
        return 0
    (pkg / "BANK_SYNC.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(pkg, DST)
    shutil.rmtree(stage, ignore_errors=True)
    print(f"[sync_bank] {final['n_families']} семейств ({', '.join(f'{k}: {v['families']}' for k, v in sorted(final['by_direction'].items()))}); "
          f"исключено {len(excluded)}; источник {manifest['commit']}"
          f"{' + ' + str(manifest['dirty_files']) + ' незакоммиченных файлов' if manifest['dirty_files'] else ''}")
    for e in excluded:
        print(f"  исключено: {e['family_id'] or e['path']} [{e['stage']}] {e['reason'][:160]}")
    if a.commit:
        subprocess.run(["git", "-C", str(REPO), "add", "-A", "backend/assessment_bank"], check=True)
        diff = subprocess.run(["git", "-C", str(REPO), "diff", "--cached", "--quiet", "--", "backend/assessment_bank"])
        if diff.returncode != 0:
            msg = (f"Банк заданий: синхронизация ({final['n_families']} семейств, источник {manifest['commit']}"
                   f"{'+' if manifest['dirty_files'] else ''}, исключено {len(excluded)})")
            subprocess.run(["git", "-C", str(REPO), "commit", "-q", "-m", msg, "--", "backend/assessment_bank"],
                           check=True)
            print(f"[sync_bank] коммит: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
