"""Сводка покрытия и тестов бэкенда для CI и значок покрытия для README.

    python tools/ci/coverage_report.py --coverage backend/coverage.xml --junit backend/junit.xml \
        [--label "SQLite"] [--badge docs/badges/coverage.svg] [--tests-badge docs/badges/tests.svg]

Печатает Markdown (итог, число тестов и время, 10 модулей с наименьшим покрытием); если задан
$GITHUB_STEP_SUMMARY — дописывает туда. С --badge перерисовывает SVG-значок (без внешних сервисов: репозиторий
открывается к сдаче, а shields.io/gist потребовали бы токенов). Порог покрытия проверяет сам pytest-cov
(fail_under в backend/pyproject.toml), здесь только отчёт.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import xml.etree.ElementTree as ET


def coverage_stats(path: Path) -> tuple[float, int, int, list[tuple[str, float, int]]]:
    root = ET.parse(path).getroot()
    rate = float(root.get("line-rate", 0)) * 100
    valid, covered = int(root.get("lines-valid", 0)), int(root.get("lines-covered", 0))
    files = []
    for cls in root.iter("class"):
        lines = cls.find("lines")
        n = len(lines) if lines is not None else 0
        if n >= 20:
            files.append((cls.get("filename", "?"), float(cls.get("line-rate", 0)) * 100, n))
    files.sort(key=lambda x: x[1])
    return rate, valid, covered, files


def junit_stats(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    out = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
    for s in suites:
        for k in ("tests", "failures", "errors", "skipped"):
            out[k] += int(s.get(k, 0))
        out["time"] += float(s.get("time", 0))
    return out


def badge_svg(label: str, value: str, color: str) -> str:
    # ширина по числу символов (шрифт Verdana 11px ≈ 6,5 px на символ), как у значков shields.io
    lw, vw = 10 + int(len(label) * 6.5), 10 + int(len(value) * 7)
    w = lw + vw
    u = hashlib.md5(label.encode()).hexdigest()[:6]  # id градиента и маски уникальны: значки бывают на одной странице
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{label}: {value}">'
        f'<title>{label}: {value}</title>'
        f'<linearGradient id="s{u}" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r{u}"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r{u})"><rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{vw}" height="20" fill="{color}"/><rect width="{w}" height="20" fill="url(#s{u})"/></g>'
        f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{lw / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{label}</text>'
        f'<text x="{lw / 2:.1f}" y="14">{label}</text>'
        f'<text x="{lw + vw / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{value}</text>'
        f'<text x="{lw + vw / 2:.1f}" y="14">{value}</text></g></svg>\n'
    )


def color_for(pct: float) -> str:
    return "#4c1" if pct >= 90 else "#97ca00" if pct >= 80 else "#dfb317" if pct >= 70 else "#e05d44"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", type=Path, required=True)
    ap.add_argument("--junit", type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--badge", type=Path)
    ap.add_argument("--tests-badge", type=Path)
    a = ap.parse_args()

    rate, valid, covered, files = coverage_stats(a.coverage)
    title = f"### Бэкенд{': ' + a.label if a.label else ''}"
    lines = [title, ""]
    if a.junit and a.junit.exists():
        j = junit_stats(a.junit)
        passed = j["tests"] - j["failures"] - j["errors"] - j["skipped"]
        lines.append(f"Тестов: **{j['tests']}** (прошло {passed}, упало {j['failures'] + j['errors']}, "
                     f"пропущено {j['skipped']}); время: {j['time']:.0f} с.")
        if a.tests_badge:
            a.tests_badge.parent.mkdir(parents=True, exist_ok=True)
            ok = j["failures"] + j["errors"] == 0
            a.tests_badge.write_text(badge_svg("тесты бэкенда", f"{passed} прошли" if ok else f"{j['failures'] + j['errors']} упали",
                                               "#4c1" if ok else "#e05d44"), "utf-8")
    lines += [f"Покрытие строк (pytest-cov, пакет app): **{rate:.1f} %** ({covered} из {valid}).", "",
              "| Наименее покрытые модули (от 20 строк) | Покрытие | Строк |", "|---|---:|---:|"]
    lines += [f"| `{f}` | {r:.0f} % | {n} |" for f, r, n in files[:10]]
    text = "\n".join(lines) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if a.badge:
        a.badge.parent.mkdir(parents=True, exist_ok=True)
        a.badge.write_text(badge_svg("покрытие", f"{rate:.0f}%", color_for(rate)), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
