#!/usr/bin/env python3
"""Проверка публикуемого дерева по КАЖДОМУ коммиту истории (правила — те же, что в tools/publish/check_public_tree.py).

    python3 ops/publish_history_scan.py [--repo .] [--rev main] [--values FILE] [--paths-out FILE] [--json FILE]

Обходит все коммиты `--rev` (по умолчанию HEAD), собирает уникальные пары (путь, blob) и проверяет каждую один раз:
быстро даже на тысячах коммитов. Печатает пути с нарушениями (правило, число коммитов, есть ли путь в голове) — без
самих найденных значений. `--paths-out` — список путей с нарушениями, которых НЕТ в голове ветки (их можно целиком
вычистить из истории: ops/publish_repo.sh --filter); пути, которые есть в голове, требуют правки содержимого и
печатаются отдельно. Сообщения коммитов проверяются теми же правилами.
Код выхода: 0 — ни в одном коммите (ни в файлах, ни в сообщениях) нарушений нет, 1 — есть.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_rules(repo: str):
    """Правила берутся из check_public_tree.py проверяемого репозитория (единый источник), иначе — из соседнего дерева."""
    for p in (Path(repo) / "tools/publish/check_public_tree.py", HERE.parent / "tools/publish/check_public_tree.py"):
        if p.exists():
            spec = importlib.util.spec_from_file_location("cpt", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)  # type: ignore[union-attr]
            return m
    sys.exit("нет tools/publish/check_public_tree.py")


def git(repo: str, *a: str) -> bytes:
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, check=True).stdout


def blob_rules(c, path: str, data: bytes, values: list[bytes]) -> set[str]:
    """Правила check_public_tree, нарушенные содержимым `data` по пути `path` (та же логика, что в его main)."""
    out: set[str] = set()
    if path in c.IGNORE_SELF:
        return out
    if c.BAD_NAMES.search(path) and path not in ("infra/llm-local/llm-local.env",):
        out.add("запрещённое имя файла")
    if len(data) > c.MAX_BYTES:
        out.add("файл больше 20 МБ")
    if any(v in data for v in values):
        out.add("значение секрета из файла --values")
    if c.SKIP.search(path):
        return out
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return out
    for line in text.splitlines():
        if any(not c.IP_OK.match(m.group(1)) for m in c.IPV4.finditer(line)):
            out.add("публичный IPv4-адрес")
        for rule, rx in c.RULES:
            if rule not in c.ALLOW.get(path, ()) and rx.search(line):
                out.add(rule)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--values", default=None)
    ap.add_argument("--paths-out", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    c = load_rules(a.repo)
    values = c.load_values(a.values)
    commits = git(a.repo, "rev-list", a.rev).decode().split()
    pairs: dict[tuple[str, str], int] = defaultdict(int)  # (путь, blob) → в скольких коммитах встречается
    for sha in commits:
        for ent in git(a.repo, "ls-tree", "-r", "-z", sha).decode("utf-8", "replace").split("\0"):
            meta, _, path = ent.partition("\t")
            parts = meta.split()
            if path and len(parts) == 3 and parts[1] == "blob":
                pairs[(path, parts[2])] += 1
    head = set(git(a.repo, "ls-tree", "-r", "--name-only", "-z", a.rev).decode("utf-8", "replace").split("\0")) - {""}
    batch = subprocess.Popen(["git", "-C", a.repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    seen_blob: dict[str, bytes] = {}
    by_path: dict[str, dict] = {}
    for (path, oid), n in sorted(pairs.items()):
        assert batch.stdin and batch.stdout
        batch.stdin.write(oid.encode() + b"\n")
        batch.stdin.flush()
        hdr = batch.stdout.readline().split()
        data = batch.stdout.read(int(hdr[2]))
        batch.stdout.read(1)
        rules = blob_rules(c, path, data, values)
        if rules:
            d = by_path.setdefault(path, {"rules": set(), "commits": 0, "blobs": 0, "in_head": path in head})
            d["rules"] |= rules
            d["commits"] += n
            d["blobs"] += 1
    batch.stdin.close()  # type: ignore[union-attr]
    gone = sorted(p for p, d in by_path.items() if not d["in_head"])
    kept = sorted(p for p, d in by_path.items() if d["in_head"])
    for title, lst in (("пути, которых нет в голове (вычищаются --filter целиком)", gone),
                       ("пути, которые есть в голове (нарушение в старых версиях или сейчас — нужна правка содержимого)", kept)):
        print(f"== {title}: {len(lst)}")
        for p in lst:
            d = by_path[p]
            print(f"  {p}: {', '.join(sorted(d['rules']))}; коммитов {d['commits']}, версий {d['blobs']}")
    # сообщения коммитов (check_public_tree их не видит, а публикуются они вместе с историей)
    log = git(a.repo, "log", "--format=%H%x00%B%x01", a.rev).decode("utf-8", "replace")
    bad_msg: dict[str, int] = defaultdict(int)
    for ent in log.split("\x01"):
        if "\x00" in ent:
            for r in blob_rules(c, "COMMIT_MESSAGE", ent.split("\x00", 1)[1].encode("utf-8"), values):
                bad_msg[r] += 1
    if bad_msg:
        print("== сообщения коммитов с нарушениями: " + ", ".join(f"{r}: {n}" for r, n in sorted(bad_msg.items())))
    print(f"коммитов: {len(commits)}; уникальных (путь, версия): {len(pairs)}; путей с нарушениями: {len(by_path)}; "
          f"нарушений в сообщениях: {sum(bad_msg.values())}")
    if a.paths_out:
        Path(a.paths_out).write_text("".join(p + "\n" for p in gone), encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps({p: {**d, "rules": sorted(d["rules"])} for p, d in by_path.items()},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if by_path or bad_msg else 0


if __name__ == "__main__":
    sys.exit(main())
