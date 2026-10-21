"""Адаптер английских текстов Djinni к конвейеру «Драфта» (свой код А17; код подбора А5 не меняется).

Что делает адаптер — только по ТЕКСТУ (Position + описание / Position + CV); структурные поля Djinni не читает:
1. Направление «Драфта» по тексту: backend / frontend / qa / data_ml / security или «вне направлений» (дизайн,
   менеджмент, продажи, DevOps, мобильная разработка, аналитики, 1С, игры …). Сначала — название (Position), затем, если
   название ничего не говорит, — частоты ключевых слов в тексте. Кандидат «вне направлений» в загрузку не попадает:
   в продукте его нет ни в одном из пяти направлений, подборка его не покажет.
2. Заявленный грейд по тексту (слово уровня в названии или стаж «N years» в тексте) — передаётся как заявленный
   (без θ: «грейд не подтверждён»); в балл не входит, фильтрует только при MATCH_UNCONFIRMED_BY_CLAIM=1.
3. Навыки — словарём продукта (catalog.dictionary.find_stack) по тексту плюс английские синонимы ниже (EN_SKILLS):
   заявленные (T0), без чисел теста.
Настраивается только на части РАЗРАБОТКИ (docs/realdata/djinni/DEV_LOG.md).
"""
from __future__ import annotations

import os
import re

VERSION = "djinni-adapter-v1"

# Название (Position): шаблоны по старшинству — первый совпавший определяет направление.
NONE_TITLE = [r"\bdesign", r"\bui/ux\b", r"\bux\b", r"\bartist\b", r"\banimator\b", r"\bmarketing", r"\bseo\b", r"\bsmm\b",
              r"\bsales\b", r"\bbusiness development", r"\blead generation", r"\brecruit", r"\bhr\b", r"\bhuman resource",
              r"\btalent", r"\bproject manager", r"\bproduct manager", r"\bproduct owner", r"\bscrum master",
              r"\bdelivery manager", r"\baccount manager", r"\boffice manager", r"\bcopywriter", r"\bcontent",
              r"\btechnical writer", r"\bwriter\b", r"\bsupport\b", r"\bhelp ?desk", r"\bcustomer", r"\boperator\b",
              r"\bdevops\b", r"\bsre\b", r"\bsite reliability", r"\bsys ?admin", r"\bsystem administrator",
              r"\bnetwork (?:engineer|administrator)", r"\binfrastructure", r"\bcloud engineer", r"\bandroid\b", r"\bios\b",
              r"\bswift\b", r"\bflutter\b", r"\bmobile\b", r"\breact native\b", r"\bunity\b", r"\bunreal\b", r"\bgame",
              r"\bbusiness analyst", r"\bsystems? analyst", r"\bdata analyst", r"\bbi (?:analyst|developer)", r"\bpower bi",
              r"\bdata engineer", r"\betl\b", r"\bdwh\b", r"\bdatabase (?:developer|administrator)", r"\bdba\b",
              r"\bsql developer", r"\b1c\b", r"\b1с\b", r"\bsalesforce", r"\bsap\b", r"\bembedded", r"\bfirmware",
              r"\bc\+\+", r"\bhardware", r"\belectronics", r"\bblockchain", r"\bsolidity", r"\bcto\b", r"\bceo\b",
              r"\bhead of\b", r"\bdirector\b", r"\bvp\b", r"\bteam ?lead\b(?!.*(?:python|java|php|\.net|node|golang|qa))",
              r"\bassistant", r"\baccountant", r"\bfinance", r"\blawyer", r"\btranslator", r"\bteacher", r"\btutor",
              r"\bmanager\b", r"\bcoordinator", r"\bconsultant", r"\bwordpress", r"\bshopify", r"\bwebflow",
              r"\brust\b", r"\bruby\b", r"\brails\b", r"\bscala\b", r"\belixir\b", r"\berlang\b", r"\bperl\b", r"\bdelphi\b"]
