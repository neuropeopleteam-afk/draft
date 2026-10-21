"""Числа в речи — словами по-русски, детерминированно (решение владельца 21.10 18:55).

Модель пишет числа цифрами, как в фактах («77,6 %», «1 646», «275–430 тыс. ₽»), а перед синтезом речи они
переводятся в слова здесь. Раньше модель писала числа словами сама и изредка сбивалась на английский («семьдесят seven»,
боевой 21.10 18:05; на 20 вопросах про цифры — 1 сбой). Субтитры остаются с цифрами, озвучка — словами.
Падеж: после «у, от, до, из, около, более, менее, свыше, с, без, для, кроме, после, порядка» — родительный, иначе
именительный (для речи этого достаточно). Цифры внутри латинских слов и кодов (v6, C-88QTWX, ISO 27001) не трогаются.
"""
from __future__ import annotations

import re

_U = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_U_F = {1: "одна", 2: "две"}
_TEEN = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать",
         "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUND = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
_U_G = ["нуля", "одного", "двух", "трёх", "четырёх", "пяти", "шести", "семи", "восьми", "девяти"]
_TEEN_G = ["десяти", "одиннадцати", "двенадцати", "тринадцати", "четырнадцати", "пятнадцати", "шестнадцати", "семнадцати",
           "восемнадцати", "девятнадцати"]
_TENS_G = ["", "", "двадцати", "тридцати", "сорока", "пятидесяти", "шестидесяти", "семидесяти", "восьмидесяти", "девяноста"]
_HUND_G = ["", "ста", "двухсот", "трёхсот", "четырёхсот", "пятисот", "шестисот", "семисот", "восьмисот", "девятисот"]

GEN_PREP = {"у", "от", "до", "из", "около", "более", "менее", "свыше", "с", "без", "для", "кроме", "после", "порядка",
            "больше", "меньше", "выше", "ниже", "среди", "вместо"}


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def _w999(n: int, gen: bool, fem: bool) -> list[str]:
    parts: list[str] = []
    h, r = divmod(n, 100)
    if h:
        parts.append((_HUND_G if gen else _HUND)[h])
    if 10 <= r < 20:
        parts.append((_TEEN_G if gen else _TEEN)[r - 10])
    else:
        tn, u = divmod(r, 10)
        if tn:
            parts.append((_TENS_G if gen else _TENS)[tn])
        if u:
            if gen:
                parts.append("одной" if fem and u == 1 else _U_G[u])
            else:
                parts.append(_U_F.get(u, _U[u]) if fem else _U[u])
    return parts


def int_words(n: int, *, gen: bool = False, fem: bool = False) -> str:
    """0 … 999 999 999 словами; «тысяча», а не «одна тысяча» (замечание владельца)."""
    n = int(n)
    if n < 0:
        return "минус " + int_words(-n, gen=gen, fem=fem)
    if n == 0:
        return _U_G[0] if gen else _U[0]
    out: list[str] = []
    mil, rest = divmod(n, 1_000_000)
    th, low = divmod(rest, 1000)
    if mil:
        if mil > 999:
            return str(n)
        out += _w999(mil, gen, False) if not (mil == 1) else []
        out.append(("миллиона" if mil == 1 else "миллионов") if gen else plural(mil, "миллион", "миллиона", "миллионов"))
    if th:
        if th == 1:
            out.append("тысячи" if gen else "тысяча")
        else:
            out += _w999(th, gen, True)
            out.append("тысяч" if gen else plural(th, "тысяча", "тысячи", "тысяч"))
    if low:
        out += _w999(low, gen, fem)
    return " ".join(out)


def _frac_words(i: int, frac: str, gen: bool) -> str:
    """77 и «6» → «семьдесят семь и шесть десятых»; «25» → «… и двадцать пять сотых»."""
    f = int(frac)
    if f == 0:
        return int_words(i, gen=gen)
    den = {1: ("десятая", "десятых", "десятой"), 2: ("сотая", "сотых", "сотой"), 3: ("тысячная", "тысячных", "тысячной")}
    one, many, one_g = den.get(len(frac), den[3])
    head = int_words(i, gen=gen) if i else ("нуля" if gen else "ноль")
    tail = int_words(f, gen=gen, fem=True)
    word = (one_g if f % 10 == 1 and f % 100 != 11 else many) if gen else (one if f % 10 == 1 and f % 100 != 11 else many)
    joiner = " целых " if i == 0 else " и "
    return f"{head}{joiner}{tail} {word}"


