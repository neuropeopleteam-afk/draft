"""Геометрия таблицы командного протокола: сколько строк участников в каждом блоке команды.

Модель хорошо читает ФИО по порядку, но ошибается в границах объединённых ячеек «место/команда».
Границы блоков видны на изображении: в колонке «Место» горизонтальная линия есть только между командами,
в колонке «Состав» — между всеми участниками. Считаем линии и получаем точное число участников в каждом
блоке, затем режем упорядоченный список ФИО от модели по этим числам.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def _groups(xs: list[int], gap: int = 3) -> list[int]:
    out: list[list[int]] = []
    for x in xs:
        if out and x - out[-1][-1] <= gap:
            out[-1].append(x)
        else:
            out.append([x])
    return [(g[0] + g[-1]) // 2 for g in out]


def block_row_counts(img_path: Path, *, dark: int = 140, vthr: float = 0.5, hthr: float = 0.85,
                     place_col: int = 0, fio_col: int = 2) -> dict:
    """Вернуть {"vlines", "team_borders", "row_borders", "counts"} для страницы протокола.

    place_col / fio_col — номер колонки (0 — «Место», 2 — «Состав» в протоколах КР/ЧР; у протоколов
    с колонкой «Статус» номера те же, лишние колонки правее).
    """
    im = np.array(Image.open(img_path).convert("L")) < dark
    h, w = im.shape
    # вертикальные линии ищем в нижних 2/3 страницы (над таблицей — шапка документа)
    band = im[int(h * 0.35): int(h * 0.95)]
    v = _groups([x for x in range(w) if band[:, x].mean() > vthr], gap=4)
    # утолщаем по вертикали на ±2 px — линии слегка наклонены на сканах
    im = im | np.roll(im, 1, axis=0) | np.roll(im, -1, axis=0) | np.roll(im, 2, axis=0) | np.roll(im, -2, axis=0)
    if len(v) < fio_col + 2:
        return {"vlines": v, "team_borders": [], "row_borders": [], "counts": []}

    def hlines(x0: int, x1: int) -> list[int]:
        seg = im[:, x0 + 3: x1 - 3]
        f = seg.mean(axis=1)
        return _groups([y for y in range(h) if f[y] > hthr])

    team = hlines(v[place_col], v[place_col + 1])
    rows = hlines(v[fio_col], v[fio_col + 1])
    # шапка таблицы: первая граница «Состава», выше которой нет участников, — по первой линии блока
    counts = []
    for a, b in zip(team, team[1:]):
        counts.append(max(0, sum(1 for y in rows if a - 3 <= y <= b + 3) - 1))
    return {"vlines": v, "team_borders": team, "row_borders": rows, "counts": counts}