TITLE = [
    ("security", [r"\bsecurity", r"\bpentest", r"\bpenetration", r"\bcyber", r"\bappsec", r"\binfosec", r"\bsoc\b",
                  r"\bethical hack", r"\bred team", r"\bblue team", r"\bvulnerab"]),
    ("qa", [r"\bqa\b", r"\bq\.a\.", r"\bquality assurance", r"\bquality control", r"\btester\b", r"\btesting\b",
            r"\btest (?:automation )?engineer", r"\bsdet\b", r"\baqa\b", r"\bautomation (?:qa|engineer|tester)",
            r"\btest analyst", r"\bqc\b"]),
    ("data_ml", [r"\bdata scien", r"\bmachine learning", r"\bml\b", r"\bdeep learning", r"\bcomputer vision", r"\bnlp\b",
                 r"\bai\b", r"\bartificial intelligence", r"\bresearch (?:engineer|scientist)", r"\bllm\b", r"\bmlops\b",
                 r"\bcv engineer"]),
    ("frontend", [r"\bfront[- ]?end", r"\breact(?:\.?js)?\b", r"\bangular", r"\bvue", r"\bjavascript\b", r"\bjs\b",
                  r"\btypescript\b", r"\bnext\.?js", r"\bhtml", r"\blayout\b", r"\bweb developer", r"\bui developer",
                  r"\bmarkup"]),
    ("backend", [r"\bback[- ]?end", r"\bpython", r"\bdjango", r"\bflask", r"\bfastapi", r"\bjava\b", r"\bkotlin",
                 r"\bspring", r"\.net\b", r"\bdotnet", r"\bc#", r"\basp\.net", r"\bphp\b", r"\blaravel", r"\bsymfony",
                 r"\byii", r"\bnode(?:\.?js)?\b", r"\bnest\.?js", r"\bgolang\b", r"\bgo developer", r"\bgo engineer",
                 r"\bgo\b", r"\bfull[- ]?stack", r"\bsoftware (?:engineer|developer)", r"\bprogrammer", r"\bdeveloper",
                 r"\bengineer"]),
]
# Ключевые слова текста (если название ничего не решило): направление с наибольшим числом попаданий.
TEXT_KW = {
    "security": [r"\bpenetration test", r"\bpentest", r"\bowasp\b", r"\bburp\b", r"\bsiem\b", r"\bvulnerabilit",
                 r"\bsoc\b", r"\bmetasploit", r"\bnmap\b", r"\bkali\b", r"\binformation security", r"\bcybersecurity"],
    "qa": [r"\btest cases?\b", r"\bbug reports?\b", r"\bregression\b", r"\bselenium\b", r"\bcypress\b", r"\bjira\b",
           r"\btestrail\b", r"\bpostman\b", r"\bmanual testing", r"\bautomation testing", r"\bqa\b", r"\btest plan",
           r"\bsmoke\b", r"\bplaywright\b", r"\bappium\b", r"\btesting\b"],
    "data_ml": [r"\bmachine learning", r"\bdeep learning", r"\bpytorch\b", r"\btensorflow\b", r"\bscikit", r"\bsklearn",
                r"\bkeras\b", r"\bcomputer vision", r"\bnlp\b", r"\bneural", r"\bmodels?\b", r"\bpandas\b", r"\bnumpy\b",
                r"\bdata science", r"\bllm", r"\bkaggle\b"],
    "frontend": [r"\breact\b", r"\bredux\b", r"\bangular\b", r"\bvue\b", r"\bhtml\b", r"\bcss\b", r"\bsass\b", r"\bscss\b",
                 r"\bwebpack\b", r"\bnext\.?js", r"\bjavascript\b", r"\btypescript\b", r"\bfront[- ]?end", r"\bui\b",
                 r"\bresponsive\b", r"\bjquery\b"],
    "backend": [r"\bpython\b", r"\bdjango\b", r"\bflask\b", r"\bfastapi\b", r"\bjava\b", r"\bspring\b", r"\bhibernate\b",
                r"\.net\b", r"\bc#", r"\basp\.net", r"\bphp\b", r"\blaravel\b", r"\bsymfony\b", r"\bnode\.?js\b",
                r"\bexpress\b", r"\bnestjs\b", r"\bgolang\b", r"\bmicroservices?\b", r"\bpostgres", r"\bmysql\b",
                r"\brest ?api", r"\bback[- ]?end", r"\bkafka\b", r"\bredis\b"],
}
_C = lambda ps: [re.compile(p, re.I) for p in ps]  # noqa: E731
NONE_RE = _C(NONE_TITLE)
TITLE_RE = [(d, _C(ps)) for d, ps in TITLE]
TEXT_RE = {d: _C(ps) for d, ps in TEXT_KW.items()}
BACK_LANG_RE = _C([r"\bnode(?:\.?js)?\b", r"\bnest\.?js", r"\bphp\b", r"\blaravel", r"\bsymfony", r"\bpython",
                   r"\bdjango", r"\bjava\b", r"\bspring", r"\.net\b", r"\bc#", r"\bgolang\b", r"\bgo\b", r"\bback[- ]?end"])
HARD_NONE_RE = _C([r"\bdesign", r"\bmarketing", r"\bsales\b", r"\brecruit", r"\bdata engineer", r"\banalyst",
                   r"\bandroid\b", r"\bios\b", r"\bmobile\b", r"\bflutter\b", r"\bunity\b", r"\bgame", r"\b1c\b",
                   r"\bsalesforce", r"\bembedded", r"\bc\+\+", r"\bdata scien", r"\bmachine learning", r"\bqa\b"])