_NUM = r"\d{1,3}(?:[  ]\d{3})+|\d+"
_RX = re.compile(
    rf"(?<![A-Za-z0-9\-_/.])(?P<pm>±\s?)?(?P<n>{_NUM})(?:,(?P<f>\d{{1,3}}))?"
    rf"(?:\s?(?P<pct>%)|\s?(?P<unit>тыс\.|тыс\b|млн\.?|млрд\.?))?(?:\s?(?P<rub>₽))?(?![A-Za-z0-9_])")
_PREV = re.compile(r"([А-Яа-яЁё]+)\s*$")


_FEM_NOUN = re.compile(r"^(?:[а-яё]+[ая]|ступен[ьи]|част[ьи]|рол[ьи]|модел[ьи]|связ[ьи]|недел[ьи])$")
_NEUT_NOUN = re.compile(r"^[а-яё]+(?:ие|ье|ия|ья|о|ло|во)$")
_NEXT = re.compile(r"^\s*([А-Яа-яЁё]+)")


def _say(m: re.Match, before: str, after: str) -> str:
    raw_n = re.sub(r"[  ]", "", m.group("n"))
    if len(raw_n) > 9:
        return m.group(0)
    i, f = int(raw_n), m.group("f")
    prev = _PREV.search(before[-30:])
    if re.search(r"\b[A-Z]{2,}\s*$", before[-12:]):        # ISO 27001, GPT 4 — как написано
        return m.group(0)
    nxt = _NEXT.search(after)
    nw = nxt.group(1).lower() if nxt else ""
    if not f and 1900 <= i <= 2100 and nw.startswith("год"):   # «2026 год» — порядковое, оставляем цифрами
        return m.group(0)
    gen = bool(prev and prev.group(1).lower() in GEN_PREP)
    pct, unit, rub, pm = m.group("pct"), m.group("unit"), m.group("rub"), m.group("pm")
    if f:
        words = _frac_words(i, f, gen)
        if pct:
            words += " процента"
    else:
        d, dd = i % 10, i % 100
        fem = False
        if not unit and not pct and nw and dd not in (11, 12):
            if d == 1:   # «одна проверка», «одна ступень»; «одно задание»
                fem = bool(_FEM_NOUN.match(nw)) and not _NEUT_NOUN.match(nw) or nw.startswith(("ступен", "част", "рол", "модел"))
            elif d == 2:   # «две минуты», «две попытки»; «два задания», «два балла»
                fem = nw.endswith(("ы", "и"))
        words = int_words(i, gen=gen, fem=fem)
        if not unit and not pct and not gen and d == 1 and dd != 11 and nw and re.search(r"(?:ие|ье|о|е)$", nw):
            words = re.sub(r"один$", "одно", words)
        if pct:
            words += " " + ("процентов" if gen and i % 10 != 1 or gen and i % 100 == 11 else
                            "процента" if gen else plural(i, "процент", "процента", "процентов"))
    if unit:
        u = unit.rstrip(".")
        if u.startswith("тыс"):
            words += " " + ("тысяч" if gen or f else plural(i, "тысяча", "тысячи", "тысяч"))
        elif u.startswith("млн"):
            words += " " + ("миллионов" if gen or f else plural(i, "миллион", "миллиона", "миллионов"))
        else:
            words += " " + ("миллиардов" if gen or f else plural(i, "миллиард", "миллиарда", "миллиардов"))
    if rub:
        words += " рублей" if (unit or f or gen) else " " + plural(i, "рубль", "рубля", "рублей")
    if pm:
        words = "плюс-минус " + words
    return words


def spoken(text: str) -> str:
    """Текст для синтеза: числа словами; диапазоны «275–430» → «от двухсот семидесяти пяти до четырёхсот тридцати»."""
    if not text or not re.search(r"\d", text):
        return text
    t = text
    # диапазон без «от … до»: «275–430 тыс. ₽» → «от 275 до 430 тыс. ₽» (дальше — в родительном падеже)
    t = re.sub(rf"(?<![А-Яа-яЁёA-Za-z0-9])(?<!от )({_NUM})(,\d+)?\s?[–—-]\s?({_NUM})(?=(?:,\d+)?\s?(?:%|тыс|млн|₽|[А-Яа-яЁё]|$|[.,;!? ]))",
               lambda m: f"от {m.group(1)}{m.group(2) or ''} до {m.group(3)}", t)
    t = re.sub(r"(?<![\w])\+(?=\d)", "плюс ", t)
    out, pos = [], 0
    for m in _RX.finditer(t):
        out.append(t[pos:m.start()])
        out.append(_say(m, "".join(out), t[m.end():]))
        pos = m.end()
    out.append(t[pos:])
    return "".join(out)
