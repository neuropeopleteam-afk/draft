#!/usr/bin/env python3
"""Проверка: ни одно значение из файла значений не встречается в истории git (все объекты, достижимые из ссылок).

    python tools/publish/scan_history_values.py --values /путь/к/файлу_значений [--repo .] [--refs main integ/wave4 | --all]

Файл значений — по одному значению в строке либо JSON-строки {"v": "...", "src": "..."}; хранить его вне репозитория
(права 600). Значения НЕ печатаются: вывод — число совпадений, коммиты (короткий хеш), путь файла и метка источника.
Проверяются: содержимое всех файлов (blob) каждой версии, сообщения коммитов и тегов, имена файлов.
Код выхода: 0 — совпадений нет, 1 — есть, 2 — ошибка запуска.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def git(repo: str, *args: str, inp: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], input=inp, capture_output=True, check=True).stdout


def load_values(path: str) -> list[tuple[bytes, str]]:
    out: list[tuple[bytes, str]] = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines()):
        line = line.rstrip("\n")
        if not line.strip():
            continue
        v, src = line, f"строка {i + 1}"
        if line.startswith("{"):
            try:
                d = json.loads(line)
                v, src = d["v"], d.get("src", src)
            except Exception:
                pass
        if len(v) >= 6:
            out.append((v.encode("utf-8"), src))
    return out


def objects(repo: str, refs: list[str]) -> list[tuple[str, str]]:
    """(oid, path) всех объектов, достижимых из refs."""
    raw = git(repo, "rev-list", "--objects", *refs).decode("utf-8", "replace")
    res = []
    for line in raw.splitlines():
        oid, _, path = line.partition(" ")
        res.append((oid, path))
    return res


def cat_batch(repo: str, oids: list[str]):
    p = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert p.stdin and p.stdout

    import threading

    def feed():
        for o in oids:
            p.stdin.write(o.encode() + b"\n")
        p.stdin.close()

    threading.Thread(target=feed, daemon=True).start()
    while True:
        header = p.stdout.readline()
        if not header:
            break
        parts = header.split()
        if len(parts) < 3:
            continue
        oid, typ, size = parts[0].decode(), parts[1].decode(), int(parts[2])
        data = p.stdout.read(size)
        p.stdout.read(1)
        yield oid, typ, data
    p.wait()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--values", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--refs", nargs="*", default=[])
    ap.add_argument("--all", action="store_true", help="все ссылки репозитория")
    a = ap.parse_args()
    vals = load_values(a.values)
    if not vals:
        print("нет значений для проверки", file=sys.stderr)
        return 2
    refs = ["--all"] if a.all or not a.refs else a.refs
    objs = objects(a.repo, refs)
    paths: dict[str, set[str]] = {}
    for oid, path in objs:
        paths.setdefault(oid, set()).add(path)
    hits: dict[str, set[int]] = {}
    n_blob = n_commit = n_tag = 0
    for oid, typ, data in cat_batch(a.repo, sorted(paths)):
        if typ == "blob":
            n_blob += 1
        elif typ == "commit":
            n_commit += 1
        elif typ == "tag":
            n_tag += 1
        else:
            if typ == "tree":
                for i, (v, _s) in enumerate(vals):
                    if v in data:
                        hits.setdefault(oid, set()).add(i)
            continue
        for i, (v, _s) in enumerate(vals):
            if v in data:
                hits.setdefault(oid, set()).add(i)
    print(f"проверено: файлов (версий) {n_blob}, коммитов {n_commit}, тегов {n_tag}; значений {len(vals)}; ссылки: {' '.join(refs)}")
    total = 0
    by_src: dict[str, dict] = {}
    for oid, idxs in sorted(hits.items()):
        kind = git(a.repo, "cat-file", "-t", oid).decode().strip()
        for i in sorted(idxs):
            total += 1
            g = by_src.setdefault(vals[i][1], {"versions": 0, "paths": set(), "commits": set(), "msgs": 0})
            if kind == "commit":
                g["msgs"] += 1
                g["commits"].add(oid[:10])
            else:
                g["versions"] += 1
                g["paths"].update(paths[oid])
                g["commits"].update(git(a.repo, "log", *refs, "--format=%h", f"--find-object={oid}").decode().split())
    for src, g in sorted(by_src.items()):
        shown = sorted(g["paths"])
        extra = f" … (+{len(shown) - 8})" if len(shown) > 8 else ""
        print(f"СОВПАДЕНИЕ: источник «{src}»: версий файлов {g['versions']}, сообщений коммитов {g['msgs']}, коммитов {len(g['commits'])}; "
              f"файлы: {', '.join(shown[:8])}{extra}")
    print(f"итого совпадений: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