DIRECTIONS = ("backend", "frontend", "qa", "data_ml", "security")


def title_direction(title: str) -> str | None:
    """Направление по названию: «none» — явно вне направлений; None — название не решает."""
    t = title or ""
    hit = {d for d, rs in TITLE_RE if any(r.search(t) for r in rs)}
    # серверный язык или фреймворк в названии старше фронтенда («Full Stack Engineer | Node.js + React» → backend)
    if "frontend" in hit and not ({"security", "qa", "data_ml"} & hit) and any(r.search(t) for r in BACK_LANG_RE):
        return "backend"
    # конкретное направление старше «вне направлений», кроме общих слов (developer/engineer), см. порядок TITLE
    for d, rs in TITLE_RE[:4]:
        if d in hit:
            return d
    if any(r.search(t) for r in NONE_RE):
        # «мягкие» признаки (руководитель, DevOps, WordPress …) уступают серверному языку в названии
        if any(r.search(t) for r in BACK_LANG_RE) and not any(r.search(t) for r in HARD_NONE_RE):
            return "backend"
        return "none"
    if "backend" in hit:
        strong = [r for r in TITLE_RE[4][1][:-4]]  # без общих «software engineer / programmer / developer / engineer»
        if any(r.search(t) for r in strong):
            return "backend"
        return None
    return None


def text_direction(text: str) -> str:
    counts = {d: sum(len(r.findall(text)) for r in rs) for d, rs in TEXT_RE.items()}
    d, n = max(counts.items(), key=lambda x: x[1])
    return d if n >= 2 else "none"


def direction(title: str, body: str) -> str:
    d = title_direction(title)
    if d:
        return d
    return text_direction(f"{title}\n{body}")


GRADE_WORDS = [("senior", r"\bsenior\b|\bsr\.?\b|\blead\b|\bprincipal\b|\barchitect\b"),
               ("middle", r"\bmiddle\b|\bmid(?:-level)?\b|\bintermediate\b"),
               ("junior", r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b"),
               ("intern", r"\bintern(?:ship)?\b|\btrainee\b")]
YEARS = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*\+?\s*(?:years?|yrs?)\b", re.I)


_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*"
_MON_N = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
RANGE = re.compile(rf"(?:({_MON})|(\d{{1,2}})[./])?((?:19|20)\d\d)\s*(?:-|–|—|to|till|until)\s*(?:({_MON})|(\d{{1,2}})[./])?"
                   r"((?:19|20)\d\d|present|now|current|today|till now|nowadays)", re.I)
PRESENT_YEAR = 2023.5  # набор Djinni собран в 2023 г. (статья UNLP 2024): «по настоящее время» — середина 2023


def _ym(mon: str | None, num: str | None, year: str) -> float:
    m = _MON_N.get((mon or "")[:3].lower()) or (int(num) if num and 1 <= int(num) <= 12 else 6)
    return int(year) + (m - 1) / 12


def range_years(text: str) -> float | None:
    """Стаж по интервалам «Oct 2021 – Present», «2015-2019»: длина объединения интервалов, лет."""
    iv = []
    for m in RANGE.finditer(text or ""):
        a = _ym(m.group(1), m.group(2), m.group(3))
        end = m.group(6).lower()
        b = PRESENT_YEAR if not end[:1].isdigit() else _ym(m.group(4), m.group(5), end)
        if 1990 <= a < b <= PRESENT_YEAR + 0.01 and b - a <= 20:
            iv.append((a, b))
    if not iv:
        return None
    iv.sort()
    tot, (s, e) = 0.0, iv[0]
    for a, b in iv[1:]:
        if a > e:
            tot += e - s
            s, e = a, b
        else:
            e = max(e, b)
    return round(tot + e - s, 2)


def years(text: str) -> float | None:
    vals = [float(m.group(1).replace(",", ".")) for m in YEARS.finditer(text or "")]
    vals = [v for v in vals if 0 < v <= 25]
    if vals:
        return max(vals)
    return range_years(text) if os.environ.get("A17_RANGE_YEARS", "1") == "1" else None


def grade(title: str, body: str) -> str | None:
    for g, p in GRADE_WORDS:
        if re.search(p, title or "", re.I):
            return g
    y = years(body)
    if y is None:
        return None
    return "intern" if y < 0.5 else "junior" if y < 1.5 else "middle" if y < 4.5 else "senior"


# Английские синонимы, которых нет в словаре продукта: шаблон → тег каталога
EN_SKILLS = []


def skills(text: str) -> list[str]:
    from app.modules.catalog.dictionary import find_stack

    tags = list(find_stack(text))
    for p, tag in EN_SKILLS:
        if tag not in tags and re.search(p, text, re.I):
            tags.append(tag)
    return tags
