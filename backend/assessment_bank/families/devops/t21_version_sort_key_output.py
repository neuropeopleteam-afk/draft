"""devops.release.t21_version_sort_key_output — predict_output (набор t21, порог Junior): sorted по строкам
против sorted с key (список чисел из split) для тегов релизов в Python.

Скрипт выкладки выбирает последний тег релиза. Сортировка строк сравнивает посимвольно: `v1.10.0` < `v1.9.2`, потому
что «1» < «9»; ключ `[int(p) for p in tag[1:].split(".")]` сравнивает номера как числа. Печатаются последний тег в
обоих порядках и весь список по версии. Ключ — независимая модель сравнения в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.release.t21_version_sort_key_output"

CTX = ["агент выкладки биллинга", "релизный бот каталога", "скрипт отката платёжного шлюза", "CI поиска",
       "агент обновления личного кабинета", "релизный бот CRM", "скрипт выкладки сервиса уведомлений"]
VARS = [("tags", "ver", "by_text", "by_ver"), ("releases", "key", "plain", "numeric"),
        ("versions", "parts", "as_str", "as_num")]


def _num(tag: str) -> tuple[int, ...]:
    return tuple(int(p) for p in tag[1:].split("."))


def _lex_key(tag: str) -> list[int]:
    return [ord(ch) for ch in tag]  # модель посимвольного сравнения строк (все символы ASCII)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    tv, fn, a, b = rng.choice(VARS)
    for _ in range(500):
        major = rng.randint(1, 3)
        k = rng.randint(4, 5)
        tags = set()
        while len(tags) < k:
            mj = major + rng.choice([0, 0, 0, 1]) if rng.random() < 0.3 else major
            mn = rng.choice([rng.randint(1, 9), rng.randint(10, 14)])
            pt = rng.choice([0, rng.randint(1, 12)])
            tags.add(f"v{mj}.{mn}.{pt}")
        tags = sorted(tags)  # множество → список в фиксированном порядке, затем перемешивание из rng
        rng.shuffle(tags)
        by_text = sorted(tags, key=_lex_key)
        by_ver = sorted(tags, key=_num)
        if by_text[-1] != by_ver[-1] and by_text != by_ver:
            break
    else:
        raise RuntimeError("t21_version_sort_key: не подобраны теги")
    code = (f"{tv} = {tags!r}\n"
            f"def {fn}(tag):\n"
            "    return [int(p) for p in tag[1:].split(\".\")]\n"
            f"{a} = sorted({tv})\n"
            f"{b} = sorted({tv}, key={fn})\n"
            f"print({a}[-1], {b}[-1])\n"
            f'print(" ".join({b}))')
    out = f"{by_text[-1]} {by_ver[-1]}\n{' '.join(by_ver)}"
    x, y = next((x, y) for i, x in enumerate(by_text) for y in by_text[i + 1:] if _num(x) > _num(y))
    j = next(i for i in range(min(len(x), len(y))) if x[i] != y[i])
    expl = (f"sorted без key сравнивает строки посимвольно — решает первый различающийся символ (у «{x}» и «{y}» "
            f"это «{x[j]}» < «{y[j]}», поэтому «{x}» раньше): по тексту {' '.join(by_text)}, последний — "
            f"«{by_text[-1]}». Ключ {fn} "
            f"превращает тег в список чисел и сравнивает номера как числа: {' < '.join(by_ver)}. Вывод: "
            f"«{by_text[-1]} {by_ver[-1]}» и «{' '.join(by_ver)}».")
    stem = f"{ctx[0].upper() + ctx[1:]} выбирает самый новый тег релиза из списка."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"tags": tags}, language="python")
