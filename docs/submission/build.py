#!/usr/bin/env python3
"""Сборка материалов сдачи «Драфт» одной командой.

    python3 docs/submission/build.py            # всё: README, документация (MD, PDF, DOCX), презентация, сценарий видео
    python3 docs/submission/build.py --text     # только тексты (README, DOCUMENTATION.md, SCRIPT.md) — без PDF/DOCX/PPTX
    python3 docs/submission/build.py --numbers <файл>   # другой NUMBERS.json (предпросмотр; в git не коммитить)

Цифры берутся только из docs/NUMBERS.json (через numfacts.py). Шаблоны — docs/submission/src/*.md:
  {{id}}            значение факта (например «87,9 %»)
  {{id.kn}}         «k из n»; {{id.ci}} — 95 % доверительный интервал; {{id.cond}} — условие измерения
  {{repo.<ключ>}}   описательные сведения из репозитория (правила продукта, число операций API)
  {{#id}}…{{/id}}   блок выводится, только если факт есть в NUMBERS.json; {{^id}}…{{/id}} — если факта нет
  {{numbers_table:<набор>}}  таблица «что измерено — значение — условие — пересчёт»
  {{libs_table}}    библиотеки и версии из backend/requirements.txt и frontend/package-lock.json
Факт, на который ссылается текст вне условного блока, но которого нет в NUMBERS.json, — ошибка сборки
(никаких «None» и чисел по умолчанию в материалах).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import numfacts as _n  # noqa: E402  (docs/submission/numfacts.py)

OUT = HERE / "out"

# Наборы строк для таблиц цифр: (id факта, подпись; если подпись пуста — берётся из факта)
TABLES = {
    "readme": [
        ("verdict_accuracy", "Верный итог проверки заявленного грейда (подтверждён / не подтверждён)"),
        ("confident_share", "Кандидатов получают уверенный ответ по основному тесту"),
        ("minutes_mean", "Среднее время теста"),
        ("match_bm25", "Подбор, для сравнения: поиск по тексту резюме (P@5)"),
        ("hh_direction_adj", "Вакансии hh.ru: направление после проверки спорных меток"),
        ("ac_filter", "Атаки на проверку ответов, перехваченные фильтром"),
        ("ac_chain_pierced", "Атаки, прошедшие всю цепочку защиты"),
        ("ac_honest_false", "Честные кандидаты, ошибочно отправленные на проверку"),
        ("fsp_athletes", "Спортсменов в индексе протоколов ФСП"),
        ("bank_checks_failed", "Ошибок автоматической проверки банка заданий"),
    ],
    "grade": [
        ("verdict_accuracy", ""), ("confident_share", ""), ("confident_accuracy", ""), ("followup_share", ""),
        ("exact_grade", ""), ("false_confirm_all", ""), ("gross_error", ""), ("retest_verdict", ""),
        ("retest_exact", ""), ("verdict_misspec", ""), ("verdict_rater_noise", ""), ("minutes_mean", ""),
        ("minutes_p90", ""), ("cheat_bots_confirmed", ""),
    ],
    "bank": [
        ("bank_families", ""), ("bank_practical", ""), ("bank_directions", ""), ("bank_variants", ""),
        ("bank_checks", ""), ("bank_checks_failed", ""), ("mutation", ""),
    ],
    "match": [
        ("match_p5", ""), ("match_p5_rep", ""), ("match_mrr", ""), ("match_bm25", ""), ("match_keywords", ""),
        ("match_no_test", ""), ("match_no_fsp", ""),
    ],
    "hh": [
        ("hh_site", ""), ("hh_direction", ""), ("hh_direction_adj", ""), ("hh_skills", ""),
        ("hh_confirmed_pool", ""), ("no_fsp_top5", ""), ("no_fsp_pool", ""),
    ],
    "ac": [
        ("ac_filter", ""), ("ac_fp", ""), ("ac_chain_pierced", ""), ("ac_honest_false", ""), ("ac_bot_detect", ""),
    ],
    "fsp": [
        ("fsp_documents", ""), ("fsp_events", ""), ("fsp_results", ""), ("fsp_athletes", ""), ("fsp_regions", ""),
        ("fsp_evsk", ""), ("fsp_ocr", ""),
    ],
    "load": [("load_p95", ""), ("load_users", "")],
}
TABLES["all"] = [r for k in ("grade", "bank", "match", "hh", "ac", "fsp", "load") for r in TABLES[k]]


class BuildError(Exception):
    pass


def md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def numbers_table(facts: dict, name: str, *, with_key: bool = False) -> str:
    """Таблица «что измерено — значение — условие №»; условия и команды пересчёта — списком под таблицей."""
    rows = [(fid, lab) for fid, lab in TABLES[name] if fid in facts]
    if not rows:
        return "_Цифры этого раздела пересчитываются; они появятся после следующей сборки._"
    conds: list[tuple[str, str]] = []
    out = ["| Что измерено | Значение | Условие |", "|---|---|---|"]
    for fid, lab in rows:
        f = facts[fid]
        c = (f["cond"], f["recompute"] or "")
        if c not in conds:
            conds.append(c)
        val = f["text"] + (f" ({f['kn']})" if f["kn"] else "") + (f"; {f['ci']}" if f["ci"] else "")
        lab = lab or (f["label"][:1].upper() + f["label"][1:])
        key = f" · `{f['key']}`" if with_key else ""
        out.append(f"| {md_cell(lab)}{key} | {md_cell(val)} | [{conds.index(c) + 1}] |")
    out.append("")
    for i, (c, rc) in enumerate(conds, 1):
        out.append(f"{i}. {c[:1].upper() + c[1:]}." + (f" Пересчёт: `{rc}`." if rc else ""))
    return "\n".join(out)


def pairs_table(pairs: dict) -> str:
    """Две колонки рядом: «стандартные условия» (заголовок) и «проверка на прочность»; обе всегда видны."""
    rows = pairs.get("pairs") or []
    if not rows:
        return ""
    conds: list[tuple[str, str]] = []

    def cell(v):
        if not v:
            return "пересчитывается"
        c = (v.get("cond") or "", v.get("recompute") or "")
        if c not in conds:
            conds.append(c)
        t = v["text"] + (f" ({v['kn']})" if v.get("kn") else "")
        return f"{t} [{conds.index(c) + 1}]"

    out = ["| Метрика | Стандартные условия (как в аналогичных решениях) | Проверка на прочность (наши жёсткие условия) |",
           "|---|---|---|"]
    for p in rows:
        lab = p["label"] + (f" — {p['hint']}" if p.get("hint") else "")
        out.append(f"| {md_cell(lab)} | {md_cell(cell(p.get('standard')))} | {md_cell(cell(p.get('hard')))} |")
    real = [r for r in pairs.get("real") or [] if r.get("value")]
    if real:
        out += ["", "| Реальные данные | Значение |", "|---|---|"]
        for r in real:
            out.append(f"| {md_cell(r['label'])} | {md_cell(cell(r['value']))} |")
    if conds:
        out.append("")
        for i, (c, rc) in enumerate(conds, 1):
            c = c or "условие — в docs/NUMBERS.json"
            out.append(f"{i}. {c[:1].upper() + c[1:]}." + (f" Пересчёт: `{rc}`." if rc else ""))
    return "\n".join(out)


# ---------- библиотеки ----------
def libs_table() -> str:
    lines = ["<!-- lint:off -->", ""]
    req = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8").splitlines()
    py = [l.split("#")[0].strip() for l in req if l.strip() and not l.strip().startswith("#")]
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    pkg = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lines.append("**Backend (Python, `backend/requirements.txt`, версии зафиксированы):**\n")
    lines.append("| Библиотека | Версия |\n|---|---|")
    for p in py:
        m = re.match(r"([A-Za-z0-9_.\-\[\]]+)\s*==\s*([^\s;]+)", p)
        if m:
            lines.append(f"| {m.group(1)} | {m.group(2)} |")
    lines.append("")
    lines.append("**Frontend (`frontend/package.json`, установленные версии — из `package-lock.json`):**\n")
    lines.append("| Пакет | Назначение | Версия |\n|---|---|---|")
    pk = lock.get("packages", {})
    for sect, purpose in (("dependencies", "в сборке сайта"), ("devDependencies", "сборка и проверка типов")):
        for name in sorted(pkg.get(sect, {})):
            v = (pk.get(f"node_modules/{name}") or {}).get("version") or pkg[sect][name]
            lines.append(f"| {name} | {purpose} | {v} |")
    lines.append("")
    comp = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    imgs = sorted(set(re.findall(r"^\s*image:\s*([^\s#]+)", comp, re.M)))
    froms = []
    for df in sorted(ROOT.glob("*/Dockerfile*")) + sorted(ROOT.glob("*/*/Dockerfile*")):
        try:
            for m in re.finditer(r"^FROM\s+(\S+)", df.read_text(encoding="utf-8"), re.M):
                froms.append((str(df.relative_to(ROOT)), m.group(1)))
        except Exception:
            pass
    lines.append("**Образы контейнеров:**\n")
    lines.append("| Где | Образ |\n|---|---|")
    for f, im in froms:
        lines.append(f"| `{f}` | `{im}` |")
    for im in imgs:
        lines.append(f"| `docker-compose.yml` | `{im}` |")
    lines += ["", "<!-- lint:on -->"]
    return "\n".join(lines)


# ---------- шаблоны ----------
TOKEN = re.compile(r"\{\{\s*([#^/]?)([a-zA-Z0-9_.:,]+)\s*\}\}")  # noqa


def render(tpl: str, facts: dict, repo: dict, *, src: str) -> str:
    # условные блоки (вложенность не нужна; обрабатываем изнутри наружу)
    blk = re.compile(r"\{\{([#^])([a-zA-Z0-9_]+)\}\}(.*?)\{\{/\2\}\}", re.S)
    while True:
        m = blk.search(tpl)
        if not m:
            break
        kind, fid, body = m.group(1), m.group(2), m.group(3)
        present = fid in facts or (fid.startswith("repo_") and fid[5:] in repo)
        keep = present if kind == "#" else not present
        tpl = tpl[:m.start()] + (body if keep else "") + tpl[m.end():]

    def sub(m: re.Match) -> str:
        kind, name = m.group(1), m.group(2)
        if kind:
            raise BuildError(f"{src}: незакрытый блок {{{{{kind}{name}}}}}")
        if name.startswith("numbers_table:"):
            arg = name.split(":", 1)[1]
            return numbers_table(facts, arg.replace(",key", ""), with_key=arg.endswith(",key"))
        if name == "libs_table":
            return libs_table()
        if name == "pairs_table":
            return pairs_table(repo.get("_pairs") or {})
        if name in ("numbers_generated_at", "recompute_all", "numbers_git_commit"):
            v = repo.get("_top", {}).get(name)
            if not v:
                raise BuildError(f"{src}: в NUMBERS.json нет поля {name}")
            return _n.date_ru(v) if name == "numbers_generated_at" else str(v)
        if name == "api_tags_table":
            rows = ["| Группа (тег OpenAPI) | Что делает | Операций |", "|---|---|---|"]
            for t in repo.get("api_tags", []):
                d = re.split(r"(?<=[.!?])\s", t["description"].strip())[0] if t["description"] else ""
                rows.append(f"| `{t['tag']}` | {md_cell(d)} | {_n.fint(t['ops'])} |")
            return "\n".join(rows)
        if name.startswith("repo."):
            k = name[5:]
            if k not in repo or isinstance(repo[k], (dict, list)):
                raise BuildError(f"{src}: нет сведения repo.{k}")
            v = repo[k]
            return _n.fint(v) if isinstance(v, (int, float)) else str(v)
        fid, _, attr = name.partition(".")
        if fid not in facts:
            raise BuildError(f"{src}: факт «{fid}» отсутствует в NUMBERS.json — оберните текст в {{{{#{fid}}}}}…{{{{/{fid}}}}}")
        f = facts[fid]
        if not attr:
            return f["text"]
        if attr not in f:
            raise BuildError(f"{src}: у факта {fid} нет поля {attr}")
        return str(f[attr])

    return TOKEN.sub(sub, tpl)


def github_md(doc: str) -> str:
    """Версия для просмотра в репозитории: без YAML-шапки и атрибутов заголовков pandoc, с номерами разделов."""
    meta = {}
    m = re.match(r"---\n(.*?)\n---\n", doc, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
        doc = doc[m.end():]
    head = f"# {meta.get('title', '')}\n\n**{meta.get('subtitle', '')}**\n\n{meta.get('author', '')}. {meta.get('date', '')}.\n\n" \
           "PDF и Word: [DOCUMENTATION.pdf](DOCUMENTATION.pdf), [DOCUMENTATION.docx](DOCUMENTATION.docx).\n"
    out, n1, n2, in_code = [], 0, 0, False
    for line in doc.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,2} ", line):
            unnum = ".unnumbered" in line
            title = re.sub(r"\s*\{[^}]*\}\s*$", "", line.lstrip("#").strip())
            if line.startswith("# "):
                if unnum:
                    line = f"## {title}"
                else:
                    n1 += 1
                    n2 = 0
                    line = f"## {n1}. {title}"
            else:
                n2 += 1
                line = f"### {n1}.{n2}. {title}" if n1 else f"### {title}"
        elif not in_code and line.startswith("### "):
            line = "#" + line
        out.append(line)
    body = "\n".join(out)
    body = re.sub(r"\[([^\]]+)\]\(#[a-z]+\)", r"\1", body)  # внутренние ссылки pandoc → текст
    return head + body + "\n"


def build_texts(res: dict) -> list[Path]:
    facts, repo = res["facts"], dict(res["repo"])
    repo["_pairs"] = res.get("pairs") or {}
    repo["_top"] = {k: res.get(k) for k in ("numbers_generated_at", "recompute_all", "numbers_git_commit")}
    targets = [
        (HERE / "src/README.md", ROOT / "README.md"),
        (HERE / "src/DOCUMENTATION.md", HERE / "DOCUMENTATION.md"),
        (ROOT / "docs/video/src/SCRIPT.md", ROOT / "docs/video/SCRIPT.md"),
    ]
    written = []
    for src, dst in targets:
        if not src.exists():
            continue
        txt = render(src.read_text(encoding="utf-8"), facts, repo, src=str(src.relative_to(ROOT)))
        if dst.name == "DOCUMENTATION.md":
            (OUT / "DOCUMENTATION.pandoc.md").write_text(txt, encoding="utf-8")
            txt = github_md(txt)
        dst.write_text(txt, encoding="utf-8")
        written.append(dst)
    return written


# Слова, которых не должно быть в материалах для жюри (правило владельца: без поставщиков и соперников)
BANNED = re.compile(r"(?i)\b(open ?router|eleven ?labs|anam|deepgram|webrtc|heygen|claude|sonnet|haiku|gpt|chatgpt|openai|"
                    r"deepseek|grok|kimi|moonshot|qwen|yandex ?gpt|gigachat|llama|mistral|gemini|anthropic|снотр\w*|"
                    r"postbox)\b")


def lint(path: Path) -> list[str]:
    bad = []
    off = False  # таблица библиотек (ТЗ 3.4: «библиотеки с версиями») — имена пакетов как в манифестах, без проверки
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "<!-- lint:off -->" in line:
            off = True
        if "<!-- lint:on -->" in line:
            off = False
        if off:
            continue
        for m in BANNED.finditer(line):
            bad.append(f"{path.relative_to(ROOT)}:{i}: «{m.group(0)}»")
    return bad


API_REF = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/api/[^`\s]+)`")


def check_api(path: Path) -> list[str]:
    """Каждый метод вида `POST /api/...` в тексте должен существовать в docs/api/openapi.json."""
    spec = json.loads((ROOT / "docs/api/openapi.json").read_text(encoding="utf-8")).get("paths", {})
    bad = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in API_REF.finditer(line):
            meth, p = m.group(1).lower(), m.group(2)
            if meth not in spec.get(p, {}):
                bad.append(f"{path.relative_to(ROOT)}:{i}: нет в OpenAPI «{m.group(1)} {p}»")
    return bad


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--numbers", default=str(ROOT / "docs/NUMBERS.json"))
    ap.add_argument("--text", action="store_true", help="только тексты, без PDF/DOCX/PPTX")
    a = ap.parse_args()

    numbers = json.loads(Path(a.numbers).read_text(encoding="utf-8"))
    res = _n.build(numbers)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "facts.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"цифр из NUMBERS.json: {len(res['facts'])}; нет в NUMBERS.json: {', '.join(res['missing']) or '—'}")
    try:
        bad = []
        for p in build_texts(res):
            print("  записано", p.relative_to(ROOT))
            bad += lint(p) + check_api(p)
        bad += lint(HERE / "CHANGELOG.md")  # не шаблон, но тоже для жюри
        if bad:
            raise BuildError("проверка текста не пройдена (поставщики/соперники, методы API):\n  " + "\n  ".join(bad))
    except BuildError as e:
        print("ОШИБКА СБОРКИ:", e, file=sys.stderr)
        return 2
    if a.text:
        return 0
    run([sys.executable, str(HERE / "render_docs.py")])
    pres = ROOT / "docs/presentation/build.mjs"
    if pres.exists():
        run(["node", str(pres)], cwd=str(pres.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
